"""Local OCR for image-only scans.

Tesseract runs as a subprocess on this machine. There are no cloud calls and no
API keys, so scanned client material never leaves the computer.

The central design decision: **OCR never alters the document that gets exported.**
A scanned page is evidence, and a re-rendered version of it is not the same
exhibit. So OCR produces a separate searchable copy used only for reading and
metadata:

    work/ocr/<hash>.pdf    searchable copy, for titles/dates/search

The bundle still exports the original scan. OCR's job is to stop the tool being
blind to scanned documents, not to rewrite them.

If Tesseract is not installed, every function here reports that plainly and the
pipeline carries on exactly as before.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .compat import HAS_PYMUPDF, PYMUPDF

DEFAULT_LANG = "eng"
DEFAULT_DPI = 200
DEFAULT_MAX_PAGES = 25

# Where Tesseract usually lands on Windows. Checked because the installer does
# not always add it to PATH for the current session.
WINDOWS_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"C:\Users\Public\Tesseract-OCR\tesseract.exe",
]


@dataclass
class OcrTool:
    path: str | None = None
    version: str = ""
    languages: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.path)


@dataclass
class OcrResult:
    pdf_path: Path | None = None
    status: str = "not_attempted"
    # ok | no_text_found | unavailable | failed | skipped
    pages: int = 0
    text_chars: int = 0
    detail: str = ""
    mean_confidence: float | None = None


def find_tesseract() -> OcrTool:
    """Locate Tesseract without assuming it is on PATH."""
    exe = shutil.which("tesseract")
    if not exe:
        local = Path.home() / "AppData" / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe"
        for cand in [*WINDOWS_CANDIDATES, str(local)]:
            if Path(cand).exists():
                exe = cand
                break
    if not exe:
        return OcrTool()

    tool = OcrTool(path=exe)
    try:
        proc = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
        first = (proc.stdout or proc.stderr or "").splitlines()
        tool.version = first[0].strip() if first else ""
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=30)
        lines = (proc.stdout or "").splitlines()
        tool.languages = [ln.strip() for ln in lines[1:] if ln.strip()]
    except (OSError, subprocess.SubprocessError):
        pass
    return tool


def pick_language(tool: OcrTool, requested: str = "") -> str:
    """Use the requested language if its data is installed, else fall back."""
    if not requested:
        return DEFAULT_LANG
    available = set(tool.languages)
    if not available:
        return requested
    wanted = [p for p in requested.split("+") if p]
    usable = [p for p in wanted if p in available]
    if not usable:
        return DEFAULT_LANG
    return "+".join(usable)


def _render_pages(pdf: Path, work: Path, dpi: int, max_pages: int):
    """Yield (index, PIL image) for up to max_pages pages."""
    if not HAS_PYMUPDF:
        return
    from PIL import Image
    import io

    with PYMUPDF.open(str(pdf)) as doc:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            yield i, img


def _build_searchable(pdf: Path, work: Path, dpi: int, max_pages: int,
                      tsv_rows: dict[int, list[dict]]):
    """Write a new PDF whose pages are images with an invisible text layer.

    Text is placed at the word's true position, at a font size derived from the
    recognised box height, so it is selectable and searchable but invisible.
    """
    out = PYMUPDF.open()
    from PIL import Image
    import io

    with PYMUPDF.open(str(pdf)) as doc:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(dpi=dpi)
            newpage = out.new_page(width=page.rect.width, height=page.rect.height)
            newpage.insert_image(newpage.rect, stream=pix.tobytes("png"))

            for w in tsv_rows.get(i, []):
                text = (w.get("text") or "").strip()
                if not text:
                    continue
                try:
                    left = float(w["left"]) / dpi * 72.0
                    top = float(w["top"]) / dpi * 72.0
                    width = float(w["width"]) / dpi * 72.0
                    height = float(w["height"]) / dpi * 72.0
                except (TypeError, ValueError, KeyError):
                    continue
                if width <= 0 or height <= 0:
                    continue
                fontsize = max(4.0, height * 0.85)
                # Scale the text to fill the recognised box.
                rendered = PYMUPDF.get_text_length(text, fontsize=fontsize)
                if rendered > 0:
                    fontsize *= max(0.35, min(3.0, width / rendered))
                try:
                    newpage.insert_text(
                        (left, top + fontsize),
                        text,
                        fontsize=fontsize,
                        render_mode=3,   # invisible: searchable, not visible
                    )
                except Exception:  # noqa: BLE001 - skip a bad word, keep the page
                    continue

    work.parent.mkdir(parents=True, exist_ok=True)
    out.save(str(work))
    out.close()


def ocr_pdf(pdf: Path, dest: Path, tool: OcrTool, *, lang: str = DEFAULT_LANG,
            dpi: int = DEFAULT_DPI, max_pages: int = DEFAULT_MAX_PAGES,
            timeout: int = 180) -> OcrResult:
    """OCR a PDF into a searchable copy at `dest`.

    Returns a result describing what happened. Never raises: a failure here must
    not lose a document.
    """
    if not tool.available:
        return OcrResult(status="unavailable",
                         detail="Tesseract is not installed on this machine")
    if not HAS_PYMUPDF:
        return OcrResult(status="failed", detail="PyMuPDF is required to render pages")
    if not pdf.exists():
        return OcrResult(status="failed", detail=f"missing file: {pdf}")

    tsv_rows: dict[int, list[dict]] = {}
    texts: list[str] = []
    confidences: list[float] = []
    pages_done = 0
    notes: list[str] = []

    try:
        with tempfile.TemporaryDirectory(prefix="aod-ocr-") as tmp:
            tmpdir = Path(tmp)
            for i, img in _render_pages(pdf, tmpdir, dpi, max_pages):
                png = tmpdir / f"page-{i:04d}.png"
                img.save(png, "PNG")
                base = tmpdir / f"out-{i:04d}"

                try:
                    proc = subprocess.run(
                        [str(tool.path), str(png), str(base),
                         "-l", lang, "--oem", "3", "--psm", "3", "tsv"],
                        capture_output=True, text=True, timeout=timeout,
                    )
                except subprocess.TimeoutExpired:
                    notes.append(f"page {i + 1} timed out")
                    continue
                except OSError as exc:
                    return OcrResult(status="failed", detail=f"tesseract: {exc}")

                if proc.returncode != 0:
                    notes.append(f"page {i + 1} failed (rc={proc.returncode})")
                    continue

                tsv_file = base.with_suffix(".tsv")
                rows: list[dict] = []
                if tsv_file.exists():
                    lines = tsv_file.read_text(encoding="utf-8", errors="replace").splitlines()
                    if lines:
                        header = lines[0].split("\t")
                        for line in lines[1:]:
                            parts = line.split("\t")
                            if len(parts) != len(header):
                                continue
                            row = dict(zip(header, parts))
                            rows.append(row)
                            if row.get("text", "").strip():
                                texts.append(row["text"])
                                try:
                                    conf = float(row.get("conf", -1))
                                    if conf >= 0:
                                        confidences.append(conf)
                                except ValueError:
                                    pass
                tsv_rows[i] = rows
                pages_done += 1

            if pages_done == 0:
                return OcrResult(status="failed", detail="no pages could be rendered")

            text = " ".join(texts).strip()
            if len(text) < 20:
                return OcrResult(
                    status="no_text_found", pages=pages_done, text_chars=len(text),
                    detail="Tesseract found no readable text"
                           + (f" ({'; '.join(notes)})" if notes else ""),
                )

            _build_searchable(pdf, dest, dpi, max_pages, tsv_rows)

        mean_conf = round(sum(confidences) / len(confidences), 1) if confidences else None
        detail = f"{pages_done} page(s) via {Path(tool.path).name} ({lang}, {dpi} dpi)"
        if notes:
            detail += f"; {'; '.join(notes)}"
        return OcrResult(pdf_path=dest, status="ok", pages=pages_done,
                         text_chars=len(text), detail=detail,
                         mean_confidence=mean_conf)

    except Exception as exc:  # noqa: BLE001 - OCR failure must never lose a document
        return OcrResult(status="failed", detail=f"{type(exc).__name__}: {exc}")


def ocr_image(path: Path, dest: Path, tool: OcrTool, *, lang: str = DEFAULT_LANG,
              timeout: int = 180) -> OcrResult:
    """OCR a standalone image into a searchable single-page PDF."""
    if not tool.available:
        return OcrResult(status="unavailable",
                         detail="Tesseract is not installed on this machine")
    try:
        with tempfile.TemporaryDirectory(prefix="aod-ocr-") as tmp:
            base = Path(tmp) / "out"
            proc = subprocess.run(
                [str(tool.path), str(path), str(base), "-l", lang, "tsv"],
                capture_output=True, text=True, timeout=timeout,
            )
            tsv_file = base.with_suffix(".tsv")
            text = ""
            rows: list[dict] = []
            if tsv_file.exists():
                lines = tsv_file.read_text(encoding="utf-8", errors="replace").splitlines()
                if lines:
                    header = lines[0].split("\t")
                    for line in lines[1:]:
                        parts = line.split("\t")
                        if len(parts) == len(header):
                            row = dict(zip(header, parts))
                            rows.append(row)
                            if row.get("text", "").strip():
                                text += row["text"] + " "
            if proc.returncode != 0 or len(text.strip()) < 10:
                return OcrResult(status="no_text_found", text_chars=len(text.strip()),
                                 detail="Tesseract found no readable text")
            return OcrResult(pdf_path=dest, status="ok", pages=1,
                             text_chars=len(text.strip()),
                             detail=f"single image via {lang}")
    except subprocess.TimeoutExpired:
        return OcrResult(status="failed", detail="tesseract timed out")
    except Exception as exc:  # noqa: BLE001
        return OcrResult(status="failed", detail=f"{type(exc).__name__}: {exc}")


def describe_tool() -> str:
    tool = find_tesseract()
    if not tool.available:
        return "Tesseract: not installed"
    langs = ", ".join(tool.languages[:8]) or "none reported"
    return f"Tesseract: {tool.version} | languages: {langs}"
