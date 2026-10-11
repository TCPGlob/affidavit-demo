"""Ingest: discover source files, fingerprint them, and group duplicates.

Deduplication is content-based in two passes:

  1. Exact: group by a fingerprint of the *extracted text*, falling back to a
     byte hash when no text can be read. Fingerprinting text rather than bytes
     is deliberate -- the same letter re-saved by Word, or exported to PDF and
     then photocopied as a scan, is the same instrument and should collapse.
     It is also what makes a `foo.pdf` / `foo.docx` pair resolve to one document.

  2. Near: group by text similarity, so documents that differ only by a
     signature block or a cover page are still surfaced for a human to confirm.

The byte hash is always recorded for traceability.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from . import db
from .config import Config
from .convert import SUPPORTED_EXTS

CHUNK = 1024 * 1024

# When the same content arrives in several formats, prefer the richest
# original as the "canonical" copy to convert from.
EXT_PREFERENCE = [
    ".pdf",
    ".docx",
    ".doc",
    ".rtf",
    ".odt",
    ".xlsx",
    ".xls",
    ".ods",
    ".csv",
    ".pptx",
    ".ppt",
    ".odp",
    ".eml",
    ".msg",
    ".txt",
    ".md",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
    ".heic",
]

SKIP_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", "work", "output"}

_WS = re.compile(r"\s+")


@dataclass
class Discovered:
    path: Path
    relpath: str
    name: str
    ext: str
    size: int
    mtime: float
    sha256: str = ""
    text_digest: str = ""
    text: str = ""
    text_ok: bool = False
    note: str = ""
    group_key: str = ""


@dataclass
class IngestResult:
    files_seen: int = 0
    unique_documents: int = 0
    exact_duplicates: int = 0
    near_duplicates: int = 0
    unsupported: int = 0
    duplicate_pairs: list[tuple[str, str, str]] = field(default_factory=list)
    cross_format_pairs: list[tuple[str, str]] = field(default_factory=list)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def discover(source_dir: Path) -> list[Discovered]:
    """Walk the intake folder. Nested folders are expected and preserved."""
    found: list[Discovered] = []
    if not source_dir.exists():
        return found

    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [
            d
            for d in dirs
            if d not in SKIP_DIRS and not d.startswith(".") and not d.startswith("_")
        ]
        for name in files:
            if name.lower() in SKIP_NAMES or name.startswith("~$") or name.startswith("."):
                continue
            p = Path(root) / name
            try:
                st = p.stat()
            except OSError:
                continue
            found.append(
                Discovered(
                    path=p,
                    relpath=str(p.relative_to(source_dir)),
                    name=name,
                    ext=p.suffix.lower(),
                    size=st.st_size,
                    mtime=st.st_mtime,
                )
            )
    return found


def _norm_text(text: str) -> str:
    t = _WS.sub(" ", text.lower()).strip()
    return re.sub(r"[^a-z0-9 ]", "", t)


def _text_digest(text: str) -> str:
    return hashlib.sha256(_norm_text(text).encode("utf-8")).hexdigest()[:32]


def _read_text(path: Path, ext: str) -> tuple[str, bool]:
    """Best-effort text for fingerprinting. Returns (text, ok)."""
    try:
        if ext == ".pdf":
            from .extract import pdf_text

            text, _, err = pdf_text(path, max_pages=40)
            return text, (bool(text.strip()) and not err)
        if ext in {".txt", ".md", ".csv", ".log", ".tsv"}:
            return path.read_text(encoding="utf-8", errors="replace"), True
        if ext in {".docx", ".xlsx", ".pptx"}:
            return _read_ooxml(path), True
        if ext in {".eml"}:
            return path.read_text(encoding="utf-8", errors="replace"), True
    except Exception:  # noqa: BLE001 - fingerprinting must never break ingest
        return "", False
    return "", False


def _read_ooxml(path: Path) -> str:
    """Pull visible text out of a DOCX/XLSX/PPTX package (stdlib zipfile only)."""
    import zipfile

    chunks: list[str] = []
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            targets = [
                n
                for n in names
                if n == "word/document.xml"
                or n.startswith("xl/sharedStrings")
                or n.startswith("xl/worksheets/sheet")
                or n.startswith("ppt/slides/slide")
            ]
            for n in targets[:40]:
                xml = z.read(n).decode("utf-8", "replace")
                chunks.append(re.sub(r"<[^>]+>", " ", xml))
    except (zipfile.BadZipFile, OSError, KeyError):
        return ""
    return _WS.sub(" ", " ".join(chunks))


def _pref_rank(ext: str) -> int:
    try:
        return EXT_PREFERENCE.index(ext)
    except ValueError:
        return len(EXT_PREFERENCE)


def _tokens(text: str) -> set[str]:
    stop = {
        "the", "and", "of", "to", "in", "a", "is", "that", "for", "on", "as",
        "by", "with", "this", "be", "are", "or", "at", "from", "it", "not",
    }
    return {t for t in text.split() if len(t) > 2 and t not in stop}


def _similar(a: str, b: str) -> float:
    """Character-level similarity over a bounded prefix.

    `quick_ratio` is deliberately NOT used: it compares character multisets, so
    two unrelated legal documents that share vocabulary score near 1.0. That
    would silently merge distinct documents, which in an affidavit context is a
    correctness failure, not a cosmetic one.
    """
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a[:8000], b[:8000]).ratio()


def _token_overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def prune_missing(conn, cfg: Config) -> dict:
    """Drop rows whose source file is no longer in the intake folder.

    Without this, re-running the pipeline after files are renamed or removed
    leaves orphaned documents behind: the package would contain documents that
    are no longer in intake, and the index would list them as if they were.

    Deleting a document also deletes its review decision, which is correct --
    a decision about a document that no longer exists is not audit history, it
    is corrupt state. (Every decision is also recorded in the audit log, which
    this does not touch.)
    """
    rows = conn.execute("SELECT id, canonical_src FROM documents").fetchall()
    stale = [r["id"] for r in rows if not (cfg.source_dir / r["canonical_src"]).exists()]
    if not stale:
        return {"documents_removed": 0}

    marks = ",".join("?" * len(stale))
    conn.execute(f"DELETE FROM decisions WHERE doc_id IN ({marks})", stale)
    conn.execute(f"DELETE FROM source_files WHERE doc_id IN ({marks})", stale)
    conn.execute(f"DELETE FROM documents WHERE id IN ({marks})", stale)

    # Source rows for files that have disappeared entirely.
    orphans = [
        r["id"]
        for r in conn.execute("SELECT id, src_relpath FROM source_files").fetchall()
        if not (cfg.source_dir / r["src_relpath"]).exists()
    ]
    if orphans:
        marks = ",".join("?" * len(orphans))
        conn.execute(f"DELETE FROM source_files WHERE id IN ({marks})", orphans)

    conn.commit()
    return {"documents_removed": len(stale), "source_rows_removed": len(orphans)}


def ingest(conn, cfg: Config) -> IngestResult:
    files = discover(cfg.source_dir)
    result = IngestResult(files_seen=len(files))

    usable: list[Discovered] = []
    for d in files:
        if d.size == 0:
            d.note = "zero-byte file"
            result.unsupported += 1
            _record_unsupported(conn, d)
            continue
        if d.ext not in SUPPORTED_EXTS:
            d.note = f"unsupported format {d.ext or '(no extension)'}"
            result.unsupported += 1
            _record_unsupported(conn, d)
            continue
        d.sha256 = sha256_file(d.path)
        d.text, d.text_ok = _read_text(d.path, d.ext)
        if d.text_ok:
            d.text_digest = _text_digest(d.text)
            d.group_key = f"text:{d.text_digest}"
        else:
            d.note = "no extractable text - grouped by file bytes"
            d.group_key = f"bytes:{d.sha256}"
        usable.append(d)

    # ---- pass 1: exact groups -------------------------------------------
    groups: dict[str, list[Discovered]] = {}
    for d in usable:
        groups.setdefault(d.group_key, []).append(d)

    # ---- pass 2: merge near-identical text groups ------------------------
    # Compare each group only against current cluster representatives, using
    # union-find so transitive matches collapse to one root.
    text_groups = sorted(k for k in groups if k.startswith("text:"))
    parent: dict[str, str] = {k: k for k in text_groups}
    reps: dict[str, str] = {}  # root -> normalised representative text

    for key in text_groups:
        sample = _norm_text(groups[key][0].text)
        target = None
        for root, rep_text in reps.items():
            if (
                _similar(sample, rep_text) >= cfg.near_dup_threshold
                and _token_overlap(sample, rep_text) >= cfg.near_dup_min_token_overlap
            ):
                target = root
                break
        if target:
            parent[key] = target
        else:
            reps[key] = sample

    def find(k: str) -> str:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    clusters: dict[str, list[Discovered]] = {}
    for key in text_groups:
        clusters.setdefault(find(key), []).extend(groups[key])
    # byte-keyed groups (no extractable text) can never be near-merged safely
    for key, group in groups.items():
        if not key.startswith("text:"):
            clusters[key] = group
    groups = clusters

    # ---- persist ---------------------------------------------------------
    for key, group in groups.items():
        group.sort(key=lambda d: (_pref_rank(d.ext), len(d.relpath)))
        canonical = group[0]

        doc_id = db.upsert_document(
            conn,
            sha256=canonical.sha256,
            text_fingerprint=canonical.text_digest or None,
            canonical_src=canonical.relpath,
            ext=canonical.ext,
        )
        result.unique_documents += 1

        for d in group:
            is_canon = d.relpath == canonical.relpath
            if not is_canon:
                same_text = bool(d.text_digest) and d.text_digest == canonical.text_digest
                if same_text:
                    why = "identical text content"
                    result.exact_duplicates += 1
                else:
                    why = "near-identical text - confirm it is the same instrument"
                    result.near_duplicates += 1
                result.duplicate_pairs.append((d.relpath, canonical.relpath, why))
                if d.ext != canonical.ext:
                    result.cross_format_pairs.append((d.relpath, canonical.relpath))
            db.record_source(
                conn,
                src_path=str(d.path),
                src_relpath=d.relpath,
                src_name=d.name,
                ext=d.ext,
                size_bytes=d.size,
                mtime=d.mtime,
                sha256=d.sha256,
                doc_id=doc_id,
                role="canonical" if is_canon else "duplicate",
                dup_of_doc_id=None if is_canon else doc_id,
                note="" if is_canon else why,
            )
    return result


def _record_unsupported(conn, d: Discovered) -> None:
    db.record_source(
        conn,
        src_path=str(d.path),
        src_relpath=d.relpath,
        src_name=d.name,
        ext=d.ext,
        size_bytes=d.size,
        mtime=d.mtime,
        sha256=d.sha256 or None,
        doc_id=None,
        role="unsupported",
        note=d.note,
    )
