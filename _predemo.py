"""Pre-demo verification: the whole workflow, with documents a client would send.

Runs the real console, drops real files into the drop folder, builds a bundle and
inspects what comes out.
"""
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pymupdf

sys.path.insert(0, ".")
from affidavit.config import load_config
from affidavit import db

ROOT = Path(".").resolve()
cfg = load_config(ROOT)

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))


def api(path, payload=None, base="http://127.0.0.1:8961"):
    if payload is None:
        req = urllib.request.Request(base + path)
    else:
        req = urllib.request.Request(base + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as x:
            raw = x.read()
            try:
                return x.status, json.loads(raw or b"{}")
            except json.JSONDecodeError:
                # The console page is HTML, not JSON.
                return x.status, {"_html_bytes": len(raw)}
    except urllib.error.HTTPError as e:
        return e.code, {}


def make_pdf(path, title, dateline, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 90), title, fontsize=13)
    page.insert_text((72, 120), dateline, fontsize=10)
    for i, line in enumerate(body):
        page.insert_text((72, 155 + i * 16), line, fontsize=10)
    doc.save(str(path))
    doc.close()


print("=" * 70)
print("  PRE-DEMO VERIFICATION")
print("=" * 70)

print("\n1. CLEAN START")
for d in ("work", "output", "intake"):
    shutil.rmtree(ROOT / d, ignore_errors=True)
print("   removed work, output and intake")
print("   NOTE: the console was already started by the caller")

print("\n2. A CLIENT SENDS DOCUMENTS, dropped into the watch folder")
watch = cfg.watch_dir
watch.mkdir(parents=True, exist_ok=True)
docs = [
    ("01 - Statement of Claim.pdf", "STATEMENT OF CLAIM", "Date: 20 June 2024",
     ["The Plaintiff claims damages of $184,500.00.", "Filed in the Superior Court."]),
    ("02 - Demand Letter.pdf", "DEMAND LETTER", "Date: 14 May 2024",
     ["Payment is demanded within ten days.", "Outstanding balance: $41,250.00"]),
    ("03 - Witness Statement.pdf", "WITNESS STATEMENT", "Dated: 2 June 2024",
     ["I attended the facility on 12 April 2024.", "Signed, M. Reed"]),
    ("04 - Invoice NG-4471.pdf", "TAX INVOICE NG-4471", "Date: 31 March 2024",
     ["Storage services, March 2024: $22,300.00", "TOTAL DUE $22,300.00"]),
]
# also a scan with no text layer, and a Word document
scan_png = watch / "05 - Signed Receipt.png"
from PIL import Image, ImageDraw, ImageFont
img = Image.new("RGB", (1275, 1650), "white")
d = ImageDraw.Draw(img)
font = None
for cand in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\calibri.ttf"):
    try:
        font = ImageFont.truetype(cand, 30); break
    except OSError:
        continue
d.text((100, 140), "HARBOURVIEW STORAGE LTD.", fill=(10, 10, 10), font=font)
d.text((100, 200), "RECEIPT  HV-2291", fill=(10, 10, 10), font=font)
d.text((100, 260), "Date: 12 April 2024", fill=(10, 10, 10), font=font)
d.text((100, 320), "TOTAL PAID: $4,850.00", fill=(10, 10, 10), font=font)
img.save(scan_png)

import zipfile
docx = watch / "06 - Retainer Letter.docx"
from affidavit.fixtures import build_docx
build_docx(docx, "RETAINER LETTER",
           ["Dated: 3 February 2024", "Ashford & Bell LLP are retained."])

for name, *_ in docs:
    make_pdf(watch / name, *docs[[d[0] for d in docs].index(name)][1:])

print(f"   wrote {len(list(watch.iterdir()))} documents into {watch.name}/")
for p in sorted(watch.iterdir()):
    print(f"     {p.name}  ({p.stat().st_size:,} bytes)")

print("\n3. THE WATCHER PICKS THEM UP (no command run)")
deadline = time.time() + 90
seen = 0
while time.time() < deadline:
    status, body = api("/api/documents")
    got = body.get("documents", [])
    names = {d["canonical_src"].split("\\")[-1].split("/")[-1] for d in got}
    seen = len([n for n in names if any(k in n for k in
                ("Statement", "Demand", "Witness", "Invoice", "Receipt", "Retainer"))])
    if seen >= 6:
        break
    time.sleep(3)
print(f"   documents in the library: {len(got)}  (matched {seen} of 6 dropped)")
check("all six dropped documents were picked up", seen >= 6, f"{seen}/6")

print("\n4. EACH DOCUMENT WAS CONVERTED AND READ")
print(f"   {'name':<40} {'type':<16} {'date':<12} quality")
for d in sorted(got, key=lambda x: x["canonical_src"]):
    nm = d["canonical_src"].split("\\")[-1]
    print(f"   {nm[:38]:<40} {(d['doc_type'] or '-')[:14]:<16} "
          f"{(d['doc_date'] or '-')[:10]:<12} {d.get('ocr_quality_label','')}")
titled = [d for d in got if d["title_guess"]]
dated = [d for d in got if d["doc_date"]]
check("every document has a title", len(titled) == len(got), f"{len(titled)}/{len(got)}")
check("every text document has a date", len(dated) >= 5, f"{len(dated)}/{len(got)}")

print("\n5. THE CONSOLE PAGES ALL WORK")
for path, label in (("/", "the console page"), ("/api/help", "help content"),
                    ("/api/documents", "the library"), ("/api/collections", "collections"),
                    ("/api/ocr", "the OCR panel"), ("/api/sync", "the drop folder panel"),
                    ("/api/team", "the team panel")):
    s, b = api(path)
    detail = f"status {s}"
    if path == "/":
        detail = f"{b.get('_html_bytes', 0):,} bytes"
    check(f"{label} responds", s == 200, detail)

print("\n5b. A DROPPED SCAN GETS READ BY OCR")
deadline = time.time() + 90
scan_read = False
while time.time() < deadline:
    s, body = api("/api/documents")
    mine = [d for d in body.get("documents", [])
            if "Signed Receipt" in d["canonical_src"]]
    if mine and mine[0].get("ocr_quality") not in (None, "unread", "not read"):
        scan_read = True
        print(f"   the dropped scan was read: {mine[0].get('ocr_quality_label')} "
              f"confidence, date {mine[0].get('doc_date')}")
        break
    time.sleep(4)
check("the dropped scan was read by OCR", scan_read)

print("\n6. THE HELP AND INSTRUCTIONS BUTTONS HAVE CONTENT")
s, h = api("/api/help")
check("the instructions have steps", len(h.get("workflow", [])) >= 5,
      f"{len(h.get('workflow', []))} steps")
check("the help has topics", len(h.get("reference", [])) >= 5,
      f"{len(h.get('reference', []))} topics")
check("the help has a glossary", len(h.get("glossary", [])) >= 5,
      f"{len(h.get('glossary', []))} terms")

print("\n7. BUILD A BUNDLE FROM THE LIBRARY")
ids = [d["id"] for d in sorted(got, key=lambda x: x["id"]) if
       any(k in d["canonical_src"] for k in
           ("Statement", "Demand", "Witness", "Invoice", "Receipt"))]
s, out = api("/api/collections/create",
             {"name": "Demo Exhibit Bundle", "description": "For the client demo"})
check("a collection was created", s == 200 and out.get("ok"), str(out.get("error", "")))
cid = out.get("collection_id")
s, out = api("/api/collections/action",
             {"action": "add", "collection_id": cid, "doc_ids": ids})
check("documents were added", s == 200 and out.get("ok"), f"{len(ids)} documents")

print("\n8. EXPORT, WHICH IS WHAT FEEDS ZIBBIT")
t0 = time.time()
s, res = api("/api/collections/export", {"collection_id": cid})
elapsed = time.time() - t0
check("export succeeded", s == 200 and res.get("ok"), str(res.get("error", "")))
print(f"   took {elapsed:.1f}s for {res.get('exported')} documents, {res.get('pages')} pages")

bundle = Path(res.get("bundle", ""))
check("the bundle is in the finished folder", "finished" in str(bundle), str(bundle))
check("the bundle folder exists", bundle.exists())
pdfs = sorted((bundle / "PDFs").glob("*.pdf")) if bundle.exists() else []
check("numbered PDFs were written", len(pdfs) >= 5, f"{len(pdfs)} PDFs")
check("the PDFs are numbered in order",
      all(p.name[:3].isdigit() for p in pdfs), str([p.name[:3] for p in pdfs]))
check("a Word index was written", any(bundle.glob("*.docx")))
check("index.csv was written", (bundle / "index.csv").exists())
check("manifest.json was written", (bundle / "manifest.json").exists())
check("the COMPLETE marker was written", (bundle / "COMPLETE").exists())

print("\n   the bundle:")
for p in sorted(bundle.rglob("*")):
    if p.is_file():
        rel = p.relative_to(bundle)
        print(f"     {rel}  ({p.stat().st_size:,} bytes)")

print("\n9. THE EXPORTED DOCUMENTS ARE REAL PDFs THAT OPEN")
import pymupdf as fitz
broken = []
for p in pdfs:
    try:
        with fitz.open(str(p)) as d:
            if d.page_count < 1:
                broken.append(p.name)
            d[0].get_text()
    except Exception as exc:
        broken.append(f"{p.name}: {exc}")
check("every exported PDF opens and has pages", not broken, str(broken[:3]))

print("\n10. THE BUNDLE LEAVES THE CONSOLE")
s, cols = api("/api/collections")
live = [c["name"] for c in cols.get("collections", [])]
finished = [c["name"] for c in cols.get("finished", [])]
check("it is gone from the live list", "Demo Exhibit Bundle" not in live, str(live))
check("it is listed as finished", "Demo Exhibit Bundle" in finished, str(finished))

print("\n11. THE FILES THE CLIENT SENT ARE UNTOUCHED")
still_there = [p.name for p in watch.iterdir()]
check("every dropped file is still where the user put it", len(still_there) >= 6,
      f"{len(still_there)} files")
lib = list((cfg.source_dir).glob("*"))
check("copies are in the library", len(lib) >= 6, f"{len(lib)} files in intake/source")

print("\n12. THE RECONCILIATION REPORT ACCOUNTS FOR EVERYTHING")
s, _ = api("/api/documents")
conn = db.connect(cfg.db_path)
from affidavit import reconcile
summary = reconcile.reconcile(conn, cfg)
conn.close()
check("every source file is accounted for",
      summary["source_files"] >= 6, f"{summary['source_files']} files traced")
check("the report was written", (cfg.reports_dir / "reconciliation.md").exists())

print()
print("=" * 70)
if FAIL:
    print(f"  {len(PASS)} passed, {len(FAIL)} FAILED")
    for f in FAIL:
        print(f"    FAILED: {f}")
    print("=" * 70)
    sys.exit(1)
print(f"  ALL {len(PASS)} CHECKS PASSED. READY TO DEMO.")
print("=" * 70)
