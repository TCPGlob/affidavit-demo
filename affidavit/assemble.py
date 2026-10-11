"""Assemble the deliverable package from reviewed decisions.

Produces:
  output/package/Schedule A/...   producible documents, sequentially numbered
  output/package/Schedule B/...   documents objected to, with the ground
  output/package/Schedule C/...   documents no longer in possession
  output/package/Unclassified/    anything not yet reviewed (blocks final delivery)
  output/schedules/               index as CSV, XLSX and Markdown
"""

from __future__ import annotations

import csv
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from . import db
from .config import Config

SCHEDULE_TITLES = {
    "A": "Schedule A - Documents to be Produced",
    "B": "Schedule B - Documents Objected to (Privilege Claimed)",
    "C": "Schedule C - Documents No Longer in Possession",
}


def unique_path(directory: Path, name: str) -> Path:
    """Avoid clobbering if two documents resolve to the same file name."""
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    n = 2
    while True:
        candidate = directory / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def safe_dirname(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*]+', "-", s).strip().rstrip(".")
    return s or "untitled"


def fetch_reviewed(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT d.*, dec.schedule, dec.privilege_ground, dec.description,
               dec.reviewed_by, dec.reviewed_at,
               (SELECT COUNT(*) FROM source_files s WHERE s.doc_id = d.id) AS source_copies,
               (SELECT GROUP_CONCAT(s.src_relpath, ' | ')
                  FROM source_files s WHERE s.doc_id = d.id) AS source_paths
        FROM documents d
        LEFT JOIN decisions dec ON dec.doc_id = d.id
        ORDER BY (d.doc_date IS NULL), d.doc_date, d.id
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _index_row(doc: dict, seq: int, cfg: Config) -> dict:
    schedule = doc.get("schedule") or ""
    if cfg.bates_numbering and schedule in ("A", "B", "C"):
        exhibit = f"{cfg.bates_prefix}-{seq:06d}"
    else:
        exhibit = str(seq)
    return {
        "exhibit": exhibit,
        "schedule": schedule,
        "filename": doc.get("package_name", ""),
        "title": doc.get("title_guess") or "",
        "description": doc.get("description") or doc.get("summary") or "",
        "doc_type": doc.get("doc_type") or "",
        "doc_date": doc.get("doc_date") or "",
        "pages": doc.get("page_count") if doc.get("page_count") is not None else "",
        "privilege_ground": doc.get("privilege_ground") or "",
        "source_file": doc.get("canonical_src") or "",
        "copies_collapsed": doc.get("source_copies") or 1,
        "original_paths": doc.get("source_paths") or "",
        "reviewed_by": doc.get("reviewed_by") or "",
        "reviewed_at": doc.get("reviewed_at") or "",
    }


def assemble(conn, cfg: Config, stamp: bool = False) -> dict:
    cfg.ensure_dirs()
    docs = fetch_reviewed(conn)

    # Clean previous package so re-runs are idempotent.
    if cfg.package_dir.exists():
        shutil.rmtree(cfg.package_dir)
    cfg.package_dir.mkdir(parents=True, exist_ok=True)

    buckets: dict[str, list[dict]] = defaultdict(list)
    for d in docs:
        sched = (d.get("schedule") or "").strip()
        buckets[sched if sched in ("A", "B", "C", "excluded") else "unclassified"].append(d)

    counts = {}
    index_rows: list[dict] = []

    for sched in ("A", "B", "C"):
        items = buckets.get(sched, [])
        if not items:
            counts[sched] = 0
            continue
        folder = cfg.package_dir / SCHEDULE_TITLES[sched]
        folder.mkdir(parents=True, exist_ok=True)
        for seq, doc in enumerate(items, start=1):
            _place(doc, folder, seq, sched, cfg, stamp)
            index_rows.append(_index_row(doc, seq, cfg))
        counts[sched] = len(items)

    # Unclassified: not part of the affidavit, kept visible as a blocker.
    unclassified = buckets.get("unclassified", [])
    if unclassified:
        folder = cfg.package_dir / "ZZ - UNCLASSIFIED (do not file)"
        folder.mkdir(parents=True, exist_ok=True)
        for doc in unclassified:
            _place(doc, folder, 0, "", cfg, stamp=False)
    counts["unclassified"] = len(unclassified)
    counts["excluded"] = len(buckets.get("excluded", []))

    _write_indexes(conn, cfg, index_rows, docs)
    _write_cover(conn, cfg, counts)

    return {"counts": counts, "index_rows": index_rows, "unclassified": unclassified}


def _place(doc: dict, folder: Path, seq: int, sched: str, cfg: Config, stamp: bool) -> None:
    """Copy (and optionally stamp) one document into its schedule folder."""
    src = doc.get("pdf_path")
    base = Path(doc["canonical_src"]).stem
    base = re.sub(r"[^\w\-. ]+", "-", base)[:70] or "document"
    if sched:
        name = f"{seq:03d} - {base}.pdf"
    else:
        name = f"{base}.pdf"

    dest = unique_path(folder, safe_dirname(name))
    if src and Path(src).exists():
        if stamp and sched:
            stamped = _stamp_pdf(Path(src), doc, sched, seq, cfg)
            if stamped:
                shutil.copy2(stamped, dest)
            else:
                shutil.copy2(src, dest)
        else:
            shutil.copy2(src, dest)
    doc["package_name"] = dest.name
    doc["package_path"] = str(dest)


def _stamp_pdf(src: Path, doc: dict, sched: str, seq: int, cfg: Config) -> Path | None:
    """Overlay a footer identifying the document in the affidavit.

    Off by default: this modifies page appearance and should be a deliberate
    choice confirmed with the supervising lawyer.
    """
    from .compat import HAS_PYMUPDF, PYMUPDF

    if not HAS_PYMUPDF:
        return None
    try:
        out_dir = cfg.work_dir / "stamped"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{doc['sha256'][:8]}-{sched}{seq:03d}.pdf"
        label = (
            f"{cfg.bates_prefix}-{seq:06d}" if cfg.bates_numbering else f"Schedule {sched} - {seq}"
        )
        with PYMUPDF.open(str(src)) as pdf:
            for i, page in enumerate(pdf):
                rect = page.rect
                page.insert_text(
                    (36, rect.height - 22),
                    f"{label}   |   page {i + 1} of {pdf.page_count}",
                    fontsize=8,
                    color=(0.35, 0.35, 0.35),
                )
            pdf.save(str(out))
        return out
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- indexes

INDEX_COLUMNS = [
    ("exhibit", "Exhibit"),
    ("schedule", "Schedule"),
    ("filename", "File Name"),
    ("doc_date", "Date"),
    ("doc_type", "Type"),
    ("description", "Description"),
    ("pages", "Pages"),
    ("privilege_ground", "Privilege Ground / Note"),
    ("source_file", "Source File"),
    ("copies_collapsed", "Copies Collapsed"),
    ("original_paths", "All Original Paths"),
    ("reviewed_by", "Reviewed By"),
    ("reviewed_at", "Reviewed At"),
]


def _write_indexes(
    conn, cfg: Config, index_rows: list[dict], all_docs: list[dict]
) -> dict[str, bool]:
    out = cfg.schedules_dir
    out.mkdir(parents=True, exist_ok=True)

    # CSV - machine-readable, but headed with the same readable labels as the
    # spreadsheet so a lawyer can open it and understand it immediately.
    csv_path = out / "index.csv"
    keys = [k for k, _ in INDEX_COLUMNS]
    labels = [label for _, label in INDEX_COLUMNS]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(labels)
        for row in index_rows:
            w.writerow([row.get(k, "") for k in keys])

    # Markdown - readable in the console / pasted into an email
    md = ["# Affidavit of Documents - Index", ""]
    for sched in ("A", "B", "C"):
        rows = [r for r in index_rows if r["schedule"] == sched]
        if not rows:
            continue
        md.append(f"## {SCHEDULE_TITLES[sched]}")
        md.append("")
        md.append("| # | Date | Type | Description | Pages | Ground |")
        md.append("|---|---|---|---|---|---|")
        for r in rows:
            desc = (r["description"] or "").replace("|", "\\|")[:110]
            md.append(
                f"| {r['exhibit']} | {r['doc_date'] or '-'} | {r['doc_type']} | "
                f"{desc} | {r['pages']} | {r['privilege_ground'] or '-'} |"
            )
        md.append("")
    (out / "index.md").write_text("\n".join(md), encoding="utf-8")

    # XLSX - one sheet per schedule plus excluded, for the lawyers to edit.
    # Requires openpyxl; the CSV and Markdown index remain authoritative.
    xlsx_ok = _write_xlsx(out / "index.xlsx", index_rows, all_docs)
    docx_ok = _write_word(out / "index.docx", index_rows, all_docs, cfg)
    return {"csv": True, "markdown": True, "xlsx": xlsx_ok, "docx": docx_ok}


def _write_word(path: Path, index_rows: list[dict], all_docs: list[dict],
                cfg: Config) -> bool:
    """Produce the index as a Word document the lawyers can edit and swear.

    The team works in Word, so this is the primary human-readable deliverable.
    Written with the standard library so it needs no installed dependency.
    """
    from . import docxwriter as dw

    b: list[str] = []

    # ---- caption ---------------------------------------------------------
    for line in (cfg.court or "").splitlines():
        if line.strip():
            b.append(dw.para(line.strip(), bold=True, size_half_pt=24, align="center",
                             space_after=0))
    b.append(dw.para("", space_after=60))
    if cfg.court_file_no:
        b.append(dw.para(f"Court File No.: {cfg.court_file_no}", align="center",
                         size_half_pt=22, space_after=60))
    if cfg.proceeding_between_plaintiff or cfg.proceeding_between_defendant:
        b.append(dw.para("BETWEEN:", bold=True, align="center", space_after=40))
        b.append(dw.para(cfg.proceeding_between_plaintiff or "", align="center",
                         space_after=20))
        b.append(dw.para("Plaintiff", italic=True, align="center", size_half_pt=20,
                         space_after=40))
        b.append(dw.para("and", align="center", space_after=40))
        b.append(dw.para(cfg.proceeding_between_defendant or "", align="center",
                         space_after=20))
        b.append(dw.para("Defendant", italic=True, align="center", size_half_pt=20,
                         space_after=120))

    b.append(dw.heading("AFFIDAVIT OF DOCUMENTS", size_half_pt=28))
    b.append(dw.para("INDEX OF DOCUMENTS", bold=True, align="center", space_after=200))

    if cfg.deponent_name:
        b.append(dw.para(
            f"Deponent: {cfg.deponent_name}"
            + (f" ({cfg.deponent_role})" if cfg.deponent_role else ""),
            space_after=80))
    b.append(dw.para(f"Rules: {cfg.jurisdiction_rules}", size_half_pt=18,
                     color="666666", space_after=240))

    # ---- schedules -------------------------------------------------------
    headings = {
        "A": "SCHEDULE A - DOCUMENTS TO BE PRODUCED",
        "B": "SCHEDULE B - DOCUMENTS OBJECTED TO ON THE GROUND OF PRIVILEGE",
        "C": "SCHEDULE C - DOCUMENTS NO LONGER IN THE PARTY'S POSSESSION, "
             "CONTROL OR POWER",
    }
    headers = ["No.", "Date", "Document", "Pages"]
    widths = [8, 14, 66, 8]

    for sched in ("A", "B", "C"):
        rows = [r for r in index_rows if r["schedule"] == sched]
        if not rows:
            continue
        if b:
            b.append(dw.page_break())
        b.append(dw.heading(headings[sched], size_half_pt=24))
        b.append(dw.para(
            f"The following {len(rows)} document(s) are listed under this Schedule.",
            italic=True, size_half_pt=19, color="666666", space_after=160))

        table_rows: list[list[str]] = []
        for r in rows:
            desc = r["description"] or r["title"] or "(no description)"
            if r["doc_type"]:
                desc = f"{r['doc_type']}: {desc}"
            table_rows.append([
                str(r["exhibit"]),
                r["doc_date"] or "--",
                desc,
                str(r["pages"]),
            ])
        b.append(dw.table(headers, table_rows, widths))

        # Privilege grounds belong beside Schedule B, and explanations beside C.
        if sched == "B":
            b.append(dw.para("", space_after=60))
            b.append(dw.para("Grounds of objection:", bold=True, space_after=100))
            for r in rows:
                b.append(dw.para(
                    f"{r['exhibit']}. {r['privilege_ground'] or '[GROUND NOT STATED]'}",
                    space_after=80))

    # ---- appendix: not part of the affidavit -----------------------------
    excluded = [d for d in all_docs if d.get("schedule") == "excluded"]
    if excluded:
        b.append(dw.page_break())
        b.append(dw.heading(
            "APPENDIX - DOCUMENTS REVIEWED AND NOT LISTED (NOT PART OF THE AFFIDAVIT)",
            size_half_pt=22))
        b.append(dw.para(
            "Recorded for the audit trail only. These documents are not listed in "
            "any Schedule. The reason for exclusion is stated so the decision is "
            "defensible on a motion for production.",
            italic=True, size_half_pt=19, color="666666", space_after=160))
        rows = []
        for d in excluded:
            rows.append([
                d.get("title_guess") or "",
                d.get("doc_date") or "--",
                d.get("description") or d.get("privilege_ground") or "(no reason recorded)",
                d.get("reviewed_by") or "",
            ])
        b.append(dw.table(["Document", "Date", "Reason not listed", "Reviewed by"],
                          rows, [30, 12, 46, 12]))

    dw.write_docx(path, "".join(b), title="Affidavit of Documents - Index")
    return True


def _write_xlsx(path: Path, index_rows: list[dict], all_docs: list[dict]) -> bool:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError:
        return False

    wb = Workbook()
    wb.remove(wb.active)
    headers = [label for _, label in INDEX_COLUMNS]
    keys = [k for k, _ in INDEX_COLUMNS]
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", start_color="344054")

    def add_sheet(title: str, rows: list[dict]) -> None:
        ws = wb.create_sheet(title[:31])
        ws.append(headers)
        for c in ws[1]:
            c.font = head_font
            c.fill = head_fill
            c.alignment = Alignment(vertical="center")
        for row in rows:
            ws.append([row.get(k, "") for k in keys])
        widths = [8, 9, 34, 12, 14, 52, 7, 28, 30, 10, 12, 12]
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
        ws.freeze_panes = "A2"

    for sched in ("A", "B", "C"):
        rows = [r for r in index_rows if r["schedule"] == sched]
        if rows:
            add_sheet(f"Schedule {sched}", rows)

    excluded = [
        _index_row(d, 0, _NullCfg()) for d in all_docs if d.get("schedule") == "excluded"
    ]
    if excluded:
        add_sheet("Excluded", excluded)

    unreviewed = [_index_row(d, 0, _NullCfg()) for d in all_docs if not d.get("schedule")]
    if unreviewed:
        add_sheet("UNREVIEWED", unreviewed)

    wb.save(path)
    return True


class _NullCfg:
    bates_numbering = False
    bates_prefix = "DOC"


# ---------------------------------------------------------------- cover

def _write_cover(conn, cfg: Config, counts: dict) -> None:
    lines = [
        "# Affidavit of Documents - Assembly Package",
        "",
        f"**Court:** {cfg.court.replace(chr(10), ' / ')}",
        f"**Court File No.:** {cfg.court_file_no or '(not set)'}",
        f"**Between:** {cfg.proceeding_between_plaintiff or '(not set)'} (Plaintiff)"
        f" and {cfg.proceeding_between_defendant or '(not set)'} (Defendant)",
        f"**Deponent:** {cfg.deponent_name or '(not set)'}"
        + (f", {cfg.deponent_role}" if cfg.deponent_role else ""),
        f"**Rules:** {cfg.jurisdiction_rules}",
        "",
        "## Package Contents",
        "",
        "| Schedule | Documents |",
        "|---|---|",
        f"| Schedule A - to be produced | {counts.get('A', 0)} |",
        f"| Schedule B - objected to | {counts.get('B', 0)} |",
        f"| Schedule C - no longer in possession | {counts.get('C', 0)} |",
        f"| Excluded (not relevant) | {counts.get('excluded', 0)} |",
        f"| **Unclassified - BLOCKS FILING** | **{counts.get('unclassified', 0)}** |",
        "",
    ]
    if counts.get("unclassified", 0):
        lines += [
            "> **NOT READY TO FILE.** "
            f"{counts['unclassified']} document(s) have no schedule assigned. "
            "Open the review console and classify every document before serving this affidavit.",
            "",
        ]
    else:
        lines += ["> All documents reviewed. Package is complete.", ""]

    lines += [
        "## Files",
        "",
        "- `output/package/` - documents filed by schedule",
        "- `output/schedules/index.csv` - machine-readable index",
        "- `output/schedules/index.xlsx` - index by schedule, editable",
        "- `output/schedules/index.md` - readable index",
        "- `output/reports/reconciliation.md` - proof every source file was accounted for",
        "",
        "## Review",
        "",
        "Every A/B/C assignment in this package is a human decision recorded with a",
        "reviewer and timestamp. Privilege markers detected in document text are",
        "surfaced as suggestions only and must be confirmed by the supervising lawyer.",
        "",
    ]
    (cfg.output_dir / "PACKAGE-README.md").write_text("\n".join(lines), encoding="utf-8")
