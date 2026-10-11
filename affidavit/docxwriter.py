"""Minimal, dependency-free Word (.docx) writer.

The team works in Microsoft Word, so the index must arrive as a Word document
they can open, edit and swear -- not a CSV they have to import.

python-docx is not available on this machine and pip is blocked by the sandbox,
so this writes WordprocessingML directly using the standard library. It is a
valid OOXML package, which is all Word requires.

Only the small subset of WordprocessingML actually needed is emitted: headings,
paragraphs, bold runs, tables, and correct column widths.
"""

from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# Letter page, 1 inch margins (twips: 1 inch = 1440)
PAGE_W = 12240
MARGIN = 1440
CONTENT_W = PAGE_W - 2 * MARGIN


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _rpr(bold: bool = False, italic: bool = False, size_half_pt: int = 22,
         color: str | None = None, font: str = "Calibri") -> str:
    parts = [
        f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}"/>',
        f'<w:sz w:val="{size_half_pt}"/>',
        f'<w:szCs w:val="{size_half_pt}"/>',
    ]
    if bold:
        parts.append("<w:b/>")
    if italic:
        parts.append("<w:i/>")
    if color:
        parts.append(f'<w:color w:val="{color}"/>')
    return f"<w:rPr>{''.join(parts)}</w:rPr>"


def para(text: str = "", bold: bool = False, italic: bool = False,
         size_half_pt: int = 22, align: str | None = None, space_after: int = 120,
         color: str | None = None, style: str | None = None) -> str:
    rpr = _rpr(bold, italic, size_half_pt, color)
    ppr = [f'<w:spacing w:after="{space_after}"/>']
    if align:
        ppr.append(f'<w:jc w:val="{align}"/>')
    if style:
        ppr.append(f'<w:pStyle w:val="{style}"/>')
    runs = f"<w:r>{rpr}<w:t xml:space=\"preserve\">{_esc(text)}</w:t></w:r>" if text else ""
    return f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>{runs}</w:p>"


def heading(text: str, size_half_pt: int = 28) -> str:
    return para(text, bold=True, size_half_pt=size_half_pt, space_after=160)


def _cell(text: str, width_tw: int, bold: bool = False, shade: str | None = None,
          size_half_pt: int = 20) -> str:
    tcpr = [f'<w:tcW w:w="{width_tw}" w:type="dxa"/>']
    if shade:
        tcpr.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{shade}"/>')
    # keep text from touching the cell edge
    tcpr.append('<w:tcMar><w:top w:w="40" w:type="dxa"/><w:bottom w:w="40" w:type="dxa"/>'
                '<w:left w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tcMar>')
    rpr = _rpr(bold, size_half_pt=size_half_pt)
    body = f"<w:r>{rpr}<w:t xml:space=\"preserve\">{_esc(text)}</w:t></w:r>" if text else ""
    return (
        f"<w:tc><w:tcPr>{''.join(tcpr)}</w:tcPr>"
        f"<w:p><w:pPr><w:spacing w:after=\"20\"/></w:pPr>{body}</w:p></w:tc>"
    )


def table(headers: list[str], rows: list[list[str]], widths: list[int]) -> str:
    """A bordered table with a shaded, repeating header row."""
    total = sum(widths)
    scale = CONTENT_W / total if total else 1
    widths = [int(w * scale) for w in widths]

    borders = (
        "<w:tblBorders>"
        '<w:top w:val="single" w:sz="4" w:color="999999"/>'
        '<w:left w:val="single" w:sz="4" w:color="999999"/>'
        '<w:bottom w:val="single" w:sz="4" w:color="999999"/>'
        '<w:right w:val="single" w:sz="4" w:color="999999"/>'
        '<w:insideH w:val="single" w:sz="4" w:color="CCCCCC"/>'
        '<w:insideV w:val="single" w:sz="4" w:color="CCCCCC"/>'
        "</w:tblBorders>"
    )
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    head = (
        "<w:tr><w:trPr><w:tblHeader/></w:trPr>"
        + "".join(_cell(h, w, bold=True, shade="F2F4F7") for h, w in zip(headers, widths))
        + "</w:tr>"
    )
    body = "".join(
        "<w:tr>" + "".join(_cell(c, w) for c, w in zip(row, widths)) + "</w:tr>"
        for row in rows
    )
    return (
        f'<w:tbl><w:tblPr><w:tblW w:w="{CONTENT_W}" w:type="dxa"/>'
        f"{borders}<w:tblLayout w:type=\"fixed\"/></w:tblPr>"
        f"<w:tblGrid>{grid}</w:tblGrid>{head}{body}</w:tbl>"
    )


def page_break() -> str:
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


# ---------------------------------------------------------------- package

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W}">
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="120"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
</w:styles>"""


def write_docx(path: Path, body_xml: str, title: str = "Index of Documents",
               author: str = "Affidavit pipeline") -> None:
    """Assemble a valid .docx package around the given body XML."""
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>{body_xml}'
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
        'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        "</w:body></w:document>"
    )
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{_esc(title)}</dc:title>"
        f"<dc:creator>{_esc(author)}</dc:creator>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
        "</cp:coreProperties>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("docProps/core.xml", core)


def read_docx_text(path: Path) -> str:
    """Extract visible text from a .docx (used to verify output)."""
    import re

    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    xml = xml.replace("</w:p>", "\n").replace("</w:tc>", " | ")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", xml))
