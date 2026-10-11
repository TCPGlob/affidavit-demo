"""Tests for local OCR.

Tesseract-dependent checks are skipped with a visible notice when the engine is
not installed, so the suite is still meaningful on a machine without it - which
is also how the graceful-degradation path gets exercised.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from affidavit import db, ocr  # noqa: E402
from affidavit.config import load_config  # noqa: E402
from affidavit.extract import parse_date_token, pdf_text  # noqa: E402
from affidavit.fixtures import build_scanned_image  # noqa: E402

ROOT = Path(__file__).resolve().parent


def main() -> int:
    failures: list[str] = []
    skipped: list[str] = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
        if not cond:
            failures.append(label)

    def skip(label: str, why: str) -> None:
        print(f"[SKIP] {label}  ({why})")
        skipped.append(label)

    tool = ocr.find_tesseract()
    print("=" * 68)
    print(f"  {ocr.describe_tool()}")
    print("=" * 68)
    print()

    # ---------------- detection ------------------------------------------
    print("--- engine detection ---")
    if tool.available:
        check("Tesseract is detected", True, tool.path)
        check("a version is reported", bool(tool.version), tool.version)
        check("language data is listed", len(tool.languages) > 0,
              ", ".join(tool.languages[:6]))
        check("'eng' is available", "eng" in tool.languages,
              "needed for English documents")
        check("an uninstalled language falls back to eng",
              ocr.pick_language(tool, "kaz") == "eng")
        check("an installed language is honoured",
              ocr.pick_language(tool, "eng") == "eng")
        check("a multi-language request is filtered to what exists",
              ocr.pick_language(tool, "eng+xyz") == "eng")
    else:
        skip("engine detection", "Tesseract not installed")

    # ---------------- graceful degradation -------------------------------
    print("\n--- graceful degradation ---")
    tmp = ROOT / "work" / "_ocrtest"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    empty_tool = ocr.OcrTool()  # simulates "not installed"
    res = ocr.ocr_pdf(tmp / "missing.pdf", tmp / "out.pdf", empty_tool)
    check("a missing engine reports 'unavailable', not an exception",
          res.status == "unavailable", f"status={res.status}")
    check("the reason is explained", "not installed" in res.detail.lower(),
          res.detail)

    res = ocr.ocr_pdf(tmp / "nope.pdf", tmp / "out.pdf", tool)
    check("a missing input file reports 'failed', not an exception",
          res.status == "failed", f"status={res.status}")

    # ---------------- OCR-tolerant dates ---------------------------------
    # OCR routinely loses a separator; the date must still be recovered, and
    # invalid runs must NOT be turned into dates.
    print("\n--- OCR-tolerant date parsing ---")
    good = {
        "2024-04-12": "2024-04-12",
        "202404-12": "2024-04-12",   # dropped dash
        "20240412": "2024-04-12",    # dropped both
        "12/04/2024": "2024-04-12",
        "30 April 2024": "2024-04-30",
    }
    for token, expected in good.items():
        got = parse_date_token(token)
        check(f"parses {token!r}", got == expected, f"got {got}")

    for token in ("20241350", "12345678", "2291", "00000000"):
        got = parse_date_token(token)
        check(f"refuses {token!r} (not a real date)", got is None, f"got {got}")

    # ---------------- real OCR -------------------------------------------
    print("\n--- OCR of a real scan ---")
    if not tool.available:
        skip("scanning a fixture", "Tesseract not installed")
        skip("searchable output", "Tesseract not installed")
        skip("metadata improvement", "Tesseract not installed")
    else:
        scan = tmp / "invoice.png"
        build_scanned_image(
            scan, "HARBOURVIEW STORAGE LTD.",
            ["TAX INVOICE NG-4502", "Date: 30 April 2024",
             "Client: Northgate Property Holdings Inc.",
             "TOTAL DUE $18,950.00", "Payment terms: Net 30"],
        )
        check("fixture image created", scan.exists())

        out = tmp / "searchable.pdf"
        result = ocr.ocr_pdf(scan if scan.suffix == ".pdf" else _png_to_pdf(scan, tmp),
                             out, tool, dpi=200)
        check("OCR succeeds", result.status == "ok", result.detail)
        check("a searchable PDF was written",
              bool(result.pdf_path) and Path(result.pdf_path).exists())
        check("text was recovered", result.text_chars > 40,
              f"{result.text_chars} chars")
        check("a confidence is reported",
              result.mean_confidence is not None and result.mean_confidence > 50,
              f"{result.mean_confidence}")

        if result.pdf_path:
            text, pages, err = pdf_text(Path(result.pdf_path))
            check("the searchable copy has a text layer",
                  len(text.strip()) > 40, f"{len(text.strip())} chars")
            check("the copy is one page", pages == 1, f"pages={pages}")
            for needle in ("INVOICE", "NG-4502", "18,950"):
                check(f"searchable: {needle!r} is findable",
                      needle.lower() in text.lower())
            check("the recognised date is present",
                  "2024" in text, text.strip()[:70])

        # A blank page must report honestly rather than inventing text.
        from affidavit.fixtures import build_blank_pdf
        blank = tmp / "blank.pdf"
        build_blank_pdf(blank, "blank")
        blank_result = ocr.ocr_pdf(blank, tmp / "blank-ocr.pdf", tool)
        check("a blank page reports 'no_text_found'",
              blank_result.status == "no_text_found", blank_result.status)

    # ---------------- pipeline integration -------------------------------
    print("\n--- pipeline integration ---")
    cfg = load_config(ROOT)
    cfg.db_path = tmp / "ocr.sqlite3"
    conn = db.connect(cfg.db_path)
    db.init(conn)

    from affidavit.pipeline import run_ocr_stage

    if tool.available:
        import pymupdf

        img_pdf = tmp / "scan.pdf"
        png = tmp / "scan-src.png"
        build_scanned_image(png, "INVOICE", ["Date: 30 April 2024", "TOTAL $18,950.00"])
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_image(page.rect, filename=str(png))
        doc.save(str(img_pdf))
        doc.close()

        doc_id = db.upsert_document(
            conn, sha256="ocrscan1", canonical_src="scan.pdf", ext=".pdf",
            pdf_path=str(img_pdf), pdf_status="ok", needs_ocr=1,
            has_text_layer=0, title_guess="scan", doc_type="Document",
        )
        conn.commit()

        cfg.work_dir = tmp
        (tmp / "ocr").mkdir(exist_ok=True)
        stats = run_ocr_stage(conn, cfg, {}, force=False)
        check("the stage reports the engine available", stats["available"] is True)
        check("the scan was processed", stats["processed"] == 1, str(stats))
        check("the scan was read", stats["succeeded"] == 1, str(stats))

        row = conn.execute(
            "SELECT needs_ocr, has_text_layer, ocr_status, ocr_path, ocr_chars, "
            "ocr_confidence, doc_date FROM documents WHERE id=?", (doc_id,)
        ).fetchone()
        check("needs_ocr is cleared once read", row["needs_ocr"] == 0)
        check("has_text_layer is now true", row["has_text_layer"] == 1)
        check("the searchable copy is recorded",
              bool(row["ocr_path"]) and Path(row["ocr_path"]).exists())
        check("characters are recorded", (row["ocr_chars"] or 0) > 20,
              str(row["ocr_chars"]))
        check("a confidence is recorded",
              row["ocr_confidence"] is not None, str(row["ocr_confidence"]))
        check("the date was recovered from the scan",
              row["doc_date"] == "2024-04-30", str(row["doc_date"]))

        # Re-running must not redo work that succeeded.
        again = run_ocr_stage(conn, cfg, {}, force=False)
        check("a second run skips documents already read",
              again["processed"] == 0, str(again))

        forced = run_ocr_stage(conn, cfg, {}, force=True)
        check("--force re-reads them", forced["processed"] == 1, str(forced))

        # The exported PDF must still be the original scan, not the OCR copy.
        check("the original scan is untouched (OCR never rewrites the exhibit)",
              Path(row["ocr_path"]) != Path(str(img_pdf)))
    else:
        skip("pipeline integration", "Tesseract not installed")
        stats = run_ocr_stage(conn, cfg, {}, force=False)
        check("without the engine the stage reports unavailable",
              stats["available"] is False)
        check("and processes nothing", stats["processed"] == 0)

    conn.close()
    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if skipped:
        print(f"{len(skipped)} check(s) skipped (no Tesseract on this machine).")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL OCR CHECKS PASSED")
    return 0


def _png_to_pdf(png: Path, tmp: Path) -> Path:
    """Wrap an image in a PDF so the page-rendering path is exercised."""
    import pymupdf

    out = tmp / (png.stem + ".pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(page.rect, filename=str(png))
    doc.save(str(out))
    doc.close()
    return out


if __name__ == "__main__":
    raise SystemExit(main())
