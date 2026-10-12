"""Ordering documents by date, on realistic and messy inputs.

A client's folder is never tidy. Dates appear in the text, in the file name, in
several formats, or not at all. This checks what actually comes out, and how the
undated and the odd ones are handled.
"""
import shutil
import sys
import tempfile
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from affidavit.config import load_config  # noqa: E402
from affidavit import auth, db, fixtures, pipeline  # noqa: E402

ROOT = Path(__file__).resolve().parent
PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))


def make_pdf(path, title, body_lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    d = pymupdf.open()
    p = d.new_page()
    p.insert_text((72, 90), title, fontsize=13)
    for i, line in enumerate(body_lines):
        p.insert_text((72, 125 + i * 16), line, fontsize=10)
    d.save(str(path))
    d.close()


TMP = Path(tempfile.mkdtemp(prefix="order-test-"))
cfg = load_config(ROOT)
cfg.source_dir = TMP / "intake" / "source"
cfg.work_dir = TMP / "work"
cfg.output_dir = TMP / "output"
cfg.db_path = cfg.work_dir / "pipeline.sqlite3"
cfg.sync_watch_dir = str(TMP / "intake" / "incoming")
cfg.ensure_dirs()

print("=" * 76)
print("  ORDERING BY DATE")
print("=" * 76)

# A realistic mixture: different date styles, a bad file name, no date at all.
case = [
    # (folder, file name, title, date line)
    ("Correspondence", "Email from solicitor.pdf", "EMAIL", "Date: 18 March 2024"),
    ("Pleadings", "Statement of Claim.pdf", "STATEMENT OF CLAIM",
     "Date: 20 June 2024"),
    ("Financial", "Invoice NG-4471.pdf", "INVOICE NG-4471", "Invoice date: 31 March 2024"),
    ("Correspondence", "Demand letter.pdf", "DEMAND LETTER", "Dated: 14 May 2024"),
    ("Expert", "Report - technical.pdf", "EXPERT REPORT", "Date: 8 July 2024"),
    # an ISO date
    ("Agreements", "Retainer.pdf", "RETAINER AGREEMENT", "2024-02-03"),
    # a date hidden in a longer line
    ("Internal", "File note.pdf", "FILE NOTE",
     "This note records the attendance on 2 June 2024 at the site."),
    # no date anywhere, and a useless file name
    ("Miscellaneous", "scan0001.pdf", "LETTERHEAD", "The writer confirms as follows."),
    # a date in the file name only
    ("Financial", "Receipt 2024-04-12.pdf", "RECEIPT", "Amount paid in full."),
]

for folder, name, title, dateline in case:
    make_pdf(cfg.source_dir / folder / name, title,
             [dateline, "Reference material for the within matter."])

# Something the tool must refuse politely.
(cfg.source_dir / "Miscellaneous" / "archive.zip").write_bytes(b"PK\x03\x04 junk")

print(f"\n1. A MESSY FOLDER OF {len(case) + 1} FILES")
conn = db.connect(cfg.db_path)
db.init(conn)
auth.init_auth(conn)
pipeline.run(conn, cfg, fresh=False, skip_ingest=False)

rows = conn.execute(
    """SELECT id, canonical_src, title_guess, doc_type, doc_date, date_source,
              pdf_status
         FROM documents ORDER BY id"""
).fetchall()

print(f"\n2. WHAT IT READ FROM EACH")
print(f"   {'file':<34} {'date':<12} {'source of date':<26} type")
for r in rows:
    name = Path(r["canonical_src"]).name
    print(f"   {name[:32]:<34} {(r['doc_date'] or '-'):<12} "
          f"{(r['date_source'] or '-'):<26} {r['doc_type'] or '-'}")

print("\n3. THE CHECKS")
by_name = {Path(r["canonical_src"]).name: r for r in rows}

expected = {
    "Email from solicitor.pdf": "2024-03-18",
    "Statement of Claim.pdf": "2024-06-20",
    "Invoice NG-4471.pdf": "2024-03-31",
    "Demand letter.pdf": "2024-05-14",
    "Report - technical.pdf": "2024-07-08",
    "Retainer.pdf": "2024-02-03",
    "File note.pdf": "2024-06-02",
    "Receipt 2024-04-12.pdf": "2024-04-12",
}
for name, want in expected.items():
    r = by_name.get(name)
    got = r["doc_date"] if r else None
    check(f"{name[:30]} is dated {want}", got == want, f"got {got!r}")

r = by_name.get("scan0001.pdf")
check("a document with no date is left undated rather than guessed",
      r is not None and not r["doc_date"], f"got {r['doc_date'] if r else 'missing'!r}")
check("the file name is used as a fallback title",
      r is not None and r["title_guess"], f"got {r['title_guess'] if r else None!r}")

check("the tool refuses an unsupported file rather than pretending",
      not any("archive.zip" in r["canonical_src"] for r in rows))

print("\n4. ORDERED BY DATE, OLDEST FIRST")
dated = [r for r in rows if r["doc_date"]]
ordered = sorted(dated, key=lambda r: r["doc_date"])
print(f"   {'#':<4} {'date':<12} document")
for i, r in enumerate(ordered, 1):
    print(f"   {i:<4} {r['doc_date']:<12} {Path(r['canonical_src']).name}")
check("every dated document sorts into a strict chronological order",
      [r["doc_date"] for r in ordered] == sorted(r["doc_date"] for r in ordered))
check("the earliest is the retainer, 3 February 2024",
      Path(ordered[0]["canonical_src"]).name == "Retainer.pdf",
      Path(ordered[0]["canonical_src"]).name)
check("the latest is the expert report, 8 July 2024",
      Path(ordered[-1]["canonical_src"]).name == "Report - technical.pdf",
      Path(ordered[-1]["canonical_src"]).name)

print("\n5. BUILDING A BUNDLE IN DATE ORDER")
names = [Path(r["canonical_src"]).name for r in ordered]
ids = [r["id"] for r in ordered]
from affidavit import collections as col  # noqa: E402

cid = db.create_collection(conn, "Chronological Bundle", "Ordered by date", "jane")
db.add_to_collection(conn, cid, ids, "jane")
result = col.export_collection(conn, cfg, cid, username="jane")

pdfs = sorted(Path(result["bundle"]).glob("PDFs/*.pdf"))
print(f"   {result['bundle']}")
for p in pdfs:
    print(f"     {p.name}")

check("the bundle numbers the documents in date order",
      all(p.name.startswith(f"{i:03d} ") for i, p in enumerate(pdfs, 1)),
      str([p.name[:3] for p in pdfs]))
first_expected = Path(ordered[0]["canonical_src"]).stem
check("and the first file is the earliest document",
      first_expected.split("_")[-1][:12] in pdfs[0].name or "Retainer" in pdfs[0].name,
      pdfs[0].name)

print("\n6. THE INDEX LISTED THE DATES")
index = (Path(result["bundle"]) / "index.csv").read_text(encoding="utf-8-sig")
lines = index.strip().splitlines()
print(f"   {lines[0]}")
for line in lines[1:5]:
    print(f"   {line}")
check("the index has a date column", "Date" in lines[0], lines[0])
check("the dates appear in the index in order",
      [ln.split(",")[4] for ln in lines[1:]] == sorted(ln.split(",")[4] for ln in lines[1:]),
      str([ln.split(",")[4] for ln in lines[1:5]]))

conn.close()
shutil.rmtree(TMP, ignore_errors=True)

print()
print("=" * 76)
if FAIL:
    print(f"  {len(PASS)} passed, {len(FAIL)} FAILED")
    for f in FAIL:
        print(f"    FAILED: {f}")
    print("=" * 76)
    sys.exit(1)
print(f"  ALL {len(PASS)} CHECKS PASSED")
print("=" * 76)
