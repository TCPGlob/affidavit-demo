"""Pipeline orchestrator: ingest -> convert -> extract -> classify suggestions."""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from pathlib import Path

from . import db, extract, ingest as ingest_module
from .config import Config
from .convert import convert_to_pdf, detect_toolchain, pdf_page_count, print_toolchain
from .ingest import ingest

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize(s: str, fallback: str = "document") -> str:
    s = _SAFE.sub("-", (s or "").strip()).strip("-._")
    s = re.sub(r"-{2,}", "-", s)
    return s[:80] or fallback


def build_filename(cfg: Config, doc_row, seq: int = 0) -> str:
    date = doc_row["doc_date"] or "undated"
    doctype = sanitize(doc_row["doc_type"] or "Document").lower()
    h8 = (doc_row["sha256"] or "")[:8]
    try:
        stem = cfg.filename_template.format(
            date=date, doctype=doctype, hash8=h8, seq=f"{seq:04d}"
        )
    except (KeyError, IndexError):
        stem = f"{date}_{doctype}_{h8}"
    return f"{sanitize(stem, 'document')}.pdf"


def parties_from_config(cfg: Config) -> list[str]:
    return [cfg.proceeding_between_plaintiff, cfg.proceeding_between_defendant]


def run(conn, cfg: Config, fresh: bool = False, skip_ingest: bool = False,
        ocr: bool = True, ocr_force: bool = False) -> dict:
    cfg.ensure_dirs()
    db.init(conn)
    tools = {t.name: t for t in detect_toolchain()}

    print("=" * 66)
    print("  AFFIDAVIT OF DOCUMENTS - ASSEMBLY PIPELINE")
    print("=" * 66)
    print(f"  source : {cfg.source_dir}")
    print(f"  work   : {cfg.work_dir}")
    print(f"  output : {cfg.output_dir}")
    print_toolchain(list(tools.values()))

    # ---------------------------------------------------------- 1. ingest
    if not skip_ingest:
        print("Step 1/4  Ingesting, fingerprinting and grouping")
        pruned = ingest_module.prune_missing(conn, cfg)
        if pruned["documents_removed"]:
            print(f"          {pruned['documents_removed']} document(s) removed from state "
                  "(source file no longer in intake)")
        result = ingest(conn, cfg)
        print(f"          {result.files_seen} files seen")
        print(f"          {result.unique_documents} unique documents")
        print(f"          {result.exact_duplicates} exact duplicates collapsed")
        if result.near_duplicates:
            print(f"          {result.near_duplicates} near-duplicates collapsed (verify these)")
        print(f"          {result.unsupported} unsupported / empty")
        if result.duplicate_pairs:
            print("\n          Collapsed into the canonical copy:")
            for rel, canon, why in result.duplicate_pairs[:12]:
                print(f"            {rel}")
                print(f"              -> {canon}   ({why})")
            if len(result.duplicate_pairs) > 12:
                print(f"            ... and {len(result.duplicate_pairs) - 12} more")
        if result.cross_format_pairs:
            print(
                f"\n          {len(result.cross_format_pairs)} duplicate(s) arrived in a "
                "different format than the copy kept"
            )
        print()

    # ---------------------------------------------------------- 2. convert
    print("Step 2/4  Converting to PDF")
    rows = conn.execute(
        "SELECT * FROM documents ORDER BY id"
    ).fetchall()
    conv_stats: Counter = Counter()

    for row in rows:
        src_rel = row["canonical_src"]
        src_path = cfg.source_dir / src_rel
        out_name = build_filename(cfg, row)
        out_path = cfg.normalized_dir / out_name

        if not src_path.exists():
            conv_stats["missing_source"] += 1
            conn.execute(
                "UPDATE documents SET pdf_status=?, status_detail=? WHERE id=?",
                ("failed", f"canonical source missing: {src_rel}", row["id"]),
            )
            conn.commit()
            continue

        res = convert_to_pdf(src_path, out_path, tools)

        final_path = None
        if res.status in ("ok", "passthrough"):
            final_path = Path(res.pdf_path) if res.pdf_path else None
            if final_path and final_path != out_path and final_path.exists():
                shutil.copy2(final_path, out_path)
                final_path = out_path
            elif res.status == "passthrough":
                # Keep a normalised copy so the package is self-contained.
                try:
                    shutil.copy2(src_path, out_path)
                    final_path = out_path
                except OSError:
                    final_path = src_path
        elif res.status == "skipped_no_converter":
            final_path = Path(res.pdf_path) if res.pdf_path else None

        pages = res.page_count
        if pages is None and final_path and final_path.exists():
            pages = pdf_page_count(final_path)

        conv_stats[res.status] += 1
        conn.execute(
            """UPDATE documents
               SET pdf_path=?, pdf_status=?, status_detail=?, page_count=?
               WHERE id=?""",
            (
                str(final_path) if final_path else None,
                res.status,
                res.detail[:400],
                pages,
                row["id"],
            ),
        )
        conn.commit()
        flag = "  !" if res.status not in ("ok", "passthrough") else "   "
        print(f"       {flag} {src_rel[:52]:<52} -> {res.status}")

    print()
    for status in ("ok", "passthrough", "skipped_no_converter", "unsupported", "failed", "missing_source"):
        if conv_stats[status]:
            print(f"          {status:<22} {conv_stats[status]}")
    print()

    # ---------------------------------------------------------- 3. extract
    print("Step 3/4  Extracting text and metadata")
    rows = conn.execute(
        "SELECT * FROM documents WHERE pdf_path IS NOT NULL ORDER BY id"
    ).fetchall()
    parties = parties_from_config(cfg)
    ocr_needed = 0

    for row in rows:
        pdf = Path(row["pdf_path"])
        source_name = Path(row["canonical_src"]).name
        ex = extract.extract(pdf, source_name, parties)

        if ex.needs_ocr:
            ocr_needed += 1

        if row["pdf_status"] == "skipped_no_converter":
            ex.privilege_flags = []

        conn.execute(
            """UPDATE documents SET
                 page_count=?, text_chars=?, has_text_layer=?, needs_ocr=?,
                 title_guess=?, doc_type=?, doc_date=?, date_source=?,
                 privilege_flags=?, party_hits=?, summary=?, text_fingerprint=?,
                 status_detail=CASE WHEN ?<>'' THEN ? ELSE status_detail END
               WHERE id=?""",
            (
                ex.page_count if ex.page_count is not None else row["page_count"],
                len(ex.text),
                1 if ex.has_text_layer else 0,
                1 if ex.needs_ocr else 0,
                ex.title_guess,
                ex.doc_type,
                ex.doc_date,
                ex.date_source,
                json.dumps(ex.privilege_flags),
                json.dumps(ex.party_hits),
                ex.summary,
                ex.text_fingerprint,
                ex.error,
                ex.error,
                row["id"],
            ),
        )
        conn.commit()

    print(f"          {len(rows)} documents profiled")
    if ocr_needed:
        print(f"          {ocr_needed} image-only scan(s) require OCR")
    print()

    # ---------------------------------------------------------- 4. OCR
    ocr_stats = None
    if cfg.ocr_enabled and ocr:
        print("Step 4/4  Reading scanned documents (OCR, local only)")
        ocr_stats = run_ocr_stage(conn, cfg, tools, force=ocr_force)
        print()
    else:
        scans = conn.execute(
            "SELECT COUNT(*) c FROM documents WHERE needs_ocr=1"
        ).fetchone()["c"]
        if scans:
            print(f"          {scans} scan(s) still need OCR. Run: python pipeline.py ocr")
            print()

    _suggest_privilege(conn)
    _report_metrics(conn, cfg)
    return {"tools": {k: v.available for k, v in tools.items()}, "ocr": ocr_stats}


def run_ocr_stage(conn, cfg: Config, tools: dict, force: bool = False) -> dict:
    """OCR every document that has no text layer.

    Only runs on scans; documents that already have text are skipped. The
    searchable copy lands in work/ocr/ and is used for reading and metadata.
    The exported bundle still carries the original scan.
    """
    from . import ocr as ocr_mod

    tool = ocr_mod.find_tesseract()
    if not tool.available:
        print("          Tesseract is not installed - skipping OCR.")
        print("          Install it, then re-run:  python pipeline.py ocr")
        print("          Windows: winget install UB-Mannheim.TesseractOCR")
        return {"available": False, "processed": 0, "succeeded": 0, "empty": 0,
                "failed": 0, "chars": 0}

    lang = ocr_mod.pick_language(tool, cfg.ocr_lang)
    if lang != cfg.ocr_lang:
        print(f"          Language '{cfg.ocr_lang}' not installed; using '{lang}'")
        print(f"          Installed: {', '.join(tool.languages) or 'none reported'}")

    # What counts as "needs reading" differs between the two modes:
    #   normal - documents with no readable text layer that have not been read
    #            successfully already
    #   force  - anything that was ever OCR'd, plus anything still unread
    if force:
        where = (
            "SELECT * FROM documents WHERE pdf_path IS NOT NULL "
            "AND (ocr_status IS NOT NULL OR needs_ocr=1)"
        )
    else:
        where = (
            "SELECT * FROM documents WHERE pdf_path IS NOT NULL AND needs_ocr=1 "
            "AND (ocr_status IS NULL OR ocr_status IN ('failed','no_text_found'))"
        )
    rows = conn.execute(where + " ORDER BY id").fetchall()

    if not rows:
        print("          Nothing to OCR - every document already has a text layer.")
        return {"available": True, "processed": 0, "succeeded": 0, "empty": 0,
                "failed": 0, "chars": 0}

    print(f"          {len(rows)} scanned document(s) to read "
          f"({lang}, {cfg.ocr_dpi} dpi, max {cfg.ocr_max_pages} pages each)")

    stats = {"available": True, "processed": 0, "succeeded": 0, "empty": 0,
             "failed": 0, "chars": 0}
    ocr_dir = cfg.work_dir / "ocr"
    ocr_dir.mkdir(parents=True, exist_ok=True)
    parties = parties_from_config(cfg)

    for row in rows:
        pdf = Path(row["pdf_path"])
        dest = ocr_dir / f"{row['sha256'][:12]}.pdf"
        res = ocr_mod.ocr_pdf(pdf, dest, tool, lang=lang, dpi=cfg.ocr_dpi,
                              max_pages=cfg.ocr_max_pages)
        stats["processed"] += 1

        if res.status == "ok":
            stats["succeeded"] += 1
            stats["chars"] += res.text_chars
        elif res.status == "no_text_found":
            stats["empty"] += 1
        else:
            stats["failed"] += 1

        conn.execute(
            """UPDATE documents SET ocr_status=?, ocr_path=?, ocr_chars=?,
                   ocr_confidence=?, ocr_detail=?, ocr_at=?
               WHERE id=?""",
            (res.status, str(res.pdf_path) if res.pdf_path else None,
             res.text_chars, res.mean_confidence, res.detail[:400],
             db.utcnow(), row["id"]),
        )
        conn.commit()

        mark = {"ok": "read", "no_text_found": "no text", "failed": "FAILED"}.get(res.status, res.status)
        print(f"            [{mark:>8}] {row['canonical_src'][:44]:<46} "
              f"{res.text_chars:>7,} chars"
              + (f"  conf {res.mean_confidence}" if res.mean_confidence else ""))

        # Now that the scan can be read, improve its metadata and clear the
        # "needs OCR" flag.
        #
        # Deliberately NOT gated on extract()'s has_text_layer, which uses a
        # 40-character threshold: a short document (a receipt, a one-line memo)
        # can OCR perfectly and still fall under it, which previously left
        # needs_ocr set forever and re-ran OCR on every pass.
        if res.status == "ok" and res.pdf_path:
            source_name = Path(row["canonical_src"]).name
            ex = extract.extract(res.pdf_path, source_name, parties)
            recovered = len(ex.text) if ex.text.strip() else res.text_chars
            conn.execute(
                """UPDATE documents SET
                     needs_ocr=0, has_text_layer=1, text_chars=?,
                     title_guess=COALESCE(NULLIF(?,''), title_guess),
                     doc_type=COALESCE(NULLIF(?,''), doc_type),
                     doc_date=COALESCE(NULLIF(?,''), doc_date),
                     date_source=COALESCE(NULLIF(?,''), date_source),
                     privilege_flags=?, summary=?, text_fingerprint=?
                   WHERE id=?""",
                (recovered, ex.title_guess, ex.doc_type, ex.doc_date,
                 ex.date_source, json.dumps(ex.privilege_flags), ex.summary,
                 ex.text_fingerprint, row["id"]),
            )
            conn.commit()

    print(f"          read {stats['succeeded']}/{stats['processed']} "
          f"({stats['chars']:,} characters recovered)")
    return stats


def _suggest_privilege(conn) -> None:
    """Pre-fill privilege grounds as a SUGGESTION a human must confirm.

    Schedule placement is deliberately left NULL - the machine never decides.
    """
    rows = conn.execute(
        "SELECT id, privilege_flags FROM documents WHERE privilege_flags IS NOT NULL"
    ).fetchall()
    suggested = 0
    for row in rows:
        try:
            flags = json.loads(row["privilege_flags"] or "[]")
        except json.JSONDecodeError:
            continue
        if not flags:
            continue
        existing = conn.execute(
            "SELECT doc_id FROM decisions WHERE doc_id=?", (row["id"],)
        ).fetchone()
        if existing:
            continue
        conn.execute(
            """INSERT INTO decisions (doc_id, schedule, privilege_ground, notes, reviewed_at)
               VALUES (?, NULL, ?, ?, NULL)
               ON CONFLICT(doc_id) DO NOTHING""",
            (
                row["id"],
                "; ".join(flags),
                "AUTO-SUGGESTED from document text - requires lawyer confirmation",
            ),
        )
        suggested += 1
    conn.commit()
    if suggested:
        print(f"          {suggested} document(s) carry privilege markers (suggested, not decided)")


def _report_metrics(conn, cfg: Config) -> None:
    total = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
    reviewed = conn.execute(
        "SELECT COUNT(*) c FROM decisions WHERE schedule IS NOT NULL"
    ).fetchone()["c"]
    undated = conn.execute(
        "SELECT COUNT(*) c FROM documents WHERE doc_date IS NULL"
    ).fetchone()["c"]
    no_text = conn.execute(
        "SELECT COUNT(*) c FROM documents WHERE has_text_layer=0"
    ).fetchone()["c"]

    print("Summary")
    print("-" * 66)
    print(f"  documents            {total}")
    print(f"  reviewed (A/B/C)     {reviewed}  ({_pct(reviewed, total)})")
    print(f"  awaiting review      {total - reviewed}")
    print(f"  undated              {undated}")
    print(f"  no text layer        {no_text}")
    print()


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f}%" if b else "n/a"
