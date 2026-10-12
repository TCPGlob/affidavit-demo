"""Collections: user-named bundles prepared for Zibbit.

A collection is whatever the user says it is. There is no fixed taxonomy and no
legal classification: someone ticks documents, names the bundle, and exports.

**Zibbit is fed PDFs.** That is the contract, so the numbered PDFs in `PDFs/`
are the primary output -- they are what goes into Zibbit. The Word document is a
convenience index for the person doing the work, not something Zibbit consumes.

The export produces:

    output/collections/<Name>/
        PDFs/                        <- THE ZIBBIT INPUT
            001 - First document.pdf
            002 - Second document.pdf
            ...
        index.csv                    contents list, machine-readable
        manifest.json                same, for any later tooling
        00 - <Name> - Index.docx     cover sheet for humans

Only the documents the user selected are converted. Anything that could not be
converted properly is reported and kept out of the numbered sequence, because a
placeholder sitting in a bundle is worse than a visible gap.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
from collections import Counter
from pathlib import Path

from . import db
from .config import Config
from .convert import convert_to_pdf, detect_toolchain

ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_component(name: str, fallback: str = "document") -> str:
    cleaned = ILLEGAL.sub("-", (name or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned[:110] or fallback


def _stem_for(doc: dict, index: int) -> str:
    """The file name (without extension) a document gets inside the bundle.

    Preference order matters. A per-collection display name wins, because the
    user set it deliberately for this bundle. Next is the title derived from the
    original file name, which is nearly always meaningful. The canonical source
    path is the last resort -- by then it has usually been renamed to a hash.
    """
    label = (doc.get("display_name") or "").strip()
    if not label:
        # Called both with a database row ("title_guess") and with an export
        # entry ("title"); accept either.
        label = (doc.get("title_guess") or doc.get("title") or "").strip()
    if not label:
        raw = Path(doc.get("canonical_src") or "document").stem
        label = re.sub(r"[_]+", " ", raw).strip()
    # A leading numeric prefix in the source name would fight our ordering.
    label = re.sub(r"^\d+\s*[-.)]?\s*", "", label)
    return f"{index:03d} - {safe_component(label)}"


def _auto_tag(conn, doc: dict) -> None:
    """Write pipeline-derived tags, never clobbering user tags."""
    tags = {
        "type": doc.get("doc_type") or "",
        "date": doc.get("doc_date") or "",
        "pages": str(doc.get("page_count") or ""),
    }
    if doc.get("needs_ocr"):
        tags["needs_ocr"] = "yes"
    if doc.get("pdf_status") not in ("ok", "passthrough"):
        tags["conversion"] = doc.get("pdf_status") or "unknown"
    db.set_tags(conn, doc["id"], {k: v for k, v in tags.items() if v}, source="auto")


def build_manifest(conn, cfg: Config, collection: dict, items: list[dict]) -> list[dict]:
    """Resolve every item to its final file name, converting if necessary.

    Returns the ordered list of entries with their export state. Documents that
    fail to convert are returned with `exported=False` and a reason, so the
    caller can report them rather than silently shipping a gap.
    """
    tools = {t.name: t for t in detect_toolchain()}
    entries: list[dict] = []

    for i, doc in enumerate(items, start=1):
        _auto_tag(conn, doc)
        stem = _stem_for(doc, i)
        entry = {
            "position": i,
            "doc_id": doc["id"],
            "display_name": doc.get("display_name") or "",
            "title": doc.get("title_guess") or "",
            "type": doc.get("doc_type") or "",
            "date": doc.get("doc_date") or "",
            "pages": doc.get("page_count"),
            "note": doc.get("note") or "",
            "source_file": doc.get("canonical_src") or "",
            "file_name": f"{stem}.pdf",
            "exported": False,
            "reason": "",
        }

        pdf = doc.get("pdf_path")
        if not pdf or not Path(pdf).exists():
            src = cfg.source_dir / (doc.get("canonical_src") or "")
            if not src.exists():
                entry["reason"] = "source file is missing from the intake folder"
                entries.append(entry)
                continue
            dest = cfg.work_dir / "collection-pdfs" / f"{doc['sha256'][:8]}.pdf"
            dest.parent.mkdir(parents=True, exist_ok=True)
            res = convert_to_pdf(src, dest, tools)
            if res.status not in ("ok", "passthrough") or not res.pdf_path:
                entry["reason"] = f"could not convert ({res.status}): {res.detail[:120]}"
                entries.append(entry)
                continue
            pdf = str(res.pdf_path)
            conn.execute(
                "UPDATE documents SET pdf_path=?, pdf_status=?, status_detail=? WHERE id=?",
                (pdf, res.status, res.detail[:400], doc["id"]),
            )
            conn.commit()
            if res.page_count:
                entry["pages"] = res.page_count

        if doc.get("needs_ocr"):
            # Still exported: the original scan is the evidence. Flagged, not dropped.
            entry["reason"] = "image-only scan - no readable text (OCR still required)"

        entry["exported"] = True
        entry["source_pdf"] = pdf
        entries.append(entry)

    return entries


def export_collection(conn, cfg: Config, collection_id: int,
                      username: str = "") -> dict:
    """Convert the selected documents and write the Zibbit-ready bundle."""
    cfg.ensure_dirs()
    collection = db.get_collection(conn, collection_id)
    if collection is None:
        raise db.CollectionError("That collection no longer exists.")

    items = db.collection_items(conn, collection_id)
    if not items:
        raise db.CollectionError("This collection has no documents in it yet.")

    # Refuse to export anything still being prepared.
    #
    # The folder watcher processes documents in the background, so a person can
    # tick something seconds after dropping it and export before the conversion
    # and metadata reading have finished. Doing that produced files named
    # "document.pdf" with no date, which is worse than making them wait a moment.
    not_ready = [
        i for i in items
        if not i.get("pdf_path") or i.get("profiled_at") is None
    ]
    if not_ready:
        names = ", ".join(
            (Path(i["canonical_src"]).name or "a document")[:40] for i in not_ready[:3]
        )
        more = f" and {len(not_ready) - 3} more" if len(not_ready) > 3 else ""
        raise db.CollectionError(
            f"{len(not_ready)} document(s) in this collection are still being "
            f"prepared: {names}{more}. Wait a few seconds and export again."
        )

    entries = build_manifest(conn, cfg, collection, items)

    name = collection["name"]
    # Drafts stay in collections/; exporting moves the bundle to collections/
    # finished/ and takes it out of the console. If it was finalised before and
    # is being re-exported, rebuild it in place there.
    if collection.get("status") == "finalised" and collection.get("export_path"):
        bundle = Path(collection["export_path"])
    else:
        bundle = cfg.finished_dir / name
    if bundle.exists():
        shutil.rmtree(bundle)
    pdf_dir = bundle / "PDFs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    exported: list[dict] = []
    skipped: list[dict] = []

    # Only successfully converted documents take a number, so numbering is
    # gapless and Zibbit never sees a placeholder.
    for entry in entries:
        if not entry["exported"]:
            skipped.append(entry)
            continue
        seq = len(exported) + 1
        stem = _stem_for(entry, seq)
        entry["position"] = seq
        entry["file_name"] = f"{stem}.pdf"
        dest = pdf_dir / entry["file_name"]
        try:
            shutil.copy2(entry["source_pdf"], dest)
            entry["bytes"] = dest.stat().st_size
            exported.append(entry)
        except OSError as exc:
            entry["exported"] = False
            entry["reason"] = f"could not write file: {exc}"
            skipped.append(entry)

    write_index_csv(bundle / "index.csv", collection, exported, skipped)
    write_manifest(bundle / "manifest.json", collection, exported, skipped, username)
    write_cover_docx(bundle / f"00 - {safe_component(name)} - Index.docx",
                     collection, exported, skipped)

    # The COMPLETE marker is written LAST, and carries a hash of everything
    # else. Any tool consuming a bundle (a Zibbit importer, a backup script)
    # should wait for this file: its absence means the bundle is half-written.
    digest, file_count = bundle_digest(bundle)
    marker = {
        "collection": name,
        "exported_by": username,
        "exported_at": db.utcnow(),
        "documents": len(exported),
        "pages": sum(int(e.get("pages") or 0) for e in exported),
        "files_hashed": file_count,
        "bundle_hash": digest,
        "not_included": len(skipped),
    }
    (bundle / "COMPLETE").write_text(json.dumps(marker, indent=2), encoding="utf-8")

    db.finalise_collection(conn, collection_id, str(bundle), digest, username)

    return {
        "collection": collection,
        "bundle": str(bundle),
        "exported": exported,
        "skipped": skipped,
        "pages": sum(int(e.get("pages") or 0) for e in exported),
        "ocr_flagged": [e for e in exported if "OCR" in (e.get("reason") or "")],
        "bundle_hash": digest,
        "finalised": True,
    }


def bundle_digest(directory: Path) -> tuple[str, int]:
    """A stable hash of a bundle's contents.

    The COMPLETE marker is excluded, obviously, since it will contain this
    value. Documents are hashed by content, so re-exporting an unchanged bundle
    produces the same digest and a changed one does not.
    """
    import hashlib

    entries: list[str] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name == "COMPLETE":
            continue
        h = hashlib.sha256()
        with path.open("rb") as fh:
            while block := fh.read(1 << 20):
                h.update(block)
        entries.append(f"{path.relative_to(directory).as_posix()}:{h.hexdigest()}")
    return hashlib.sha256("\n".join(entries).encode()).hexdigest(), len(entries)


# ---------------------------------------------------------------- index files

def write_index_csv(path: Path, collection: dict, exported: list[dict],
                    skipped: list[dict]) -> None:
    headers = ["No.", "File Name", "Document", "Type", "Date", "Pages", "Note"]
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        for e in exported:
            w.writerow([e["position"], e["file_name"],
                        e["display_name"] or e["title"], e["type"], e["date"],
                        e["pages"] or "", e["reason"] or e["note"]])
        if skipped:
            w.writerow([])
            w.writerow(["NOT INCLUDED"])
            w.writerow(["", "Source file", "Document", "", "", "", "Reason"])
            for e in skipped:
                w.writerow(["", e["source_file"], e["title"], "", "", "",
                            e["reason"]])


def write_manifest(path: Path, collection: dict, exported: list[dict],
                   skipped: list[dict], username: str) -> None:
    payload = {
        "collection": {
            "name": collection["name"],
            "description": collection.get("description") or "",
            "created_by": collection.get("created_by"),
            "exported_by": username,
            "exported_at": db.utcnow(),
        },
        "totals": {
            "documents": len(exported),
            "pages": sum(int(e.get("pages") or 0) for e in exported),
            "not_included": len(skipped),
        },
        "documents": [
            {k: e.get(k) for k in
             ("position", "file_name", "display_name", "title", "type", "date",
              "pages", "bytes", "source_file", "reason")}
            for e in exported
        ],
        "not_included": [
            {k: e.get(k) for k in ("title", "type", "source_file", "reason")}
            for e in skipped
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- cover doc

def write_cover_docx(path: Path, collection: dict, exported: list[dict],
                     skipped: list[dict]) -> None:
    """A cover sheet and ordered contents list, for the person doing the work.

    Zibbit consumes the PDFs, not this document. This exists so a human can see
    at a glance what the bundle contains, in what order, and what was left out.
    """
    from . import docxwriter as dw

    b: list[str] = []
    name = collection["name"]

    b.append(dw.heading(name, size_half_pt=32))
    if collection.get("description"):
        b.append(dw.para(collection["description"], italic=True, size_half_pt=20,
                         color="666666", space_after=160))

    b.append(dw.para(
        f"{len(exported)} document(s), {sum(int(e.get('pages') or 0) for e in exported)} "
        f"page(s) in total.",
        size_half_pt=20, space_after=80))
    b.append(dw.para(
        f"Prepared by {collection.get('created_by') or 'unknown'} "
        f"on {str(collection.get('created_at') or '')[:10]}.",
        size_half_pt=19, color="666666", space_after=240))

    b.append(dw.para(
        "The PDFs are numbered and filed in the PDFs folder beside this document. "
        "That folder is what is imported into Zibbit; this sheet is for reference.",
        size_half_pt=20, space_after=240))

    b.append(dw.heading("Contents", size_half_pt=24))

    rows = []
    for e in exported:
        desc = e["display_name"] or e["title"] or ""
        if e["note"]:
            desc = f"{desc} - {e['note']}" if desc else e["note"]
        rows.append([
            str(e["position"]),
            e["file_name"],
            desc,
            e["date"] or "--",
            str(e["pages"] or ""),
        ])
    if rows:
        b.append(dw.table(["No.", "File", "Document", "Date", "Pages"], rows,
                          [6, 30, 44, 12, 8]))

    if skipped:
        b.append(dw.page_break())
        b.append(dw.heading("Not included", size_half_pt=22))
        b.append(dw.para(
            "These documents were ticked for this bundle but could not be included. "
            "They are listed here so the omission is deliberate and visible rather "
            "than silently missing.",
            italic=True, size_half_pt=19, color="666666", space_after=160))
        b.append(dw.table(
            ["Document", "Source file", "Reason"],
            [[e["title"] or "", e["source_file"], e["reason"] or ""] for e in skipped],
            [26, 30, 44]))

    dw.write_docx(path, "".join(b), title=f"{name} - Document Index",
                  author="Document preparation pipeline")


def collection_summary(entries: list[dict]) -> dict:
    counts = Counter()
    for e in entries:
        counts["documents"] += 1
        counts["pages"] += int(e.get("pages") or 0)
        if "OCR" in (e.get("reason") or ""):
            counts["needs_ocr"] += 1
    return dict(counts)
