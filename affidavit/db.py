"""SQLite state store. Dependency-free, fully local, single file."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_files (
    id            INTEGER PRIMARY KEY,
    src_path      TEXT NOT NULL,
    src_relpath   TEXT NOT NULL UNIQUE,
    src_name      TEXT NOT NULL,
    ext           TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    mtime         REAL,
    sha256        TEXT,
    doc_id        INTEGER REFERENCES documents(id),
    role          TEXT NOT NULL DEFAULT 'unknown',
        -- canonical | duplicate | unsupported | failed
    dup_of_doc_id INTEGER REFERENCES documents(id),
    note          TEXT,
    first_seen    TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    id             INTEGER PRIMARY KEY,
    sha256         TEXT NOT NULL,
    text_fingerprint TEXT,
    canonical_src  TEXT NOT NULL,
    ext            TEXT,
    page_count     INTEGER,
    text_chars     INTEGER,
    has_text_layer INTEGER,
    needs_ocr      INTEGER DEFAULT 0,
    pdf_path       TEXT,
    pdf_status     TEXT DEFAULT 'pending',
        -- pending | ok | skipped_no_converter | failed | passthrough
    status_detail  TEXT,
    title_guess    TEXT,
    doc_type       TEXT,
    doc_date       TEXT,
    date_source    TEXT,
    privilege_flags TEXT,
    party_hits     TEXT,
    summary        TEXT,
    created_at     TEXT,
    updated_at     TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    doc_id           INTEGER PRIMARY KEY REFERENCES documents(id),
    schedule         TEXT,
        -- A | B | C | excluded
    privilege_ground TEXT,
    description      TEXT,
    reviewed_by      TEXT,
    reviewed_at      TEXT,
    notes            TEXT,
    -- Soft lock so two reviewers do not silently overwrite each other.
    -- Advisory only: the console warns, it never refuses an edit.
    editing_by       TEXT,
    editing_since    TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_doc ON source_files(doc_id);
CREATE INDEX IF NOT EXISTS idx_doc_sha    ON documents(sha256);

-- ---------------------------------------------------------------- collections
-- A collection is a user-named bundle of documents destined for Zibbit. The
-- folder name is whatever the user chooses; there is no fixed A/B/C taxonomy.
-- Collections are SHARED: everyone signed in sees every collection, so a
-- colleague can pick up work. `created_by` records who started it.
CREATE TABLE IF NOT EXISTS collections (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT DEFAULT '',
    created_by   TEXT,
    created_at   TEXT,
    updated_at   TEXT,
    exported_at  TEXT,
    export_path  TEXT,
    version      INTEGER NOT NULL DEFAULT 1
);

-- Membership carries per-collection presentation: what this document is called
-- *in this bundle*, and where it sits. The same document can appear in several
-- collections with different names.
--
-- `version` drives conflict detection: a client sends the version it last saw,
-- and the write is refused if someone else has changed the row since. That is
-- what stops two people silently overwriting each other in a shared pool.
CREATE TABLE IF NOT EXISTS collection_items (
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    doc_id        INTEGER NOT NULL REFERENCES documents(id)   ON DELETE CASCADE,
    position      INTEGER NOT NULL DEFAULT 0,
    display_name  TEXT DEFAULT '',
    note          TEXT DEFAULT '',
    added_by      TEXT,
    added_at      TEXT,
    version       INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (collection_id, doc_id)
);

-- Free-form tags, namespaced by source so user tags survive a re-ingest.
--   source='auto'  - written by the pipeline (doc_type, date, privilege...)
--   source='user'  - entered by a person and never overwritten
CREATE TABLE IF NOT EXISTS doc_tags (
    doc_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    key     TEXT NOT NULL,
    value   TEXT DEFAULT '',
    source  TEXT NOT NULL DEFAULT 'user',
    PRIMARY KEY (doc_id, key, source)
);

CREATE INDEX IF NOT EXISTS idx_items_collection ON collection_items(collection_id);
CREATE INDEX IF NOT EXISTS idx_items_doc        ON collection_items(doc_id);
CREATE INDEX IF NOT EXISTS idx_tags_doc         ON doc_tags(doc_id);

-- What the folder watcher has done, and its state (heartbeat, lock).
CREATE TABLE IF NOT EXISTS sync_events (
    id     INTEGER PRIMARY KEY,
    ts     TEXT NOT NULL,
    kind   TEXT NOT NULL,
    detail TEXT,
    path   TEXT
);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Every file the folder watcher has taken, by content hash.
--
-- Without this, a file the pipeline cannot use (a .zip, say) stays in the drop
-- folder and is copied in again on every scan, producing endless copies. The
-- drop folder is the user's, so the file cannot simply be moved away.
--
-- The destination is stored because the record is only meaningful while that
-- copy still exists. Clearing the library deletes the copies, and a record
-- without a destination would then refuse the file forever.
CREATE TABLE IF NOT EXISTS sync_files (
    sha256    TEXT NOT NULL,
    name      TEXT,
    dest      TEXT,
    first_seen TEXT,
    PRIMARY KEY (sha256)
);

CREATE INDEX IF NOT EXISTS idx_sync_events_ts ON sync_events(ts DESC);
"""

# Columns added after the first release. Applied on open so an existing
# database keeps working without being rebuilt.
MIGRATIONS: list[tuple[str, str, str]] = [
    ("decisions", "editing_by", "TEXT"),
    ("decisions", "editing_since", "TEXT"),
    ("collections", "version", "INTEGER NOT NULL DEFAULT 1"),
    ("collection_items", "version", "INTEGER NOT NULL DEFAULT 1"),
    # Finalised bundles move to output/collections/finished/ and drop out of
    # the console, so the collections list only shows live work.
    ("collections", "status", "TEXT NOT NULL DEFAULT 'draft'"),
    ("collections", "finalised_at", "TEXT"),
    ("collections", "finalised_by", "TEXT"),
    ("collections", "bundle_hash", "TEXT"),
    # OCR produces a separate searchable copy; the exported scan is untouched.
    ("documents", "ocr_path", "TEXT"),
    ("documents", "ocr_status", "TEXT"),
    ("documents", "ocr_chars", "INTEGER DEFAULT 0"),
    ("documents", "ocr_confidence", "REAL"),
    ("documents", "ocr_detail", "TEXT"),
    ("documents", "ocr_at", "TEXT"),
    # Marks that conversion and metadata extraction have been done. Needed
    # because ingest() already sets text_fingerprint, so that column cannot be
    # used to tell "not yet read" from "read".
    ("documents", "profiled_at", "TEXT"),
    # The library copy of a file taken from the drop folder. The "already taken"
    # record is only meaningful while this exists, so clearing the library lets
    # the same file be taken again instead of being refused forever.
    ("sync_files", "dest", "TEXT"),
]

SCHEDULES = ("A", "B", "C")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path, check_same_thread: bool = True) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def connect_for_thread(db_path: Path) -> sqlite3.Connection:
    """Open a connection usable from the calling thread.

    The review console is threaded, so each request gets its own connection.
    Handlers also hold a lock, because a read-modify-write through two racing
    connections could otherwise lose a decision.
    """
    return connect(db_path, check_same_thread=False)


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the first release, if missing."""
    for table, column, decl in MIGRATIONS:
        try:
            existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        except sqlite3.OperationalError:
            continue
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.commit()


def claim_document(conn: sqlite3.Connection, doc_id: int, username: str) -> None:
    """Record who is currently editing a document. Advisory, not enforcing."""
    now = utcnow()
    conn.execute(
        """INSERT INTO decisions (doc_id, editing_by, editing_since)
           VALUES (?,?,?)
           ON CONFLICT(doc_id) DO UPDATE SET editing_by=excluded.editing_by,
                                             editing_since=excluded.editing_since""",
        (doc_id, username, now),
    )
    conn.commit()


def stale_claims(conn: sqlite3.Connection, hours: int = 8) -> int:
    """Release advisory locks abandoned for longer than `hours`."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    cur = conn.execute(
        "UPDATE decisions SET editing_by=NULL, editing_since=NULL "
        "WHERE editing_since IS NOT NULL AND editing_since < ?",
        (cutoff,),
    )
    conn.commit()
    return cur.rowcount


# ---------------------------------------------------------------- collections

class CollectionError(Exception):
    """A user-facing problem with a collection operation."""


class ConflictError(CollectionError):
    """Someone else changed this row since the client last read it.

    Raised instead of quietly overwriting. The caller is told what the current
    value is, so a human can decide rather than losing their typing.
    """

    def __init__(self, message: str, current: dict | None = None):
        super().__init__(message)
        self.current = current or {}


def safe_folder_name(name: str) -> str:
    """Turn a user-supplied name into a filesystem-safe folder name.

    Kept readable on purpose: the lawyer will see this folder in Explorer.
    """
    import re

    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", (name or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    if not cleaned:
        raise CollectionError("A collection needs a name.")
    return cleaned[:120]


def create_collection(conn: sqlite3.Connection, name: str, description: str,
                      username: str) -> int:
    folder = safe_folder_name(name)
    now = utcnow()
    try:
        cur = conn.execute(
            """INSERT INTO collections (name, description, created_by, created_at, updated_at)
               VALUES (?,?,?,?,?)""",
            (folder, description or "", username, now, now),
        )
    except sqlite3.IntegrityError as exc:
        raise CollectionError(f"A collection called '{folder}' already exists.") from exc
    conn.commit()
    return int(cur.lastrowid)


def rename_collection(conn: sqlite3.Connection, collection_id: int, name: str) -> None:
    folder = safe_folder_name(name)
    try:
        conn.execute("UPDATE collections SET name=?, updated_at=? WHERE id=?",
                     (folder, utcnow(), collection_id))
    except sqlite3.IntegrityError as exc:
        raise CollectionError(f"A collection called '{folder}' already exists.") from exc
    conn.commit()


def delete_collection(conn: sqlite3.Connection, collection_id: int) -> None:
    conn.execute("DELETE FROM collection_items WHERE collection_id=?", (collection_id,))
    conn.execute("DELETE FROM collections WHERE id=?", (collection_id,))
    conn.commit()


def touch_collection(conn: sqlite3.Connection, collection_id: int) -> None:
    conn.execute("UPDATE collections SET updated_at=? WHERE id=?", (utcnow(), collection_id))
    conn.commit()


def list_collections(conn: sqlite3.Connection, include_finished: bool = False) -> list[dict]:
    """Live collections. Finalised ones are hidden unless asked for.

    A finalised bundle has been handed over to Zibbit; keeping it in the working
    list would clutter the console and invite edits to something already
    delivered.
    """
    where = "" if include_finished else "WHERE COALESCE(c.status,'draft') <> 'finalised'"
    try:
        rows = conn.execute(
            f"""SELECT c.*,
                      (SELECT COUNT(*) FROM collection_items i
                        WHERE i.collection_id = c.id) AS item_count,
                      (SELECT COALESCE(SUM(d.page_count), 0)
                         FROM collection_items i
                         JOIN documents d ON d.id = i.doc_id
                        WHERE i.collection_id = c.id) AS page_total,
                      (SELECT COUNT(*) FROM collection_items i
                         JOIN documents d ON d.id = i.doc_id
                        WHERE i.collection_id = c.id AND d.needs_ocr = 1) AS needs_ocr,
                      (SELECT COUNT(*) FROM collection_items i
                         JOIN documents d ON d.id = i.doc_id
                        WHERE i.collection_id = c.id
                          AND d.pdf_status NOT IN ('ok', 'passthrough')) AS not_converted,
                      -- Still being prepared by the watcher: conversion or
                      -- metadata reading has not finished. Exporting now would
                      -- produce an unnamed, undated file.
                      (SELECT COUNT(*) FROM collection_items i
                         JOIN documents d ON d.id = i.doc_id
                        WHERE i.collection_id = c.id
                          AND (d.pdf_path IS NULL OR d.profiled_at IS NULL)) AS not_ready
               FROM collections c
               {where}
               ORDER BY c.updated_at DESC, c.id DESC"""
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def finalise_collection(conn: sqlite3.Connection, collection_id: int,
                        bundle_path: str, bundle_hash: str, username: str) -> None:
    now = utcnow()
    conn.execute(
        """UPDATE collections
           SET status='finalised', finalised_at=?, finalised_by=?,
               bundle_hash=?, export_path=?, exported_at=?, updated_at=?
           WHERE id=?""",
        (now, username, bundle_hash, bundle_path, now, now, collection_id),
    )
    conn.commit()


def get_collection(conn: sqlite3.Connection, collection_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM collections WHERE id=?", (collection_id,)).fetchone()
    return dict(row) if row else None


def collection_items(conn: sqlite3.Connection, collection_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT d.*, i.position, i.display_name, i.note, i.added_by, i.added_at,
                  i.version AS item_version
           FROM collection_items i
           JOIN documents d ON d.id = i.doc_id
           WHERE i.collection_id = ?
           ORDER BY i.position, i.doc_id""",
        (collection_id,),
    ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        # `version` is what the client sends back to detect a conflicting edit.
        # The documents table has no version column, so this is unambiguous.
        item["version"] = item.pop("item_version", 1) or 1
        out.append(item)
    return out


def add_to_collection(conn: sqlite3.Connection, collection_id: int,
                      doc_ids: list[int], username: str) -> int:
    """Add documents to a collection, appended in the order given."""
    now = utcnow()
    row = conn.execute(
        "SELECT COALESCE(MAX(position), 0) m FROM collection_items WHERE collection_id=?",
        (collection_id,),
    ).fetchone()
    pos = int(row["m"])
    added = 0
    for doc_id in doc_ids:
        pos += 1
        cur = conn.execute(
            """INSERT INTO collection_items
                   (collection_id, doc_id, position, added_by, added_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(collection_id, doc_id) DO NOTHING""",
            (collection_id, doc_id, pos, username, now),
        )
        added += cur.rowcount
    touch_collection(conn, collection_id)
    return added


def remove_from_collection(conn: sqlite3.Connection, collection_id: int,
                           doc_ids: list[int]) -> int:
    removed = 0
    for doc_id in doc_ids:
        cur = conn.execute(
            "DELETE FROM collection_items WHERE collection_id=? AND doc_id=?",
            (collection_id, doc_id),
        )
        removed += cur.rowcount
    # Close the gap left by the removal, otherwise positions keep counting from
    # the original high-water mark and the exported order stops matching what
    # the user sees.
    for pos, row in enumerate(collection_items(conn, collection_id), start=1):
        conn.execute(
            "UPDATE collection_items SET position=? WHERE collection_id=? AND doc_id=?",
            (pos, collection_id, row["id"]),
        )
    touch_collection(conn, collection_id)
    return removed


def set_item_field(conn: sqlite3.Connection, collection_id: int, doc_id: int,
                   field: str, value: str, expected_version: int | None = None) -> int:
    """Update one field on a collection item, returning the new version.

    When `expected_version` is supplied and does not match, the row has been
    changed by someone else and the write is refused rather than silently
    discarding their work.
    """
    if field not in ("display_name", "note"):
        raise CollectionError(f"Cannot set '{field}' on a collection item.")

    row = conn.execute(
        f"SELECT {field} AS current_value, version FROM collection_items "
        "WHERE collection_id=? AND doc_id=?",
        (collection_id, doc_id),
    ).fetchone()
    if row is None:
        raise CollectionError("That document is no longer in this collection.")

    if expected_version is not None and int(row["version"]) != int(expected_version):
        raise ConflictError(
            "Someone else changed this while you were editing.",
            {"field": field, "current_value": row["current_value"],
             "version": row["version"]},
        )

    conn.execute(
        f"UPDATE collection_items SET {field}=?, version=version+1 "
        "WHERE collection_id=? AND doc_id=?",
        (value, collection_id, doc_id),
    )
    touch_collection(conn, collection_id)
    return int(row["version"]) + 1


def set_collection_fields(conn: sqlite3.Connection, collection_id: int,
                          name: str | None = None, description: str | None = None,
                          expected_version: int | None = None) -> int:
    """Rename or re-describe a collection, with the same conflict protection."""
    row = conn.execute(
        "SELECT name, description, version FROM collections WHERE id=?", (collection_id,)
    ).fetchone()
    if row is None:
        raise CollectionError("That collection no longer exists.")

    if expected_version is not None and int(row["version"]) != int(expected_version):
        raise ConflictError(
            "Someone else renamed or edited this collection.",
            {"name": row["name"], "description": row["description"],
             "version": row["version"]},
        )

    new_name = safe_folder_name(name) if name is not None else row["name"]
    new_desc = description if description is not None else row["description"]
    try:
        conn.execute(
            "UPDATE collections SET name=?, description=?, updated_at=?, version=version+1 "
            "WHERE id=?",
            (new_name, new_desc, utcnow(), collection_id),
        )
    except sqlite3.IntegrityError as exc:
        raise CollectionError(f"A collection called '{new_name}' already exists.") from exc
    conn.commit()
    return int(row["version"]) + 1


def move_item(conn: sqlite3.Connection, collection_id: int, doc_id: int,
              direction: int) -> None:
    """Move one item up (-1) or down (+1) within its collection."""
    items = collection_items(conn, collection_id)
    ids = [i["id"] for i in items]
    if doc_id not in ids:
        return
    idx = ids.index(doc_id)
    target = idx + direction
    if target < 0 or target >= len(ids):
        return
    ids[idx], ids[target] = ids[target], ids[idx]
    for pos, d_id in enumerate(ids, start=1):
        conn.execute(
            "UPDATE collection_items SET position=? WHERE collection_id=? AND doc_id=?",
            (pos, collection_id, d_id),
        )
    touch_collection(conn, collection_id)


def reorder_collection(conn: sqlite3.Connection, collection_id: int,
                       doc_ids: list[int]) -> int:
    """Set the order of a collection from a full list of document ids."""
    current = {i["id"] for i in collection_items(conn, collection_id)}
    ordered = [d for d in doc_ids if d in current]
    # Anything the caller omitted keeps its relative place at the end.
    ordered += [d for d in current if d not in ordered]
    for pos, doc_id in enumerate(ordered, start=1):
        conn.execute(
            "UPDATE collection_items SET position=? WHERE collection_id=? AND doc_id=?",
            (pos, collection_id, doc_id),
        )
    touch_collection(conn, collection_id)
    return len(ordered)


# ---------------------------------------------------------------- tags

def set_tags(conn: sqlite3.Connection, doc_id: int, tags: dict[str, str],
             source: str = "user") -> None:
    for key, value in tags.items():
        if not key:
            continue
        conn.execute(
            """INSERT INTO doc_tags (doc_id, key, value, source) VALUES (?,?,?,?)
               ON CONFLICT(doc_id, key, source) DO UPDATE SET value=excluded.value""",
            (doc_id, str(key)[:60], str(value)[:400], source),
        )
    conn.commit()


def tags_for(conn: sqlite3.Connection, doc_id: int) -> dict[str, str]:
    rows = conn.execute(
        "SELECT key, value, source FROM doc_tags WHERE doc_id=? ORDER BY source, key",
        (doc_id,),
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


def all_tags(conn: sqlite3.Connection) -> dict[int, dict[str, str]]:
    """Tags for every document, keyed by doc_id. Avoids N+1 queries."""
    out: dict[int, dict[str, str]] = {}
    for r in conn.execute(
        "SELECT doc_id, key, value FROM doc_tags ORDER BY source, key"
    ):
        out.setdefault(r["doc_id"], {})[r["key"]] = r["value"]
    return out


def reset(conn: sqlite3.Connection) -> None:
    """Drop and recreate everything. Used by --fresh."""
    for t in ("decisions", "source_files", "documents"):
        conn.execute(f"DROP TABLE IF EXISTS {t}")
    conn.commit()
    init(conn)


def reset_library(conn: sqlite3.Connection, cfg) -> dict:
    """Clear the record so the library is read fresh from what is on disk.

    Used by the console's "Start fresh" button, for the moment a new user
    replaces the sample documents with their own.

    Nothing is deleted from intake/source unless the caller asks: the samples
    are generated by this program, so removing them is safe, but a real
    document must never be removed because a button was pressed.
    """
    import shutil

    removed = 0
    cfg.source_dir.mkdir(parents=True, exist_ok=True)
    for child in list(cfg.source_dir.iterdir()):
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink()
            removed += 1
        except OSError:
            pass

    # Derived files only. The user's documents are not here.
    for d in (cfg.work_dir / "normalized", cfg.work_dir / "ocr"):
        shutil.rmtree(d, ignore_errors=True)
    for d in (cfg.collections_dir,):
        shutil.rmtree(d, ignore_errors=True)

    reset(conn)
    conn.commit()
    conn.execute("DELETE FROM sync_state")
    conn.commit()
    for table in ("sync_events",):
        try:
            conn.execute(f"DELETE FROM {table}")
        except sqlite3.Error:
            pass
    conn.commit()
    return {"removed": removed}


# ---------------------------------------------------------------- helpers

def upsert_document(conn: sqlite3.Connection, **fields) -> int:
    """Insert a document, or return the existing id for the same sha256."""
    sha = fields.get("sha256")
    row = conn.execute("SELECT id FROM documents WHERE sha256=?", (sha,)).fetchone()
    now = utcnow()
    if row:
        doc_id = int(row["id"])
        sets = ", ".join(f"{k}=?" for k in fields if k != "sha256")
        vals = [v for k, v in fields.items() if k != "sha256"]
        if sets:
            conn.execute(
                f"UPDATE documents SET {sets}, updated_at=? WHERE id=?",
                (*vals, now, doc_id),
            )
    else:
        cols = ["created_at", "updated_at", *fields.keys()]
        vals = [now, now, *fields.values()]
        q = f"INSERT INTO documents ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
        cur = conn.execute(q, vals)
        doc_id = int(cur.lastrowid)
    conn.commit()
    return doc_id


def record_source(conn: sqlite3.Connection, **fields) -> int:
    """Insert or update a source file row keyed on its relative path."""
    rel = fields["src_relpath"]
    row = conn.execute(
        "SELECT id FROM source_files WHERE src_relpath=?", (rel,)
    ).fetchone()
    if row:
        sid = int(row["id"])
        sets = ", ".join(f"{k}=?" for k in fields if k != "src_relpath")
        vals = [v for k, v in fields.items() if k != "src_relpath"]
        conn.execute(f"UPDATE source_files SET {sets} WHERE id=?", (*vals, sid))
    else:
        fields.setdefault("first_seen", utcnow())
        cols = list(fields.keys())
        q = f"INSERT INTO source_files ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
        sid = int(conn.execute(q, [fields[c] for c in cols]).lastrowid)
    conn.commit()
    return sid


def set_decision(conn: sqlite3.Connection, doc_id: int, **fields) -> None:
    fields.setdefault("reviewed_at", utcnow())
    cols = list(fields.keys())
    placeholders = ",".join("?" * len(cols))
    assignments = ",".join(f"{c}=excluded.{c}" for c in cols)
    conn.execute(
        f"""INSERT INTO decisions (doc_id,{','.join(cols)}) VALUES (?,{placeholders})
            ON CONFLICT(doc_id) DO UPDATE SET {assignments}""",
        [doc_id, *fields.values()],
    )
    conn.commit()
