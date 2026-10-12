"""Does "Clear everything" actually leave nothing behind?

The complaint was that library items and the contents of intake/source stayed.
This checks exactly that, through the running app, from the user's point of view.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
from affidavit.config import load_config  # noqa: E402

ROOT = Path(__file__).resolve().parent
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9121
B = f"http://127.0.0.1:{PORT}"

# Start our own server in a throwaway folder, so this runs unattended in CI and
# never touches a real library. It starts with the sample documents already in
# place, which is the state the complaint was about.
import shutil  # noqa: E402
import tempfile  # noqa: E402

cfg = load_config(ROOT)
_TMP = Path(tempfile.mkdtemp(prefix="clear-test-"))
cfg.source_dir = _TMP / "intake" / "source"
cfg.work_dir = _TMP / "work"
cfg.output_dir = _TMP / "output"
cfg.db_path = cfg.work_dir / "pipeline.sqlite3"
cfg.ensure_dirs()

from affidavit import auth as _auth  # noqa: E402
from affidavit import db as _db  # noqa: E402
from affidavit import fixtures as _fixtures  # noqa: E402
from affidavit import pipeline as _pipeline  # noqa: E402
from affidavit import review as _review  # noqa: E402

_conn = _db.connect(cfg.db_path)
_db.init(_conn)
_auth.init_auth(_conn)
_fixtures.generate(cfg.source_dir, clean=True)
_pipeline.run(_conn, cfg, fresh=False, skip_ingest=False)

from http.server import ThreadingHTTPServer  # noqa: E402
import threading  # noqa: E402
import time as _time  # noqa: E402

_httpd = ThreadingHTTPServer(
    ("127.0.0.1", PORT),
    _review._make_handler(_conn, cfg, require_auth=True, secure_cookie=False),
)
threading.Thread(target=_httpd.serve_forever, daemon=True).start()

# The app normally runs the folder watcher alongside the console. Without it
# nothing would be picked up, which is the whole behaviour under test here.
from affidavit import watcher as _watcher  # noqa: E402

_watch_conn = _db.connect_for_thread(cfg.db_path)
_w = _watcher.Watcher(_watch_conn, cfg, lock_name="clear-test")


def _watch_loop():
    while True:
        try:
            _w.scan_once()
        except Exception:  # noqa: BLE001
            pass
        _time.sleep(2)


threading.Thread(target=_watch_loop, daemon=True).start()
_time.sleep(1.0)
PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))


class NR(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a):
        return None


op = urllib.request.build_opener(NR)
cookie = {"v": None}


def get(path, timeout=120):
    h = {"Cookie": cookie["v"]} if cookie["v"] else {}
    try:
        with op.open(urllib.request.Request(B + path, headers=h), timeout=timeout) as x:
            raw = x.read()
            try:
                return x.status, json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return x.status, {"_bytes": len(raw)}
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return None, {"error": f"{type(e).__name__}"}


def post_json(path, payload, timeout=300):
    h = {"Content-Type": "application/json", "Origin": B}
    if cookie["v"]:
        h["Cookie"] = cookie["v"]
    req = urllib.request.Request(B + path, data=json.dumps(payload).encode(),
                                 headers=h, method="POST")
    try:
        with op.open(req, timeout=timeout) as x:
            return x.status, json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def post_form(path, fields):
    req = urllib.request.Request(
        B + path, data=urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with op.open(req, timeout=120) as x:
            sc = x.headers.get("Set-Cookie")
    except urllib.error.HTTPError as e:
        sc = e.headers.get("Set-Cookie")
    if sc:
        cookie["v"] = sc.split(";")[0]


def library_docs():
    s, b = get("/api/documents")
    return b.get("documents", [])


def source_files():
    if not cfg.source_dir.exists():
        return []
    return [p for p in cfg.source_dir.rglob("*") if p.is_file()]


def watch_files():
    if not cfg.watch_dir.exists():
        return []
    return [p for p in cfg.watch_dir.rglob("*") if p.is_file()]


print("=" * 74)
print("  CLEAR EVERYTHING: DOES IT ACTUALLY CLEAR?")
print("=" * 74)

print("\n1. SIGN IN AND GET A POPULATED LIBRARY")
s, _ = get("/")
if s == 303:
    post_form("/setup", {"display_name": "Jane", "username": "jane",
                         "password": "harbour-2024-storage",
                         "confirm": "harbour-2024-storage"})
docs = library_docs()
check("the Library starts populated", len(docs) > 0, f"{len(docs)} documents")
check("and intake/source has files", len(source_files()) > 0,
      f"{len(source_files())} files")

# Put something in the drop folder too, so we can see what happens to it.
import pymupdf  # noqa: E402

cfg.watch_dir.mkdir(parents=True, exist_ok=True)
mine = cfg.watch_dir / "My own document.pdf"
d = pymupdf.open()
p = d.new_page()
p.insert_text((72, 90), "MY OWN DOCUMENT", fontsize=13)
p.insert_text((72, 118), "Date: 9 September 2026", fontsize=10)
d.save(str(mine))
d.close()
print(f"   and I put my own file in the drop folder: {mine.name}")

# Make a collection, so we can see that cleared too.
s, out = post_json("/api/collections/create", {"name": "Test Bundle", "description": ""})
cid = out.get("collection_id")
if cid:
    post_json("/api/collections/action",
              {"action": "add", "collection_id": cid,
               "doc_ids": [x["id"] for x in docs[:2]]})
s, cols = get("/api/collections")
check("a collection exists to be cleared", len(cols.get("collections", [])) > 0,
      str([c["name"] for c in cols.get("collections", [])]))

print("\n   before clearing:")
print(f"     library documents : {len(library_docs())}")
print(f"     files in source   : {len(source_files())}")
print(f"     collections       : {len(cols.get('collections', []))}")

print("\n2. CLICK CLEAR EVERYTHING")
s, res = post_json("/api/library/reset", {"clear_samples": True})
check("the request succeeds", s == 200 and res.get("ok"), str(res.get("error", ""))[:60])
print(f"   response: {res}")

print("\n3. IS IT ACTUALLY CLEAR?")
# Give the watcher a moment: it may pick my dropped file up, which is correct
# behaviour, but the samples must not come back.
time.sleep(20)

after_docs = library_docs()
after_source = source_files()
after_cols = get("/api/collections")[1].get("collections", [])

SAMPLE_MARKERS = ("Storage Services", "Demand Letter", "Invoice NG-4471",
                  "Records Retention", "Engagement Letter", "Contact list",
                  "Remediation plan", "Scanned exhibit", "Scanned invoice",
                  "Receipt HV-2291", "Email chain", "File note", "Memorandum",
                  "Statement of Claim", "archive.zip", "empty-file")
survivors = [d for d in after_docs
             if any(m in d["canonical_src"] for m in SAMPLE_MARKERS)]
check("the Library is empty of every sample document", not survivors,
      f"{len(after_docs)} documents now: {[d['canonical_src'] for d in after_docs]}")
check("intake/source no longer holds the old files",
      len(after_source) <= 2,
      f"{len(after_source)} files: {[p.name for p in after_source]}")
check("the collections are cleared", not after_cols,
      str([c["name"] for c in after_cols]))
check("the sample documents did NOT come back",
      not any("Storage Services" in d["canonical_src"] or "Demand Letter" in d["canonical_src"]
              for d in after_docs),
      str([d.get("canonical_src") for d in after_docs]))

print("\n4. AND MY DROPPED FILE COMES BACK, BECAUSE IT IS STILL IN THE FOLDER")
found = None
for _ in range(25):
    for d in library_docs():
        if "My own document" in d["canonical_src"]:
            found = d
            break
    if found and found.get("doc_date"):
        break
    time.sleep(3)
check("my own document is picked up from the drop folder", found is not None)
if found:
    print(f"   read as: {found['title_guess']!r}, {found['doc_type']!r}, "
          f"{found['doc_date']!r}")
check("and my original file is untouched", mine.exists())
check("and it is the ONLY thing in the Library now",
      len(library_docs()) == 1,
      f"{len(library_docs())} documents: {[d['canonical_src'] for d in library_docs()]}")

print("\n5. THE OTHER BUTTON PUTS THE SAMPLES BACK")
s, res2 = post_json("/api/library/reset",
                    {"clear_samples": True, "restore_samples": True})
check("the restore request succeeds", s == 200 and res2.get("ok"),
      str(res2.get("error", ""))[:60])
check("and it reports the samples were rebuilt", res2.get("rebuilt") is True,
      str(res2))

s, h = get("/api/help")
check("the app is still healthy", s == 200)

print("\n6. CLEARING BY HAND IN THE FILE MANAGER IS ALSO NOTICED")
for p in source_files():
    try:
        p.unlink()
    except OSError:
        pass
print(f"   deleted {len(source_files())} files from intake/source by hand")
# The watcher should notice and re-take anything in the drop folder.
deadline = time.time() + 120
seen = False
while time.time() < deadline:
    if source_files():
        seen = True
        break
    time.sleep(4)
check("the app notices and rebuilds from the drop folder on its own", seen,
      f"{len(source_files())} files in source")
check("my original is still untouched", mine.exists())

print()
print("=" * 74)
if FAIL:
    print(f"  {len(PASS)} passed, {len(FAIL)} FAILED")
    for f in FAIL:
        print(f"    FAILED: {f}")
    print("=" * 74)
    sys.exit(1)
print(f"  ALL {len(PASS)} CHECKS PASSED")
print("=" * 74)
