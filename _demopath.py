"""Verify the exact sequence the demo will follow, with nothing interfering.

    double-click demo-windows.bat   (equivalent to: pipeline.py review --demo)
    drop a file into intake/incoming
    it appears in the console

Nothing is deleted while the app is running, because that is not something a
person demoing would do.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pymupdf

sys.path.insert(0, ".")
from affidavit.config import load_config

ROOT = Path(".").resolve()
cfg = load_config(ROOT)
BASE = "http://127.0.0.1:8971"
PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))


def api(path, payload=None):
    req = (urllib.request.Request(BASE + path) if payload is None else
           urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                  headers={"Content-Type": "application/json"},
                                  method="POST"))
    try:
        with urllib.request.urlopen(req, timeout=60) as x:
            raw = x.read()
            try:
                return x.status, json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return x.status, {"_bytes": len(raw)}
    except urllib.error.HTTPError as e:
        return e.code, {}


print("=" * 70)
print("  DEMO PATH VERIFICATION")
print("=" * 70)

print("\n1. THE CONSOLE IS UP (started with --demo)")
s, b = api("/")
check("the console page loads", s == 200 and b.get("_bytes", 0) > 20000,
      f"{b.get('_bytes', 0):,} bytes")
s, b = api("/api/sync")
check("the drop folder watcher is alive", b.get("status", {}).get("alive") is True,
      f"last check {b.get('status', {}).get('seconds_since_heartbeat')}s ago")
print(f"   watching: {b.get('status', {}).get('watch_dir')}")

s, b = api("/api/documents")
docs = b.get("documents", [])
check("sample documents are loaded", len(docs) > 5, f"{len(docs)} documents")
s, h = api("/api/help")
check("the Help window has content", len(h.get("reference", [])) >= 5,
      f"{len(h.get('reference', []))} topics")
check("the Instructions have content", len(h.get("workflow", [])) >= 5,
      f"{len(h.get('workflow', []))} steps")

print("\n2. DROP A NEW DOCUMENT, AS A CLIENT WOULD")
watch = cfg.watch_dir
before = len(docs)
drop = watch / "Notice of Motion.pdf"
doc = pymupdf.open()
p = doc.new_page()
p.insert_text((72, 90), "NOTICE OF MOTION", fontsize=13)
p.insert_text((72, 120), "Date: 12 October 2026", fontsize=10)
p.insert_text((72, 150), "The defendant shall produce the listed documents.", fontsize=10)
doc.save(str(drop))
doc.close()
print(f"   copied one file into {watch.name}/")

print("   waiting, running nothing...")
found = None
deadline = time.time() + 60
while time.time() < deadline:
    s, b = api("/api/documents")
    docs = b.get("documents", [])
    hits = [d for d in docs if "Motion" in (d.get("title_guess") or "")]
    if hits:
        found = hits[0]
        break
    time.sleep(3)

check("the dropped document appeared on its own", found is not None)
if found:
    print(f"     title : {found['title_guess']}")
    print(f"     type  : {found['doc_type']}")
    print(f"     date  : {found['doc_date']}")
    check("its type was read", bool(found.get("doc_type")))
    check("its date was read", found.get("doc_date") == "2026-10-12",
          str(found.get("doc_date")))
check("the library grew by one", len(docs) == before + 1, f"{before} -> {len(docs)}")

print("\n3. BUILD AND EXPORT A BUNDLE")
ids = [d["id"] for d in docs][:4]
s, out = api("/api/collections/create",
             {"name": "Client Demo Bundle", "description": "Prepared for the demo"})
check("a collection was created", s == 200 and out.get("ok"))
cid = out.get("collection_id")
s, out = api("/api/collections/action",
             {"action": "add", "collection_id": cid, "doc_ids": ids})
check("documents were added to it", s == 200 and out.get("ok"))
s, res = api("/api/collections/export", {"collection_id": cid})
check("the export succeeded", s == 200 and res.get("ok"), str(res.get("error", "")))

bundle = Path(res.get("bundle", ""))
pdfs = sorted((bundle / "PDFs").glob("*.pdf")) if bundle.exists() else []
check("numbered PDFs were produced", len(pdfs) >= 3, f"{len(pdfs)} PDFs")
check("the Word index was produced", any(bundle.glob("*.docx")))
check("the COMPLETE marker was written", (bundle / "COMPLETE").exists())
print(f"   bundle: {bundle}")
for p_ in sorted(bundle.rglob("*")):
    if p_.is_file():
        print(f"     {p_.relative_to(bundle)}")

print("\n4. THE BUNDLE LEFT THE CONSOLE")
s, cols = api("/api/collections")
live = [c["name"] for c in cols.get("collections", [])]
check("it is no longer in the live list", "Client Demo Bundle" not in live, str(live))

print("\n5. THE USER'S FILE IS UNTOUCHED")
check("the dropped file is still in the drop folder", drop.exists())

print("\n6. THE REPORT IS HONEST ABOUT WHAT IT FOUND")
from affidavit import db, reconcile
conn = db.connect(cfg.db_path)
summary = reconcile.reconcile(conn, cfg)
conn.close()
missing = [p for p in summary["problems"] if "MISSING FILE" in p]
check("no normalised files are unaccounted for", not missing, str(missing[:2]))
print(f"   {summary['source_files']} source files traced, "
      f"{len(summary['problems'])} item(s) to be aware of")
for p_ in summary["problems"][:6]:
    print(f"     - {p_[:100]}")

print()
print("=" * 70)
if FAIL:
    print(f"  {len(PASS)} passed, {len(FAIL)} FAILED")
    for f in FAIL:
        print(f"    FAILED: {f}")
    print("=" * 70)
    sys.exit(1)
print(f"  ALL {len(PASS)} CHECKS PASSED. THE DEMO PATH WORKS.")
print("=" * 70)
