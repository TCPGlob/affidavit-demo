"""Toolchain detection and conversion to PDF.

Every external tool is optional. When one is missing we do NOT silently drop
the document -- we record exactly what happened so the reconciliation report
can prove nothing vanished, and we substitute a clearly-marked placeholder so
the rest of the pipeline remains exercisable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .compat import HAS_PYMUPDF, PYMUPDF

# ---------------------------------------------------------------- formats

OFFICE_EXTS = {".doc", ".docx", ".rtf", ".odt", ".ppt", ".pptx", ".odp"}
SHEET_EXTS = {".xls", ".xlsx", ".ods", ".csv", ".tsv"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".heic", ".heif"}
PDF_EXTS = {".pdf"}
MAIL_EXTS = {".msg", ".eml", ".emlx"}
TEXT_EXTS = {".txt", ".md", ".log"}

SUPPORTED_EXTS = OFFICE_EXTS | SHEET_EXTS | IMAGE_EXTS | PDF_EXTS | MAIL_EXTS | TEXT_EXTS


@dataclass
class Tool:
    name: str
    path: str | None
    purpose: str
    install_hint: str

    @property
    def available(self) -> bool:
        return bool(self.path)


def _which(*candidates: str) -> str | None:
    for c in candidates:
        p = shutil.which(c)
        if p:
            return p
    return None


def _first_existing(paths: list[str]) -> str | None:
    for p in paths:
        if Path(p).exists():
            return p
    return None


def detect_toolchain() -> list[Tool]:
    soffice = _which("soffice", "libreoffice") or _first_existing(
        [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            "/usr/bin/soffice",
            "/usr/local/bin/soffice",
        ]
    )
    tools = [
        Tool(
            "libreoffice",
            soffice,
            "Convert Office formats (DOCX/XLSX/PPTX) to PDF",
            "https://www.libreoffice.org/download/  (or: winget install TheDocumentFoundation.LibreOffice)",
        ),
        Tool(
            "tesseract",
            _which("tesseract"),
            "OCR image-only scans into a searchable text layer",
            "https://github.com/UB-Mannheim/tesseract/wiki  (or: winget install UB-Mannheim.TesseractOCR)",
        ),
        Tool(
            "pypdf",
            _which("python") if _has_module("pypdf") else None,
            "PDF page counts, merge and metadata",
            "python -m pip install pypdf",
        ),
        Tool(
            "pymupdf",
            _which("python") if HAS_PYMUPDF else None,
            "Read/write PDFs; render scanned images into PDF pages",
            "python -m pip install pymupdf",
        ),
        Tool(
            "pillow",
            _which("python") if _has_module("PIL") else None,
            "Read image formats such as HEIC/TIFF",
            "python -m pip install pillow pillow-heif",
        ),
    ]
    return tools


def _has_module(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False




def print_toolchain(tools: list[Tool]) -> None:
    print("\nToolchain")
    print("-" * 66)
    for t in tools:
        mark = "OK  " if t.available else "MISS"
        print(f"  [{mark}] {t.name:<12} {t.purpose}")
        if not t.available:
            print(f"           -> install: {t.install_hint}")
    missing = [t.name for t in tools if not t.available]
    if missing:
        print(
            f"\n  Degraded mode: {', '.join(missing)} missing.\n"
            "  Documents of those types are converted to a clearly-marked\n"
            "  PLACEHOLDER pdf and flagged in the reconciliation report.\n"
            "  The pipeline still runs end to end."
        )
    print()


# ---------------------------------------------------------------- conversion

@dataclass
class ConversionResult:
    pdf_path: Path | None
    status: str  # ok | passthrough | skipped_no_converter | unsupported | failed
    detail: str = ""
    page_count: int | None = None


def _run(cmd: list[str], timeout: int = 180) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def soffice_to_pdf(src: Path, out_dir: Path, soffice: str) -> ConversionResult:
    """Convert an Office document via LibreOffice headless."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as profile:
        cmd = [
            soffice,
            f"-env:UserInstallation=file:///{profile.replace(os.sep, '/').lstrip('/')}",
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(src),
        ]
        code, log = _run(cmd)
    produced = out_dir / (src.stem + ".pdf")
    if code == 0 and produced.exists():
        return ConversionResult(produced, "ok", "libreoffice")
    return ConversionResult(None, "failed", f"libreoffice rc={code}: {log.strip()[:300]}")


def image_to_pdf(src: Path, dest: Path) -> ConversionResult:
    """Wrap a scanned image as a single-page PDF."""
    try:
        from PIL import Image
    except ImportError:
        return ConversionResult(None, "failed", "pillow not installed")

    try:
        img = Image.open(src)
        # HEIC and some TIFFs need the plugin registered before .load()
        try:
            from pillow_heif import register_heif_opener

            register_heif_opener()
            img = Image.open(src)
        except ImportError:
            pass

        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, "PDF", resolution=200.0)
        return ConversionResult(dest, "ok", "pillow", page_count=1)
    except Exception as exc:  # noqa: BLE001 - report, never crash the batch
        return ConversionResult(None, "failed", f"image: {exc}")


def pdf_page_count(path: Path) -> int | None:
    if HAS_PYMUPDF:
        try:
            with PYMUPDF.open(str(path)) as doc:
                return doc.page_count
        except Exception:  # noqa: BLE001
            pass
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001
        return None


def placeholder_pdf(src: Path, dest: Path, reason: str) -> ConversionResult:
    """Emit a clearly-marked placeholder so the pipeline stays exercisable.

    This exists ONLY so the proof of concept can run without LibreOffice
    installed. It is never a substitute for the real document, and the
    reconciliation report flags every placeholder loudly.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "PLACEHOLDER - NOT THE ORIGINAL DOCUMENT",
        "",
        f"Source file : {src.name}",
        f"Reason      : {reason}",
        "",
        "This PDF was generated because the required converter is not",
        "installed on this machine. It must NOT be produced to the other",
        "side or filed. Install the missing tool and re-run the pipeline.",
    ]
    try:
        if not HAS_PYMUPDF:
            return ConversionResult(None, "skipped_no_converter", "PyMuPDF not installed")
        doc = PYMUPDF.open()
        page = doc.new_page()
        y = 90
        for i, line in enumerate(lines):
            size = 16 if i == 0 else 11
            page.insert_text((72, y), line, fontsize=size)
            y += 26 if i == 0 else 18
        doc.save(str(dest))
        doc.close()
        return ConversionResult(dest, "skipped_no_converter", reason, page_count=1)
    except Exception:
        pass
    return ConversionResult(None, "skipped_no_converter", reason)


def text_to_pdf(src: Path, dest: Path) -> ConversionResult:
    """Render a plain-text file as a paginated PDF. No external tool needed."""
    if not HAS_PYMUPDF:
        return ConversionResult(None, "failed", "PyMuPDF not installed")
    import textwrap

    try:
        raw = src.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return ConversionResult(None, "failed", f"unreadable text: {exc}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    doc = PYMUPDF.open()
    page = doc.new_page(width=612, height=792)
    margin, line_h, y = 66, 14.5, 66

    def new_page():
        nonlocal page, y
        page = doc.new_page(width=612, height=792)
        y = margin

    for para in raw.splitlines():
        for chunk in (textwrap.wrap(para, 92) or [""]):
            if y > 792 - margin:
                new_page()
            page.insert_text((margin, y), chunk, fontsize=10)
            y += line_h
        y += line_h * 0.4

    doc.save(str(dest))
    n = doc.page_count
    doc.close()
    return ConversionResult(dest, "ok", "native text render", page_count=n)


def convert_to_pdf(
    src: Path,
    dest: Path,
    tools: dict[str, Tool],
) -> ConversionResult:
    """Dispatch a source file to the right converter."""
    ext = src.suffix.lower()

    if ext in PDF_EXTS:
        try:
            n = pdf_page_count(src)
            return ConversionResult(src, "passthrough", "already PDF", page_count=n)
        except Exception as exc:  # noqa: BLE001
            return ConversionResult(None, "failed", f"unreadable pdf: {exc}")

    if ext in IMAGE_EXTS:
        return image_to_pdf(src, dest)

    # Plain text needs no external tool, so do it natively rather than
    # degrading to a placeholder when LibreOffice happens to be absent.
    if ext in TEXT_EXTS:
        return text_to_pdf(src, dest)

    if ext in OFFICE_EXTS | SHEET_EXTS | MAIL_EXTS:
        soffice = tools["libreoffice"].path
        if soffice:
            res = soffice_to_pdf(src, dest.parent, soffice)
            if res.pdf_path:
                res.pdf_path = res.pdf_path.rename(dest)
                res.page_count = pdf_page_count(dest)
            return res
        return placeholder_pdf(
            src, dest, f"LibreOffice not installed; cannot convert {ext}"
        )

    return ConversionResult(None, "unsupported", f"no converter for {ext}")
