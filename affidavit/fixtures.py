"""Generate a realistic demo intake folder.

The documents are synthetic but shaped like a real Ontario civil matter, so the
pipeline exercises: nested folders, duplicates in different formats, an
image-only scan needing OCR, privilege-marked material, undated documents,
unsupported formats, and a zero-byte file.
"""

from __future__ import annotations

import textwrap
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .compat import PYMUPDF

# A4-ish; letter is 612x792
PAGE = (612, 792)
MARGIN = 66
LINE = 14.5
FONT = "helv"
MAX_CHARS = 92


@dataclass
class Fixture:
    relpath: str
    kind: str  # pdf | docx | png | blank | raw
    title: str = ""
    body: list[str] | None = None
    min_pages: int = 1
    text: str = ""


def wrap(text: str) -> list[str]:
    if not text.strip():
        return [""]
    return textwrap.wrap(text, MAX_CHARS) or [""]


def build_pdf(path: Path, title: str, body: list[str], min_pages: int = 1, footer: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = PYMUPDF.open()
    page = doc.new_page(width=PAGE[0], height=PAGE[1])
    y = MARGIN

    def new_page() -> None:
        nonlocal page, y
        page = doc.new_page(width=PAGE[0], height=PAGE[1])
        y = MARGIN

    if title:
        page.insert_text((MARGIN, y), title, fontsize=13, fontname="hebo")
        y += LINE * 1.9

    for para in body:
        for line in wrap(para):
            if y > PAGE[1] - MARGIN:
                new_page()
            page.insert_text((MARGIN, y), line, fontsize=10, fontname=FONT)
            y += LINE
        y += LINE * 0.55

    while doc.page_count < min_pages:
        new_page()
        page.insert_text(
            (MARGIN, MARGIN), f"{title} (continued)", fontsize=11, fontname="hebo"
        )
        y = MARGIN + LINE * 2
        for i in range(28):
            if y > PAGE[1] - MARGIN:
                break
            page.insert_text(
                (MARGIN, y), f"     {i + 1}. [continued schedule of particulars]", fontsize=10
            )
            y += LINE

    if footer:
        for p in doc:
            p.insert_text((MARGIN, PAGE[1] - 40), footer, fontsize=8, color=(0.4, 0.4, 0.4))

    doc.save(str(path))
    doc.close()


def build_scanned_image(path: Path, title: str = "", lines: list[str] | None = None) -> None:
    """Render text into an image-only document, as a scanner would.

    There is no text layer, so the pipeline must OCR it to know anything about
    it. A real font at a realistic size is used deliberately: OCR quality on a
    12px default bitmap font is not representative of a real scan.
    """
    from PIL import Image, ImageDraw, ImageFont

    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (1275, 1650), "white")
    d = ImageDraw.Draw(img)

    font = None
    for candidate in (
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        try:
            font = ImageFont.truetype(candidate, 30)
            break
        except (OSError, ValueError):
            continue
    big = font.font_variant(size=44) if hasattr(font, "font_variant") else font

    y = 120
    if title:
        d.text((100, y), title, fill=(15, 15, 15), font=big)
        y += 90
    for line in (lines or []):
        d.text((100, y), line, fill=(20, 20, 20), font=font)
        y += 52
    # A rule under the header, so it looks like a document rather than a caption.
    d.line([(100, y + 10), (1175, y + 10)], fill=(120, 120, 120), width=3)

    img.save(path)


def build_blank_pdf(path: Path, title: str) -> None:
    """A page with no text layer - stands in for an image-only scan."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = PYMUPDF.open()
    page = doc.new_page(width=PAGE[0], height=PAGE[1])
    # Draw only shapes: there is deliberately no extractable text.
    page.draw_rect(PYMUPDF.Rect(60, 60, 550, 730), color=(0.6, 0.6, 0.6), width=1)
    for i in range(18):
        top = 100 + i * 34
        page.draw_line((80, top), (520, top), color=(0.75, 0.75, 0.75), width=2)
    doc.save(str(path))
    doc.close()


def build_receipt_image(path: Path) -> None:
    """A deliberately poor PNG: a low-resolution photo of a receipt.

    Kept as a second OCR case alongside the clean scan, because OCR quality on a
    bad image is the realistic situation and the pipeline should still recover
    the key fields.
    """
    from PIL import Image, ImageDraw

    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (1000, 1300), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, 960, 1260], outline=(90, 90, 90), width=3)
    d.text((80, 90), "HARBOURVIEW STORAGE LTD.", fill=(20, 20, 20))
    d.text((80, 140), "RECEIPT  #HV-2291", fill=(20, 20, 20))
    d.text((80, 190), "Date: 2024-04-12", fill=(20, 20, 20))
    for i in range(14):
        d.line([(80, 260 + i * 60), (920, 260 + i * 60)], fill=(190, 190, 190), width=2)
    d.text((80, 1180), "TOTAL PAID: $4,850.00", fill=(20, 20, 20))
    img.save(path)


def build_docx(path: Path, title: str, lines: list[str]) -> None:
    """Write a minimal but valid .docx using only the standard library."""
    path.parent.mkdir(parents=True, exist_ok=True)

    def para(text: str, bold: bool = False) -> str:
        rpr = '<w:rPr><w:b/></w:rPr>' if bold else ""
        safe = (
            text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        return (
            f'<w:p><w:pPr><w:spacing w:after="160"/></w:pPr>'
            f"<w:r>{rpr}<w:t xml:space=\"preserve\">{safe}</w:t></w:r></w:p>"
        )

    body = [para(title, bold=True)] + [para(line) for line in lines]
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(body)}</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)


# ------------------------------------------------------------------ content

ENGAGEMENT = [
    "This Engagement Letter confirms the retainer of Ashford & Bell LLP by Northgate",
    "Property Holdings Inc. in connection with the Harbourview Storage dispute.",
    "",
    "1. SCOPE OF RETAINER",
    "The Firm will act for the Client in the within proceeding, including the",
    "preparation and exchange of pleadings, discovery, and any motion or appeal",
    "arising from the same.",
    "",
    "2. FEES AND DISBURSEMENTS",
    "Fees are billed at the rates set out in Schedule 1. Disbursements are billed",
    "at cost. Accounts are rendered monthly and are payable within 30 days.",
    "",
    "3. CONFLICTS",
    "The Firm confirms that it has no conflict of interest in accepting this",
    "retainer, having searched its client database as at the date hereof.",
    "",
    "Dated at Toronto this 3rd day of February, 2024.",
    "ASHFORD & BELL LLP",
]

CLAIM = [
    "TO THE DEFENDANT: A LEGAL PROCEEDING HAS BEEN COMMENCED AGAINST YOU by the",
    "Plaintiff. The claim made against you is set out in the following pages.",
    "",
    "1. The Plaintiff Northgate Property Holdings Inc. is a corporation",
    "incorporated under the laws of the Province of Ontario.",
    "",
    "2. The Defendant Harbourview Storage Ltd. is a corporation carrying on",
    "business as a commercial storage operator in the City of Toronto.",
    "",
    "3. By written agreement dated 15 January 2023 the parties entered into a",
    "storage and logistics services agreement for a term of five years.",
    "",
    "4. The Plaintiff paid the sum of $184,500.00 to the Defendant between",
    "January 2023 and March 2024 in accordance with the agreement.",
    "",
    "5. The Defendant failed to provide the services contracted for, particulars",
    "of which failure are known to the Defendant.",
    "",
    "6. The Plaintiff claims damages in the amount of $184,500.00, pre-judgment",
    "and post-judgment interest, and costs on a substantial indemnity basis.",
]

DEMAND = [
    "Re: Outstanding account - Invoice NG-4471 and Invoice NG-4502",
    "",
    "We are counsel for Northgate Property Holdings Inc. Our client's account with",
    "yours has been outstanding since 30 April 2024. Despite two reminders, no",
    "payment has been received.",
    "",
    "The outstanding balance is $41,250.00, comprised of Invoice NG-4471 in the",
    "amount of $22,300.00 and Invoice NG-4502 in the amount of $18,950.00.",
    "",
    "Demand is hereby made for payment in full within ten (10) days of the date of",
    "this letter. Failing payment, our client has instructed us to commence legal",
    "proceedings without further notice, and to seek costs on a substantial",
    "indemnity basis.",
    "",
    "Dated: 14 May 2024",
    "Per: Ashford & Bell LLP",
]

WITNESS_MEMO = [
    "PRIVILEGED AND CONFIDENTIAL - PREPARED IN ANTICIPATION OF LITIGATION",
    "",
    "Date: 2 June 2024",
    "",
    "Re: Interview of Marcus Reed, former operations manager",
    "",
    "I attended at Mr. Reed's residence and interviewed him for approximately",
    "ninety minutes. The following is a summary prepared for the purpose of",
    "providing legal advice to the client in relation to the within proceeding.",
    "",
    "Mr. Reed states that on 8 March 2024 he was instructed by the Defendant's",
    "director to remove certain inventory records from the facility. He did not",
    "comply with that instruction and no records were in fact removed.",
    "",
    "Mr. Reed is willing to provide a statement. His recollection of the 12 April",
    "2024 site visit differs materially from the account given in the Defendant's",
    "statement of defence. This memorandum is subject to solicitor-client",
    "privilege and is prepared in contemplation of litigation.",
]

STRATEGY_MEMO = [
    "SOLICITOR-CLIENT PRIVILEGED - DO NOT PRODUCE",
    "",
    "MEMORANDUM TO FILE",
    "Date: 18 June 2024",
    "",
    "Re: Assessment of exposure and settlement posture",
    "",
    "Our client's position on the quantum of damages is strong on the documents",
    "produced to date. The principal vulnerability is the absence of a signed",
    "change order for the March 2024 works, which the Defendant will argue",
    "varied the scope of the agreement.",
    "",
    "Recommendation: resist production of the internal audit correspondence and",
    "advance a settlement offer in the range of $95,000 to $110,000. My opinion",
    "on the likely outcome at trial is set out above and is provided for the",
    "purpose of enabling the client to give instructions.",
]

EMAIL_CHAIN = [
    "From: dana.whitfield@northgate-property.ca",
    "Sent: Tuesday, 9 April 2024 3:42 PM",
    "To: accounts@harbourviewstorage.com",
    "Cc: legal@northgate-property.ca",
    "Subject: RE: Invoice NG-4471 - overdue",
    "",
    "Hello,",
    "",
    "Following up again on Invoice NG-4471 dated 31 March 2024 in the amount of",
    "$22,300.00. Our records show this remains unpaid, as does NG-4502.",
    "",
    "Please confirm by return when we can expect payment. If there is a dispute",
    "about the invoiced amounts, we would appreciate specifics rather than",
    "silence.",
    "",
    "Regards,",
    "Dana Whitfield",
    "Controller, Northgate Property Holdings Inc.",
]

INVOICE = [
    "INVOICE NG-4471",
    "",
    "From: Northgate Property Holdings Inc.",
    "To:   Harbourview Storage Ltd.",
    "",
    "Invoice Date: 31 March 2024",
    "Payment Terms: Net 30",
    "",
    "Description                                    Amount",
    "Storage services - January 2024               $7,450.00",
    "Storage services - February 2024              $7,450.00",
    "Site supervision and reporting                $4,200.00",
    "Facility maintenance - February                $3,200.00",
    "                                               ---------",
    "TOTAL DUE                                     $22,300.00",
    "",
    "Please remit payment to the account on file.",
]

POLICY = [
    "NORTHGATE PROPERTY HOLDINGS INC.",
    "RECORDS RETENTION POLICY",
    "",
    "Policy No. NR-04. Approved by the Board of Directors.",
    "",
    "1. PURPOSE",
    "This policy establishes the retention periods for records created or",
    "received by the Corporation in the course of its business.",
    "",
    "2. RETENTION PERIODS",
    "Financial records shall be retained for a period of seven (7) years from",
    "the end of the fiscal year to which they relate. Contracts and agreements",
    "shall be retained for seven (7) years following expiry or termination.",
    "",
    "3. DESTRUCTION",
    "Records shall be destroyed by secure means once the applicable retention",
    "period has elapsed, and destruction shall be logged.",
    "",
    "4. NO DATE OF ISSUANCE IS RECORDED ON THIS COPY.",
]

PLAN = [
    "HARBOURVIEW FACILITY - REMEDIATION PLAN",
    "",
    "Phase 1 - Site assessment and inventory reconciliation",
    "Phase 2 - Removal of damaged inventory",
    "Phase 3 - Structural repair to Bay 4",
    "Phase 4 - Final inspection and handover",
    "",
    "Note: this plan was circulated in draft. No date appears on the face of the",
    "document and no covering email has been located.",
]

FIXTURES: list[Fixture] = [
    # --- nested folders, the way a real matter folder looks ---
    Fixture("01 - Agreements/Engagement Letter - Ashford Bell 2024-02-03.pdf", "pdf",
            "ENGAGEMENT LETTER", ENGAGEMENT, min_pages=2),
    Fixture("01 - Agreements/Storage Services Agreement 2023-01-15.pdf", "pdf",
            "STORAGE AND LOGISTICS SERVICES AGREEMENT",
            ["This Agreement is made as of the 15th day of January, 2023, between",
             "Northgate Property Holdings Inc. and Harbourview Storage Ltd.",
             "",
             "1. SERVICES. The Service Provider shall provide storage, handling and",
             "logistics services at the facility located in the City of Toronto.",
             "",
             "2. TERM. The term of this Agreement is five (5) years commencing",
             "1 February 2023 and terminating 31 January 2028.",
             "",
             "3. FEES. The Client shall pay the monthly fees set out in Schedule A."],
            min_pages=3),
    Fixture("01 - Agreements/Storage Services Agreement 2023-01-15 (copy).docx", "docx",
            "STORAGE AND LOGISTICS SERVICES AGREEMENT",
            ["This Agreement is made as of the 15th day of January, 2023."]),

    # --- correspondence ---
    Fixture("02 - Correspondence/Demand Letter 2024-05-14.pdf", "pdf",
            "DEMAND LETTER", DEMAND),
    Fixture("02 - Correspondence/Email chain - invoice overdue 2024-04-09.pdf", "pdf",
            "EMAIL", EMAIL_CHAIN),
    Fixture("02 - Correspondence/Statement of Claim 2024-06-20.pdf", "pdf",
            "STATEMENT OF CLAIM", CLAIM, min_pages=2),

    # --- financial ---
    Fixture("03 - Financial/Invoice NG-4471 2024-03-31.pdf", "pdf",
            "INVOICE", INVOICE),
    Fixture("03 - Financial/Invoice NG-4471 duplicate.pdf", "pdf",
            "INVOICE", INVOICE),
    Fixture("03 - Financial/Receipt HV-2291 scanned.png", "png", "RECEIPT"),
    # A scanned document with real content, so OCR has something to recover and
    # the recovered text can be asserted on.
    Fixture("03 - Financial/Scanned invoice NG-4502.png", "scan",
            "HARBOURVIEW STORAGE LTD.",
            [
                "TAX INVOICE NG-4502",
                "Date: 30 April 2024",
                "Client: Northgate Property Holdings Inc.",
                "",
                "Storage services April 2024          $18,950.00",
                "",
                "TOTAL DUE                            $18,950.00",
                "",
                "Payment terms: Net 30",
            ]),

    # --- internal: privilege material ---
    Fixture("04 - Internal/File note - witness interview 2024-06-02.pdf", "pdf",
            "FILE NOTE", WITNESS_MEMO),
    Fixture("04 - Internal/Memorandum to file - strategy 2024-06-18.pdf", "pdf",
            "MEMORANDUM TO FILE", STRATEGY_MEMO),

    # --- awkward cases ---
    Fixture("05 - Miscellaneous/Records Retention Policy.pdf", "pdf",
            "RECORDS RETENTION POLICY", POLICY),
    Fixture("05 - Miscellaneous/Remediation plan draft.pdf", "pdf",
            "REMEDIATION PLAN", PLAN),
    # .txt is a supported format and drives the "text changed" note path
    Fixture("05 - Miscellaneous/Contact list.txt", "raw",
            text="Northgate Property Holdings Inc. - contact list\n"
                 "Dana Whitfield, Controller, 416-555-0142\n"
                 "Marcus Reed, former operations manager\n"),
    # deliberately unsupported / degenerate inputs
    Fixture("05 - Miscellaneous/archive.zip", "raw", "unsupported container"),
    Fixture("05 - Miscellaneous/empty-file.pdf", "raw", "zero-byte file"),
    # a PDF page with no text layer at all: the OCR case
    Fixture("05 - Miscellaneous/Scanned exhibit (image only) - no text layer.pdf", "blank",
            "SCANNED EXHIBIT"),
]


def generate(dest: Path, clean: bool = True) -> dict:
    dest = Path(dest)
    if clean and dest.exists():
        import shutil

        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    written = 0
    for fx in FIXTURES:
        path = dest / fx.relpath
        if fx.kind == "pdf":
            build_pdf(path, fx.title, fx.body or [], min_pages=fx.min_pages)
        elif fx.kind == "docx":
            build_docx(path, fx.title, fx.body or [])
        elif fx.kind == "png":
            build_receipt_image(path)
        elif fx.kind == "scan":
            build_scanned_image(path, fx.title, fx.body or [])
        elif fx.kind == "blank":
            build_blank_pdf(path, fx.title)
        elif fx.kind == "raw":
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == ".zip":
                with zipfile.ZipFile(path, "w") as z:
                    z.writestr("readme.txt", "placeholder archive")
            elif fx.text:
                path.write_text(fx.text, encoding="utf-8")
            else:
                # degenerate input: a genuinely empty file
                path.write_bytes(b"")
        written += 1

    return {"written": written, "dest": str(dest)}
