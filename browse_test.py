"""Verify the folder browser endpoint, which is what the Browse button calls."""
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
from affidavit.config import load_config  # noqa: E402
from affidavit import auth, db, review  # noqa: E402

ROOT = Path(__file__).resolve().parent
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9099
cfg = load_config(ROOT)
cfg.ensure_dirs()
conn = db.connect(cfg.db_path)
db.init(conn)
auth.init_auth(conn)
conn.execute("DELETE FROM users WHERE username='jane'")
conn.commit()
auth.create_user(conn, "jane", "Jane", "harbour-2024-storage", "admin")

httpd = ThreadingHTTPServer(("127.0.0.1", PORT),
                            review._make_handler(conn, cfg, require_auth=True))
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.6)


class NR(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a):
        return None


op = urllib.request.build_opener(NR)


def sign_in():
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/login",
        data=urlencode({"username": "jane", "password": "harbour-2024-storage"}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with op.open(req, timeout=20) as x:
            sc = x.headers.get("Set-Cookie")
    except urllib.error.HTTPError as e:
        sc = e.headers.get("Set-Cookie")
    return (sc or "").split(";")[0]


cookie = sign_in()
print("=" * 70)
print("  FOLDER BROWSER ENDPOINT")
print("=" * 70)

cases = ["", "C:/", "C:/Users", "C:/Windows", "Z:/nope", "pipeline.py", "C:/Program Files"]
bad = 0
for path in cases:
    url = f"http://127.0.0.1:{PORT}/api/pickfolder?path={quote(path)}"
    req = urllib.request.Request(url, headers={"Cookie": cookie})
    try:
        with op.open(req, timeout=30) as x:
            d = json.loads(x.read())
        status = x.status
    except urllib.error.HTTPError as e:
        print(f"  [FAIL] {path!r:18} status {e.code}: {e.read().decode()[:90]}")
        bad += 1
        continue
    except Exception as e:
        print(f"  [FAIL] {path!r:18} {type(e).__name__}: {e}")
        bad += 1
        continue

    okay = status == 200
    if not okay:
        bad += 1
    print(f"  [{'PASS' if okay else 'FAIL'}] {path!r:18} "
          f"folders={len(d.get('folders', [])):3}  drives={len(d.get('drives', []))}  "
          f"error={d.get('error', '')[:40]!r}")

print("\n--- the important behaviour ---")
req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/pickfolder?path=",
                             headers={"Cookie": cookie})
with op.open(req, timeout=30) as x:
    d = json.loads(x.read())
ok1 = len(d.get("drives", [])) > 0
print(f"  [{'PASS' if ok1 else 'FAIL'}] an empty path offers the drives to start from  {d.get('drives')}")
bad += 0 if ok1 else 1

req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/pickfolder?path={quote('C:/')}",
                             headers={"Cookie": cookie})
with op.open(req, timeout=30) as x:
    d = json.loads(x.read())
ok2 = len(d.get("folders", [])) > 0 and all("path" in f and "name" in f for f in d["folders"])
print(f"  [{'PASS' if ok2 else 'FAIL'}] a real folder lists its sub-folders with full paths  "
      f"{[f['name'] for f in d.get('folders', [])[:4]]}")
bad += 0 if ok2 else 1

# permissions: somebody not signed in must not get a listing
anon = urllib.request.build_opener(NR)
try:
    with anon.open(urllib.request.Request(
            f"http://127.0.0.1:{PORT}/api/pickfolder?path=C:/"), timeout=20) as x:
        ok3 = x.status in (401, 303)
        code = x.status
except urllib.error.HTTPError as e:
    ok3 = e.code in (401, 403, 303)
    code = e.code
print(f"  [{'PASS' if ok3 else 'FAIL'}] a visitor who is not signed in is refused  status {code}")
bad += 0 if ok3 else 1

print("\n--- and it is fast, so the button never appears to hang ---")
t0 = time.time()
for _ in range(5):
    with op.open(urllib.request.Request(
            f"http://127.0.0.1:{PORT}/api/pickfolder?path={quote('C:/')}",
            headers={"Cookie": cookie}), timeout=30) as x:
        x.read()
elapsed = (time.time() - t0) / 5
ok4 = elapsed < 3
print(f"  [{'PASS' if ok4 else 'FAIL'}] five listings averaged {elapsed:.2f}s")
bad += 0 if ok4 else 1

httpd.shutdown()
conn.close()
print()
print("=" * 70)
print(f"  {'ALL CHECKS PASSED' if bad == 0 else str(bad) + ' FAILED'}")
print("=" * 70)
sys.exit(1 if bad else 0)
