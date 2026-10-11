"""Reconciliation: prove that nothing was silently lost.

This is the safety net that matters most for a sworn document. Every file that
entered the intake folder must be traceable to either a schedule in the package
or an explicit, named exclusion. Anything else is an error.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from .config import Config

BANNER = "=" * 66


def reconcile(conn, cfg: Config) -> dict:
    cfg.reports_dir.mkdir(parents=True, exist_ok=True)

    rows = conn.execute(
        """
        SELECT s.id, s.src_relpath, s.src_name, s.ext, s.size_bytes, s.sha256,
               s.role, s.note, s.doc_id,
               d.canonical_src, d.pdf_status, d.status_detail, d.page_count,
               d.pdf_path, d.needs_ocr, d.privilege_flags,
               dec.schedule
        FROM source_files s
        LEFT JOIN documents d   ON d.id = s.doc_id
        LEFT JOIN decisions dec ON dec.doc_id = s.doc_id
        ORDER BY s.src_relpath
        """
    ).fetchall()

    problems: list[str] = []
    counts: Counter = Counter()
    trace: list[dict] = []

    for r in rows:
        role = r["role"]
        counts[f"role:{role}"] += 1

        if role == "canonical" and r["doc_id"] is not None:
            status = r["pdf_status"] or "pending"
            counts[f"convert:{status}"] += 1
            destination = _destination(r["schedule"], r["canonical_src"])
            if status not in ("ok", "passthrough"):
                problems.append(
                    f"[CONVERSION] {r['src_relpath']}: {status} - {r['status_detail'] or 'no detail'}"
                )
            if r["schedule"] in (None, ""):
                problems.append(
                    f"[UNCLASSIFIED] {r['src_relpath']}: no schedule assigned - blocks filing"
                )
        elif role == "duplicate":
            status = r["pdf_status"] or "pending"
            counts[f"convert:{status}"] += 1
            destination = "(collapsed into canonical copy)"
        elif role == "unsupported":
            status = "n/a"
            destination = "(excluded - unsupported)"
            problems.append(f"[UNSUPPORTED] {r['src_relpath']}: {r['note'] or 'unsupported format'}")
        else:
            status = r["pdf_status"] or "n/a"
            destination = "(not linked to a document)"
            problems.append(f"[ORPHAN] {r['src_relpath']}: role={role} with no document row")

        trace.append(
            {
                "source_file": r["src_relpath"],
                "bytes": r["size_bytes"],
                "sha256": (r["sha256"] or "")[:16],
                "role": role,
                "conversion": status,
                "document_id": r["doc_id"] if r["doc_id"] is not None else "",
                "schedule": r["schedule"] or "",
                "pages": r["page_count"] if r["page_count"] is not None else "",
                "destination": destination,
                "note": r["status_detail"] or r["note"] or "",
            }
        )

    # ---- integrity assertions -------------------------------------------
    total_sources = len(rows)
    accounted = sum(v for k, v in counts.items() if k.startswith("role:"))
    if accounted != total_sources:
        problems.append(
            f"[INTEGRITY] accounted {accounted} of {total_sources} source files"
        )

    linked = conn.execute(
        "SELECT COUNT(*) c FROM documents WHERE pdf_status IN ('ok','passthrough')"
    ).fetchone()["c"]
    docs_total = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]

    ocr = conn.execute(
        "SELECT COUNT(*) c FROM documents WHERE needs_ocr=1"
    ).fetchone()["c"]

    # OCR outcomes, so a scan that was read is visibly different from one that
    # merely failed to convert.
    ocr_rows = conn.execute(
        """SELECT ocr_status, COUNT(*) c FROM documents
           WHERE ocr_status IS NOT NULL GROUP BY ocr_status"""
    ).fetchall()
    ocr_counts = {r["ocr_status"]: r["c"] for r in ocr_rows}
    ocr_chars = conn.execute(
        "SELECT COALESCE(SUM(ocr_chars),0) c FROM documents"
    ).fetchone()["c"]

    if ocr:
        problems.append(
            f"[OCR] {ocr} scan(s) still unread - run: python pipeline.py ocr"
        )
    for status, count in ocr_counts.items():
        if status == "no_text_found":
            problems.append(
                f"[OCR] {count} scan(s) yielded no readable text "
                "(blank, or poor image quality) - open them and check by eye"
            )
        elif status in ("failed", "unavailable"):
            problems.append(f"[OCR] {count} document(s) failed OCR ({status})")

    placeholders = [
        r["src_relpath"] for r in rows if (r["pdf_status"] or "") == "skipped_no_converter"
    ]
    for p in placeholders:
        problems.append(
            f"[PLACEHOLDER] {p}: converted to a placeholder, not the real document"
        )

    # Verify every normalised PDF referenced actually exists on disk.
    missing_files = []
    for r in conn.execute(
        "SELECT canonical_src, pdf_path FROM documents WHERE pdf_path IS NOT NULL"
    ).fetchall():
        p = r["pdf_path"]
        if p and not Path(p).exists():
            missing_files.append(r["canonical_src"])
    for m in missing_files:
        problems.append(f"[MISSING FILE] {m}: normalised pdf recorded but not found on disk")

    summary = {
        "source_files": total_sources,
        "documents": docs_total,
        "converted_ok": linked,
        "placeholders": len(placeholders),
        "needs_ocr": ocr,
        "ocr_counts": ocr_counts,
        "ocr_chars": ocr_chars,
        "duplicates_collapsed": counts.get("role:duplicate", 0),
        "unsupported": counts.get("role:unsupported", 0),
        "problems": problems,
        "counts": dict(counts),
    }

    _write_markdown(cfg, trace, summary)
    _write_csv(cfg, trace)
    _print_summary(summary)
    return summary


def _destination(schedule: str | None, canonical_src: str | None) -> str:
    if schedule in ("A", "B", "C"):
        return f"output/package/Schedule {schedule}/"
    if schedule == "excluded":
        return "(excluded - not relevant)"
    return "(unclassified)"


def _write_csv(cfg: Config, trace: list[dict]) -> None:
    path = cfg.reports_dir / "traceability.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(trace[0].keys()) if trace else ["source_file"])
        w.writeheader()
        w.writerows(trace)


def _write_markdown(cfg: Config, trace: list[dict], summary: dict) -> None:
    L: list[str] = [
        "# Reconciliation Report",
        "",
        "Every file in the intake folder, traced to its final destination.",
        "A sworn affidavit must account for all relevant documents; this report is",
        "the evidence that none were dropped.",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|---|---|",
        f"| Source files seen | {summary['source_files']} |",
        f"| Unique documents | {summary['documents']} |",
        f"| Converted successfully | {summary['converted_ok']} |",
        f"| Duplicates collapsed | {summary['duplicates_collapsed']} |",
        f"| Placeholders (missing converter) | {summary['placeholders']} |",
        f"| Scans still unread | {summary['needs_ocr']} |",
        f"| Scans read by OCR | {summary.get('ocr_counts', {}).get('ok', 0)} |",
        f"| Scans with no readable text | {summary.get('ocr_counts', {}).get('no_text_found', 0)} |",
        f"| Characters recovered by OCR | {summary.get('ocr_chars', 0):,} |",
        f"| Unsupported formats | {summary['unsupported']} |",
        f"| **Problems requiring attention** | **{len(summary['problems'])}** |",
        "",
    ]

    if summary["problems"]:
        L += ["## Problems", ""]
        for p in summary["problems"]:
            L.append(f"- {p}")
        L.append("")
    else:
        L += ["> No problems detected. Every source file is accounted for.", ""]

    L += [
        "## Traceability",
        "",
        "| Source file | Role | Conversion | Schedule | Destination |",
        "|---|---|---|---|---|",
    ]
    for t in trace:
        L.append(
            f"| `{t['source_file']}` | {t['role']} | {t['conversion']} | "
            f"{t['schedule'] or '-'} | {t['destination']} |"
        )
    L.append("")

    (cfg.reports_dir / "reconciliation.md").write_text("\n".join(L), encoding="utf-8")


def _print_summary(summary: dict) -> None:
    print(BANNER)
    print("  RECONCILIATION")
    print(BANNER)
    print(f"  source files          {summary['source_files']}")
    print(f"  unique documents      {summary['documents']}")
    print(f"  converted ok          {summary['converted_ok']}")
    print(f"  duplicates collapsed  {summary['duplicates_collapsed']}")
    print(f"  placeholders          {summary['placeholders']}")
    print(f"  scans still unread    {summary['needs_ocr']}")
    print(f"  scans read by OCR     {summary.get('ocr_counts', {}).get('ok', 0)}"
          f"  ({summary.get('ocr_chars', 0):,} characters)")
    print(f"  unsupported           {summary['unsupported']}")
    problems = summary["problems"]
    if problems:
        print(f"\n  {len(problems)} problem(s) requiring attention:")
        for p in problems[:20]:
            print(f"    - {p}")
        if len(problems) > 20:
            print(f"    ... and {len(problems) - 20} more (see reports/reconciliation.md)")
    else:
        print("\n  No problems detected. Every source file is accounted for.")
    print()
