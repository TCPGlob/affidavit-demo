"""Drive a full end-to-end test: review decisions -> assemble -> verify output.

Run as:  python e2e_test.py
It exercises the same code paths the CLI uses, but asserts on the results.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from affidavit import assemble, db, reconcile  # noqa: E402
from affidavit.config import load_config  # noqa: E402

ROOT = Path(__file__).resolve().parent

# doc_id -> (schedule, ground, description) - these stand in for lawyer calls
DECISIONS = {
    1: ("A", "", "Statement of Claim issued 20 June 2024"),
    7: ("A", "", "Storage and logistics services agreement dated 15 January 2023"),
    8: ("A", "", "Engagement letter of Ashford & Bell LLP"),
    12: ("A", "", "Invoice NG-4471 dated 31 March 2024"),
    13: ("A", "", "Receipt HV-2291 for storage charges"),
    9: ("A", "", "Contact list maintained by the plaintiff"),
    5: ("A", "", "Records retention policy NR-04"),
    10: ("A", "", "Email correspondence regarding overdue invoices"),
    2: ("A", "", "Draft remediation plan circulated internally"),
    3: ("B", "Solicitor-client privilege",
        "File note of witness interview prepared in contemplation of litigation"),
    4: ("B", "Solicitor-client privilege",
        "Memorandum to file containing legal advice on settlement posture"),
    11: ("A", "", "Demand letter to the defendant dated 14 May 2024"),
    14: ("C", "Not a producible document",
         "Image-only scan; original no longer in the plaintiff's possession"),
    6: ("excluded", "", "Placeholder only - converter unavailable, not the real document"),
}


def main() -> int:
    cfg = load_config(ROOT)
    conn = db.connect(cfg.db_path)
    failures: list[str] = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
        if not cond:
            failures.append(label)

    # ---- start from a clean review state ---------------------------------
    # Decisions persist in the database, so a previous run (or a manual click
    # in the console) would otherwise leak into this one. Documents themselves
    # are left alone; only the review decisions are cleared.
    conn.execute("DELETE FROM decisions")
    conn.commit()

    expected_total = len(DECISIONS)
    actual_total = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
    if actual_total != expected_total:
        print(f"\nThis test expects {expected_total} documents but the database has "
              f"{actual_total}.")
        print("Run:  python pipeline.py demo && python pipeline.py run --fresh")
        conn.close()
        return 1

    # ---- apply decisions -------------------------------------------------
    ids = {r["id"] for r in conn.execute("SELECT id FROM documents")}
    missing = set(DECISIONS) - ids
    check("all decision target documents exist", not missing, f"missing={sorted(missing)}")

    for doc_id, (sched, ground, desc) in DECISIONS.items():
        if doc_id in ids:
            db.set_decision(
                conn, doc_id, schedule=sched, privilege_ground=ground,
                description=desc, reviewed_by="e2e-test",
            )

    unreviewed = conn.execute(
        "SELECT COUNT(*) c FROM documents d LEFT JOIN decisions dec ON dec.doc_id=d.id "
        "WHERE dec.schedule IS NULL"
    ).fetchone()["c"]
    check("every document has a schedule", unreviewed == 0, f"unreviewed={unreviewed}")

    # ---- assemble --------------------------------------------------------
    result = assemble.assemble(conn, cfg, stamp=False)
    counts = result["counts"]
    check("Schedule A populated", counts["A"] > 0, f"A={counts['A']}")
    check("Schedule B populated", counts["B"] == 2, f"B={counts['B']}")
    check("Schedule C populated", counts["C"] == 1, f"C={counts['C']}")
    check("nothing left unclassified", counts["unclassified"] == 0,
          f"unclassified={counts['unclassified']}")

    # ---- package layout --------------------------------------------------
    sched_a = cfg.package_dir / "Schedule A - Documents to be Produced"
    sched_b = cfg.package_dir / "Schedule B - Documents Objected to (Privilege Claimed)"
    sched_c = cfg.package_dir / "Schedule C - Documents No Longer in Possession"
    for name, folder, expected in (("A", sched_a, counts["A"]), ("B", sched_b, counts["B"]),
                                   ("C", sched_c, counts["C"])):
        pdfs = sorted(folder.glob("*.pdf")) if folder.exists() else []
        check(f"Schedule {name} folder holds {expected} pdf(s)", len(pdfs) == expected,
              f"found={len(pdfs)}")
        numbered = all(f.name[:3].isdigit() for f in pdfs)
        check(f"Schedule {name} files are sequentially numbered", numbered)

    # Every packaged file must be a readable, non-empty PDF.
    import pymupdf

    bad: list[str] = []
    for folder in (sched_a, sched_b, sched_c):
        if not folder.exists():
            continue
        for pdf in folder.glob("*.pdf"):
            try:
                with pymupdf.open(str(pdf)) as doc:
                    if doc.page_count < 1:
                        bad.append(pdf.name)
            except Exception as exc:  # noqa: BLE001
                bad.append(f"{pdf.name}: {exc}")
    check("all packaged PDFs open and have pages", not bad, f"bad={bad[:3]}")

    # ---- index -----------------------------------------------------------
    csv_path = cfg.schedules_dir / "index.csv"
    check("index.csv written", csv_path.exists())
    rows: list[dict] = []
    if csv_path.exists():
        with csv_path.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        check("index rows match scheduled documents",
              len(rows) == counts["A"] + counts["B"] + counts["C"],
              f"rows={len(rows)}")
        check("index carries exhibit numbers", all(r["Exhibit"] for r in rows))
        check("index records the reviewer", all(r["Reviewed By"] == "e2e-test" for r in rows))
        exposed = [r for r in rows if r["Schedule"] == "B" and not r["Privilege Ground / Note"]]
        check("Schedule B rows state a privilege ground", not exposed,
              f"missing_ground={len(exposed)}")
        excluded = [r for r in rows if r["Schedule"] == "excluded"]
        check("excluded documents stay out of the affidavit index", not excluded)

    check("index.markdown written", (cfg.schedules_dir / "index.md").exists())

    # Word is the team's working format, so this is the primary deliverable.
    docx_path = cfg.schedules_dir / "index.docx"
    check("index.docx written", docx_path.exists())
    if docx_path.exists():
        from affidavit.docxwriter import read_docx_text

        try:
            dx = read_docx_text(docx_path)
        except Exception as exc:  # noqa: BLE001
            dx = ""
            check("index.docx is a readable OOXML package", False, str(exc))
        if dx:
            check("index.docx is a readable OOXML package", True)
            check("word doc names all three schedules",
                  all(f"SCHEDULE {s}" in dx for s in ("A", "B", "C")))
            check("word doc states Schedule B grounds",
                  "Grounds of objection" in dx and "Solicitor-client privilege" in dx)
            check("word doc omits excluded documents from the schedules",
                  "Placeholder only" not in dx.split("APPENDIX")[0])
            check("word doc records exclusions in an appendix",
                  "APPENDIX" in dx and "Placeholder only" in dx)

    # XLSX is optional: it needs openpyxl. When present it must be a real file.
    import importlib.util

    if importlib.util.find_spec("openpyxl"):
        check("index.xlsx written (openpyxl present)",
              (cfg.schedules_dir / "index.xlsx").exists())
    else:
        print("[SKIP] index.xlsx - openpyxl not installed; CSV and Markdown are authoritative")
    check("package README written", (cfg.output_dir / "PACKAGE-README.md").exists())

    # Placeholder must not be smuggled into a schedule.
    placeholder_in_package = []
    for folder in (sched_a, sched_b, sched_c):
        if not folder.exists():
            continue
        for pdf in folder.glob("*.pdf"):
            with pymupdf.open(str(pdf)) as doc:
                text = doc[0].get_text()
            if "PLACEHOLDER - NOT THE ORIGINAL DOCUMENT" in text:
                placeholder_in_package.append(pdf.name)
    check("no placeholder documents were scheduled",
          not placeholder_in_package, f"found={placeholder_in_package}")

    # ---- reconcile -------------------------------------------------------
    summary = reconcile.reconcile(conn, cfg)
    check("reconciliation counted every source file", summary["source_files"] == 17,
          f"source_files={summary['source_files']}")
    check("reconciliation found no unclassified documents",
          not any("UNCLASSIFIED" in p for p in summary["problems"]))
    check("reconciliation report written",
          (cfg.reports_dir / "reconciliation.md").exists())
    check("traceability csv written", (cfg.reports_dir / "traceability.csv").exists())
    check("unsupported files are still reported",
          any("UNSUPPORTED" in p for p in summary["problems"]),
          "archive.zip and empty-file.pdf should be flagged")

    conn.close()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL END-TO-END CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
