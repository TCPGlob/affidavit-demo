"""Text and metadata extraction.

Pulls whatever is deterministically knowable out of a PDF: page count, text
layer, dates, document type, party mentions, and -- importantly -- privilege
markers, which are surfaced as *suggestions for a human*, never as decisions.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

PRIVILEGE_PATTERNS: list[tuple[str, str]] = [
    (r"without\s+prejudice", "Settlement privilege (marked 'without prejudice')"),
    (r"solicitor[- ]client\s+privileg", "Solicitor-client privilege (express marking)"),
    (r"privileged\s*(?:&|and)?\s*confidential", "Marked privileged and confidential"),
    (r"litigation\s+privileg", "Litigation privilege (express marking)"),
    (r"\bprivileged\b", "Contains the word 'privileged' - verify"),
    (r"subject\s+to\s+solicitor[- ]client", "Subject to solicitor-client privilege"),
]

DOCTYPE_RULES: list[tuple[str, str]] = [
    # Order matters: the first match wins, so specific rules come first and
    # generic ones (Letter, Document) come last.
    # Email requires real header structure. Matching the bare word "email"
    # would classify any document that merely mentions one as an email.
    (
        r"(?:^|\n)\s*(?:from|sent|to|subject)\s*:|"
        r"\be-?mail\s+(?:chain|thread|correspondence)\b",
        "Email",
    ),
    (r"\b(?:invoice|tax\s+invoice)\b", "Invoice"),
    (r"\bstatement\s+of\s+account\b|\baccount\s+statement\b", "Statement of Account"),
    (r"\b(?:receipt|proof\s+of\s+payment|remittance)\b", "Receipt"),
    (r"\b(?:memorandum\s+to\s+file|memo\s+to\s+file|file\s+note)\b", "File Note"),
    (r"\baddendum\b", "Addendum"),
    (r"\b(?:contract|agreement)\b", "Agreement"),
    (r"\b(?:engagement|retainer)\s+letter\b", "Retainer Letter"),
    (r"\b(?:minutes|meeting\s+notes)\b", "Meeting Notes"),
    (r"\b(?:affidavit|statutory\s+declaration|statement\s+of\s+claim|statement\s+of\s+defence)\b", "Pleading"),
    (r"\b(?:demand\s+letter|notice)\b", "Notice"),
    (r"\b(?:policy|policies|procedure)s?\b", "Policy"),
    (r"\b(?:report|assessment|analysis)\b", "Report"),
    (r"\b(?:spreadsheet|budget|ledger|schedule)\b", "Spreadsheet"),
    (r"\b(?:presentation|slide)\b", "Presentation"),
    (r"\b(?:photo|photograph|image|screenshot)\b", "Photograph"),
    (r"\b(?:memorandum|memo)\b", "Memorandum"),
    (r"\bletter\b", "Letter"),
]

MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)

_MONTH_ALT = (
    "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    "aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)

# Free-scanning patterns, used only by find_dates() for reference output.
DATE_PATTERNS = [
    re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"),
    re.compile(r"\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b"),
    re.compile(rf"\b\d{{1,2}}\s+(?:{_MONTH_ALT})\.?,?\s+\d{{4}}\b", re.I),
    re.compile(rf"\b(?:{_MONTH_ALT})\.?\s+\d{{1,2}},?\s+\d{{4}}\b", re.I),
]

_WS = re.compile(r"\s+")


@dataclass
class Extraction:
    text: str = ""
    page_count: int | None = None
    has_text_layer: bool = False
    needs_ocr: bool = False
    title_guess: str = ""
    doc_type: str = ""
    doc_date: str = ""
    date_source: str = ""
    privilege_flags: list[str] = field(default_factory=list)
    party_hits: list[str] = field(default_factory=list)
    summary: str = ""
    text_fingerprint: str = ""
    error: str = ""


# ---------------------------------------------------------------- pdf text

def pdf_text(path: Path, max_pages: int = 12) -> tuple[str, int | None, str]:
    """Return (text, page_count, error). Tries PyMuPDF, then pypdf."""
    from .compat import HAS_PYMUPDF, PYMUPDF

    if HAS_PYMUPDF:
        try:
            with PYMUPDF.open(str(path)) as doc:
                n = doc.page_count
                chunks = []
                for i, page in enumerate(doc):
                    if i >= max_pages:
                        break
                    chunks.append(page.get_text())
                return "\n".join(chunks), n, ""
        except Exception:  # noqa: BLE001
            pass

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        n = len(reader.pages)
        chunks = []
        for i, page in enumerate(reader.pages):
            if i >= max_pages:
                break
            chunks.append(page.extract_text() or "")
        return "\n".join(chunks), n, ""
    except Exception as exc:  # noqa: BLE001
        return "", None, f"no PDF text backend available: {exc}"


# ---------------------------------------------------------------- dates

def _norm_date(y: int, m: int, d: int) -> str | None:
    try:
        return datetime(y, m, d).date().isoformat()
    except ValueError:
        return None


_MONTH_ALT = (
    "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    "aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)

# A date that follows an explicit label ("Date:", "Dated", "Sent:") is the most
# reliable signal, so it is tried first.
DATE_LABEL_RE = re.compile(
    rf"(?:^|\n)[ \t]*(?:dated?|date\s+of|sent|received|issued|signed|executed)"
    rf"\s*[:\-–]?\s*([^\n]{{4,60}})",
    re.I,
)

# Dates in the opening block are next best: a letter or memo states its date
# up front. Scanning the whole document risks picking up a referenced date.
DATE_NEAR_TOP_RE = re.compile(
    rf"\b(\d{{4}}-\d{{1,2}}-\d{{1,2}}"
    rf"|\d{{4}}-?\d{{2}}-?\d{{2}}"
    rf"|\d{{1,2}}[/.]\d{{1,2}}[/.]\d{{2,4}}"
    rf"|\d{{1,2}}\s+(?:{_MONTH_ALT})\.?,?\s+\d{{4}}"
    rf"|(?:{_MONTH_ALT})\.?\s+\d{{1,2}},?\s+\d{{4}})\b",
    re.I,
)

_MONTH_ALT_NUM = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_date_token(token: str) -> str | None:
    """Turn one matched date string into an ISO date, or None."""
    token = token.strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", token)
    if m:
        return _norm_date(int(m[1]), int(m[2]), int(m[3]))
    # OCR frequently loses a separator: "202404-12" or "20240412". Only accept
    # an 8-digit run when it parses as a real ISO date, so stray reference
    # numbers are not silently turned into dates.
    m = re.fullmatch(r"(\d{4})-?(\d{2})-?(\d{2})", token)
    if m:
        return _norm_date(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})", token)
    if m:
        day, month, year = int(m[1]), int(m[2]), int(m[3])
        year = year + 2000 if year < 100 else year
        # Canadian practice is day-first.
        return _norm_date(year, month, day)
    m = re.fullmatch(rf"(\d{{1,2}})\s+([A-Za-z]+)\.?,?\s+(\d{{4}})", token)
    if m:
        month = _MONTH_ALT_NUM.get(m[2][:4].lower()) or _MONTH_ALT_NUM.get(m[2][:3].lower())
        if month:
            return _norm_date(int(m[3]), month, int(m[1]))
    m = re.fullmatch(rf"([A-Za-z]+)\.?\s+(\d{{1,2}}),?\s+(\d{{4}})", token)
    if m:
        month = _MONTH_ALT_NUM.get(m[1][:4].lower()) or _MONTH_ALT_NUM.get(m[1][:3].lower())
        if month:
            return _norm_date(int(m[3]), month, int(m[2]))
    return None


def find_labelled_date(text: str) -> str | None:
    """A date introduced by 'Date:', 'Dated', 'Sent:', etc."""
    for m in DATE_LABEL_RE.finditer(text[:3000]):
        for tok in DATE_NEAR_TOP_RE.findall(m.group(1)):
            d = parse_date_token(tok)
            if d:
                return d
    return None


def find_date_near_top(text: str, window: int = 1200) -> str | None:
    """The first recognizable date in the document's opening block."""
    for tok in DATE_NEAR_TOP_RE.findall(text[:window]):
        d = parse_date_token(tok)
        if d:
            return d
    return None


def find_dates(text: str) -> list[str]:
    """All distinct dates anywhere in the text, for reference."""
    out: list[str] = []
    for pat in DATE_PATTERNS:
        for m in pat.finditer(text):
            d = parse_date_token(m.group(0))
            if d:
                out.append(d)
    seen, uniq = set(), []
    for d in out:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq


def guess_date_from_name(name: str) -> str | None:
    dates = find_dates(name)
    return dates[0] if dates else None


# ---------------------------------------------------------------- text analysis

def guess_doctype(name: str, text: str) -> str:
    """Infer a document type, preferring the file name over the body.

    The file name is usually deliberate -- a firm that names a file
    "Demand Letter 2024-05-14.pdf" means it. Matching keywords in the body is
    unreliable: an email that merely mentions an invoice is not an invoice.
    """
    name_l = name.lower()
    for pat, label in DOCTYPE_RULES:
        if re.search(pat, name_l, re.I):
            return label
    head = text[:1500]
    for pat, label in DOCTYPE_RULES:
        if re.search(pat, head, re.I):
            return label
    return "Document"


def find_privilege_flags(name: str, text: str) -> list[str]:
    hay = f"{name}\n{text[:8000]}"
    hits: list[str] = []
    for pat, label in PRIVILEGE_PATTERNS:
        if re.search(pat, hay, re.I):
            hits.append(label)
    return hits


def find_party_hits(text: str, parties: list[str]) -> list[str]:
    hits = []
    for p in parties:
        p = (p or "").strip()
        if len(p) < 3:
            continue
        if re.search(re.escape(p), text, re.I):
            hits.append(p)
    return hits


def make_summary(text: str, limit: int = 200) -> str:
    lines = [ln.strip() for ln in text.splitlines()]
    keep: list[str] = []
    for ln in lines:
        if not ln:
            continue
        # skip the placeholder banner noise
        if ln.isupper() and len(ln) > 40:
            continue
        keep.append(ln)
        if sum(len(k) for k in keep) > limit:
            break
    s = _WS.sub(" ", " ".join(keep)).strip()
    return s[:limit]


def fingerprint(text: str) -> str:
    norm = _WS.sub(" ", text.lower()).strip()
    norm = re.sub(r"[^a-z0-9 ]", "", norm)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]


def title_from_name(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem.title() if stem.islower() or stem.isupper() else stem


# ---------------------------------------------------------------- entry point

PLACEHOLDER_MARK = "PLACEHOLDER - NOT THE ORIGINAL DOCUMENT"


def has_readable_text(text: str) -> bool:
    """Is there a usable text layer?

    Word count rather than character count, and a deliberately low bar. A short
    receipt or a one-line memo is perfectly readable while having few characters;
    an earlier 40-character threshold classified such documents as "unreadable
    scans" and sent them to OCR repeatedly.
    """
    compact = _WS.sub(" ", text).strip()
    if len(compact) >= 20:
        return True
    return len([w for w in compact.split() if any(c.isalnum() for c in w)]) >= 3


def extract(pdf_path: Path, source_name: str, parties: list[str] | None = None) -> Extraction:
    ex = Extraction()
    if not pdf_path or not Path(pdf_path).exists():
        ex.error = "no pdf to extract from"
        return ex

    ex.title_guess = title_from_name(source_name)
    text, pages, err = pdf_text(pdf_path)
    ex.page_count = pages
    if err:
        ex.error = err
        return ex

    ex.text = text
    ex.has_text_layer = has_readable_text(text)
    ex.needs_ocr = not ex.has_text_layer

    # A placeholder generated because a converter was missing must never be
    # described as if it were the real document.
    if PLACEHOLDER_MARK in text:
        ex.doc_type = "Placeholder (converter missing)"
        ex.summary = "[NOT THE ORIGINAL DOCUMENT - converter not installed]"
        ex.doc_date, ex.date_source = guess_date_from_name(source_name) or "", "filename"
        ex.privilege_flags = []
        return ex

    if not ex.needs_ocr:
        ex.doc_type = guess_doctype(source_name, text)
        ex.privilege_flags = find_privilege_flags(source_name, text)
        ex.party_hits = find_party_hits(text, parties or [])
        ex.summary = make_summary(text)
        ex.text_fingerprint = fingerprint(text)

        # Date priority: explicit label > opening block > filename.
        d = find_labelled_date(text)
        if d:
            ex.doc_date, ex.date_source = d, "labelled date field"
        else:
            d = find_date_near_top(text)
            if d:
                ex.doc_date, ex.date_source = d, "date in opening text"
    else:
        ex.doc_type = guess_doctype(source_name, "")
        ex.summary = "[image-only scan - no text layer; OCR required]"
        ex.privilege_flags = find_privilege_flags(source_name, "")

    if not ex.doc_date:
        d = guess_date_from_name(source_name)
        if d:
            ex.doc_date, ex.date_source = d, "filename"

    return ex
