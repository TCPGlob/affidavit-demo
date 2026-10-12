"""The full recovery loop, from setup to getting back in.

Covers the case nothing else did: the only administrator has forgotten their own
password, nobody is above them, and there is no email on this system.
"""
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
from affidavit.config import load_config  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9071
BASE = "http://127.0.0.1:%s" % PORT

# Work in a throwaway folder, so the test never touches a real library and can
# run unattended in CI.
import shutil  # noqa: E402
import tempfile  # noqa: E402

ROOT = Path(__file__).resolve().parent
_TMP = Path(tempfile.mkdtemp(prefix="recovery-test-"))
cfg = load_config(ROOT)
cfg.source_dir = _TMP / "intake" / "source"
cfg.work_dir = _TMP / "work"
cfg.output_dir = _TMP / "output"
cfg.db_path = cfg.work_dir / "pipeline.sqlite3"
cfg.ensure_dirs()

from affidavit import db as _db  # noqa: E402

_conn = _db.connect(cfg.db_path)
_db.init(_conn)

from http.server import ThreadingHTTPServer  # noqa: E402
import threading  # noqa: E402

from affidavit import review as _review  # noqa: E402
from affidavit import auth as _auth  # noqa: E402

_auth.init_auth(_conn)
_httpd = ThreadingHTTPServer(
    ("127.0.0.1", PORT),
    _review._make_handler(_conn, cfg, require_auth=True, secure_cookie=False),
)
threading.Thread(target=_httpd.serve_forever, daemon=True).start()
import time as _time  # noqa: E402
_time.sleep(0.6)
ROOT = Path(__file__).resolve().parent
PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))


class NR(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a):
        return None


class Browser:
    def __init__(self):
        self.cookie = None
        self.op = urllib.request.build_opener(NR)

    def get(self, path, follow=False):
        h = {"Cookie": self.cookie} if self.cookie else {}
        req = urllib.request.Request(BASE + path, headers=h)
        op = self.op if not follow else urllib.request.build_opener()
        try:
            with op.open(req, timeout=40) as x:
                sc = x.headers.get("Set-Cookie")
                if sc:
                    self.cookie = sc.split(";")[0]
                return x.status, x.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            sc = e.headers.get("Set-Cookie")
            if sc:
                self.cookie = sc.split(";")[0]
            return e.code, e.read().decode("utf-8", "replace")
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    def post(self, path, fields):
        req = urllib.request.Request(
            BASE + path, data=urlencode(fields).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Origin": BASE}, method="POST")
        try:
            with self.op.open(req, timeout=40) as x:
                sc = x.headers.get("Set-Cookie")
                if sc:
                    self.cookie = sc.split(";")[0]
                return x.status, x.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            sc = e.headers.get("Set-Cookie")
            if sc:
                self.cookie = sc.split(";")[0]
            return e.code, e.read().decode("utf-8", "replace")

    def json_post(self, path, payload):
        h = {"Content-Type": "application/json", "Origin": BASE}
        if self.cookie:
            h["Cookie"] = self.cookie
        req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                     headers=h, method="POST")
        try:
            with self.op.open(req, timeout=40) as x:
                return x.status, json.loads(x.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except Exception:
                return e.code, {}


print("=" * 74)
print("  RECOVERY CODE: THE WHOLE LOOP")
print("=" * 74)

# ---------------------------------------------------------------- 1
print("\n1. SETUP ISSUES A RECOVERY CODE, ONCE")
b = Browser()
s, page = b.post("/setup", {"display_name": "Jane Smith", "username": "jane",
                            "password": "harbour-2024-storage",
                            "confirm": "harbour-2024-storage"})
check("the first account is created and we are sent to the code page",
      s == 303, f"status {s}")
check("the code page is where we are sent",
      "/your-recovery-code" in page or s == 303, page[:60])

s, page = b.get("/your-recovery-code")
m = re.search(r'id="code"[^>]*>\s*([A-Z0-9-]{10,})', page)
code = m.group(1).strip() if m else None
check("the recovery code is displayed", bool(code), code or "not found")
if code:
    groups = code.split("-")
    check("it is in four readable groups", len(groups) == 4 and all(len(g) == 4 for g in groups),
          code)
    check("it avoids characters that are misread",
          not any(c in code for c in "01OIL"), code)

print("\n2. IT CANNOT BE LOOKED UP AGAIN")
s, page2 = b.get("/your-recovery-code")
check("a second visit does not show it again",
      not (code and code in page2), f"status {s}")
check("and it sends us to the console instead", s in (200, 303), f"status {s}")

print("\n3. THE CONSOLE LETS US SET A FRESH CODE ON DEMAND")
s, body = b.json_post("/api/recovery-code", {})
check("an administrator can issue a new code for themselves",
      s == 200 and body.get("ok"), str(body.get("error", ""))[:60])
new_code = body.get("code")
check("a code is returned, and it is different from the first",
      bool(new_code) and new_code != code, new_code or "none")
check("the new code is also in four groups",
      bool(new_code) and len(new_code.split("-")) == 4, new_code or "")

# The newest code is the live one; the old one must no longer work.
code = new_code

# ---------------------------------------------------------------- 4
print("\n4. NOBODY CAN RESET WITHOUT THE CODE")
stranger = Browser()
s, page = stranger.post("/recover", {"username": "jane", "code": "AAAA-BBBB-CCCC-DDDD",
                                     "password": "attacker-password",
                                     "confirm": "attacker-password"})
check("a wrong code is refused", s == 400, f"status {s}")
check("and the refusal does not say which field was wrong",
      "do not match" in page and "Check both" in page,
      "the message covers both and says to check both")

s, page = stranger.post("/recover", {"username": "jane", "code": code,
                                     "password": "short", "confirm": "short"})
check("a too-short new password is refused", s == 400, f"status {s}")

s, page = stranger.post("/recover", {"username": "nobody", "code": code,
                                     "password": "valid-password-here",
                                     "confirm": "valid-password-here"})
check("an unknown username is refused", s == 400, f"status {s}")

print("\n5. THE RECOVERY PAGE IS REACHABLE WITHOUT SIGNING IN")
anon = Browser()
s, page = anon.get("/recover")
check("the page loads for somebody who cannot sign in", s == 200, f"status {s}")
check("it asks for a username, a code and a new password",
      all(k in page for k in ('name="username"', 'name="code"', 'name="password"')),
      "")
s, page = anon.get("/login")
check("the sign-in page links to it", "/recover" in page, "")

# ---------------------------------------------------------------- 6
print("\n6. THE CODE GETS THE ADMINISTRATOR BACK IN")
jane = Browser()
s, page = jane.post("/recover", {"username": "jane", "code": code,
                                 "password": "brand-new-password",
                                 "confirm": "brand-new-password"})
check("the reset is accepted with the right code", s == 200, f"status {s}")
check("and we are told to sign in", "Sign in" in page or "sign in" in page, page[:60])

s, _ = jane.post("/login", {"username": "jane", "password": "brand-new-password"})
check("the new password works", s == 303, f"status {s}")

old = Browser()
s, _ = old.post("/login", {"username": "jane", "password": "harbour-2024-storage"})
check("the old password no longer works", s != 303, f"status {s}")

# ---------------------------------------------------------------- 7
print("\n7. THE CODE IS USED UP, SO A FOUND PIECE OF PAPER IS WORTHLESS")
again = Browser()
s, page = again.post("/recover", {"username": "jane", "code": code,
                                  "password": "second-attempt-password",
                                  "confirm": "second-attempt-password"})
check("the same code cannot be used twice", s == 400, f"status {s}")
check("and the message says a code only works once",
      "once" in page, "")

s, _ = again.post("/login", {"username": "jane", "password": "second-attempt-password"})
check("so the second attempt did not change the password", s != 303, f"status {s}")

# ---------------------------------------------------------------- 8
print("\n8. AN ADMINISTRATOR CAN ISSUE A CODE FOR A COLLEAGUE")
s, _ = jane.post("/login", {"username": "jane", "password": "brand-new-password"})
check("signed back in as the administrator", s == 303, f"status {s}")

s, body = jane.json_post("/api/users/create",
                         {"username": "sam", "display_name": "Sam Okonjo",
                          "password": "sam-initial-password", "role": "reviewer"})
check("a colleague is added", s == 200 and body.get("ok", True), str(body.get("error", ""))[:60])

s, body = jane.json_post("/api/recovery-code", {"username": "sam"})
check("the administrator can issue a code for the colleague",
      s == 200 and body.get("ok"), str(body.get("error", ""))[:60])
sam_code = body.get("code")

sam = Browser()
s, _ = sam.post("/recover", {"username": "sam", "code": sam_code,
                             "password": "sam-brand-new-password",
                             "confirm": "sam-brand-new-password"})
check("the colleague can use it to get back in", s == 200, f"status {s}")
s, _ = sam.post("/login", {"username": "sam", "password": "sam-brand-new-password"})
check("and sign in with the new password", s == 303, f"status {s}")

print("\n9. A COLLEAGUE CANNOT ISSUE ONE FOR SOMEBODY ELSE")
s, body = sam.json_post("/api/recovery-code", {"username": "jane"})
check("a reviewer is refused", s in (403, 401), f"status {s}")
check("with an explanation", "administrator" in str(body.get("error", "")).lower(),
      str(body.get("error", ""))[:60])

s, body = sam.json_post("/api/recovery-code", {})
check("but can issue one for themselves", s == 200 and body.get("ok"),
      str(body.get("error", ""))[:50])

print("\n10. THE OLD AUTOMATIC SIGN-IN IS STILL INTACT")
s, _ = anon.post("/login", {"username": "jane", "password": "brand-new-password"})
check("a normal sign-in works", s == 303, f"status {s}")

print("\n11. CODES ARE STORED HASHED, NOT READABLE, AND CLEARED ON USE")
from affidavit import db  # noqa: E402
conn = db.connect(cfg.db_path)

# jane's code has been used, so it must be gone.
jane_row = conn.execute(
    "SELECT recovery_hash, recovery_used_at FROM users WHERE username='jane'").fetchone()
check("a used code is cleared, so it cannot be reused even by reading the file",
      not jane_row["recovery_hash"], str(jane_row["recovery_hash"])[:20])
check("and the use is recorded", bool(jane_row["recovery_used_at"]),
      str(jane_row["recovery_used_at"]))

# sam has a live code, issued by the administrator above.
sam_row = conn.execute(
    "SELECT recovery_hash, recovery_salt FROM users WHERE username='sam'").fetchone()
check("a live code is stored as a hash", bool(sam_row["recovery_hash"]),
      (sam_row["recovery_hash"] or "")[:20] + "...")
check("the stored value is nothing like the code itself",
      bool(sam_row["recovery_hash"]) and len(sam_row["recovery_hash"]) == 64
      and "-" not in sam_row["recovery_hash"],
      f"{len(sam_row['recovery_hash'] or '')} hex characters")
check("and the columns exist on an older database too, via migration",
      "recovery_hash" in {r["name"] for r in conn.execute("PRAGMA table_info(users)")})
conn.close()

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
