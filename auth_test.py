"""Tests for authentication, attribution, concurrency and audit.

Runs the console with auth enabled against a throwaway database so it never
touches the working pipeline state.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from affidavit import auth, db, review  # noqa: E402
from affidavit.config import load_config  # noqa: E402

PORT = 8795
BASE = f"http://127.0.0.1:{PORT}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 3xx responses instead of silently following them.

    Following redirects would hide the difference between 'refused' and
    'redirected to the login page', which is exactly what we need to assert.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _request(req) -> tuple[int, dict | bytes, str | None]:
    try:
        with _OPENER.open(req, timeout=5) as resp:
            body = resp.read()
            set_cookie = resp.headers.get("Set-Cookie")
            try:
                return resp.status, json.loads(body), set_cookie
            except json.JSONDecodeError:
                return resp.status, body, set_cookie
    except urllib.error.HTTPError as exc:
        body = exc.read()
        set_cookie = exc.headers.get("Set-Cookie")
        try:
            return exc.code, json.loads(body), set_cookie
        except json.JSONDecodeError:
            return exc.code, body, set_cookie


def call(path: str, payload: dict | None = None, cookie: str | None = None,
         origin: str | None = None) -> tuple[int, dict | bytes, str | None]:
    url = BASE + path
    headers = {}
    if cookie:
        headers["Cookie"] = cookie
    if origin:
        headers["Origin"] = origin
    if payload is None:
        req = urllib.request.Request(url, headers=headers)
    else:
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    return _request(req)


def form_login(username: str, password: str) -> tuple[int, dict | bytes, str | None]:
    from urllib.parse import urlencode

    data = urlencode({"username": username, "password": password}).encode()
    req = urllib.request.Request(
        BASE + "/login", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
    )
    return _request(req)


def main() -> int:
    failures: list[str] = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
        if not cond:
            failures.append(label)

    root = Path(__file__).resolve().parent
    cfg = load_config(root)

    # Isolated workspace so the real database is untouched. Kept inside the
    # project folder rather than the system temp dir, which the sandbox may
    # not permit us to clean up.
    tmp_root = root / "work" / "_authtest"
    if tmp_root.exists():
        shutil.rmtree(tmp_root, ignore_errors=True)
    tmp_root.mkdir(parents=True, exist_ok=True)
    try:
        cfg.db_path = tmp_root / "auth_test.sqlite3"
        conn = db.connect(cfg.db_path)
        db.init(conn)
        auth.init_auth(conn)

        # Seed two documents so there is something to review.
        for i in (1, 2):
            db.upsert_document(conn, sha256=f"hash{i}", canonical_src=f"doc{i}.pdf",
                               ext=".pdf")
        conn.commit()

        # ---- account rules ------------------------------------------------
        try:
            auth.create_user(conn, "shorty", "Short", "tooshort")
            check("reject password under 10 chars", False, "no error raised")
        except ValueError:
            check("reject password under 10 chars", True)

        auth.create_user(conn, "alice", "Alice Nguyen", "correct-horse-battery", "reviewer")
        auth.create_user(conn, "bob", "Bob Okafor", "another-good-passphrase", "reviewer")
        auth.create_user(conn, "admin", "Admin", "administrator-pass-1", "admin")
        check("users created", len(auth.list_users(conn)) == 3,
              f"count={len(auth.list_users(conn))}")

        # Password must not be stored in any recoverable form.
        row = conn.execute("SELECT pw_hash, pw_salt FROM users WHERE username='alice'").fetchone()
        check("password not stored in plaintext",
              "correct-horse-battery" not in row["pw_hash"]
              and row["pw_salt"] not in row["pw_hash"])

        check("wrong password rejected",
              auth.login(conn, "alice", "wrong-password-here")[0] is None)
        check("unknown user rejected",
              auth.login(conn, "nobody", "whatever-password")[0] is None)
        check("correct password accepted",
              auth.login(conn, "alice", "correct-horse-battery")[0] is not None)

        # ---- serve with auth ----------------------------------------------
        httpd = ThreadingHTTPServer(
            ("127.0.0.1", PORT),
            review._make_handler(conn, cfg, require_auth=True, secure_cookie=False),
        )
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        time.sleep(0.5)

        try:
            # Unauthenticated access is refused.
            # A GET redirects a browser to the login page; a write is refused
            # outright. Either way, no data is served.
            status, body, _ = call("/api/documents")
            check("anonymous GET is redirected to login", status == 303, f"status={status}")

            status, body, _ = call("/api/decision",
                                   {"decisions": [{"doc_id": 1, "schedule": "A"}]})
            check("anonymous write is refused with 401", status == 401, f"status={status}")

            check("anonymous request leaks no document data",
                  b"canonical_src" not in (body if isinstance(body, bytes)
                                           else json.dumps(body).encode()))

            status, body, _ = call("/")
            check("root redirects anonymous user to login", status == 303, f"status={status}")

            status, body, _ = call("/login")
            check("login page served", status == 200 and b"password" in body)

            # Bad credentials.
            status, body, cookie = form_login("alice", "nope-nope-nope")
            check("bad login rejected", status == 401, f"status={status}")

            # Good credentials.
            status, body, cookie = form_login("alice", "correct-horse-battery")
            ok = status == 303 and cookie and "aod_session=" in cookie
            check("login sets a session cookie", bool(ok), f"status={status}")
            check("cookie is HttpOnly and SameSite=Strict",
                  bool(cookie) and "HttpOnly" in cookie and "SameSite=Strict" in cookie)
            check("cookie is NOT Secure when not behind HTTPS",
                  bool(cookie) and "Secure" not in cookie)
            alice_cookie = (cookie or "").split(";")[0]

            status, body, _ = call("/api/documents", cookie=alice_cookie)
            check("authenticated read works", status == 200 and "documents" in body)
            check("server reports the signed-in user",
                  status == 200 and body.get("me", {}).get("username") == "alice",
                  str(body.get("me") if isinstance(body, dict) else body))

            # ---- attribution cannot be forged -----------------------------
            status, body, _ = call(
                "/api/decision",
                {"decisions": [{"doc_id": 1, "schedule": "B",
                                "privilege_ground": "Solicitor-client privilege",
                                "reviewed_by": "somebody-else"}]},
                cookie=alice_cookie,
            )
            doc1 = next(d for d in body["documents"] if d["id"] == 1)
            check("reviewer is taken from the session, not the request",
                  doc1["reviewed_by"] == "alice", f"got={doc1['reviewed_by']!r}")

            # ---- concurrency warning --------------------------------------
            status, body, cookie_b = form_login("bob", "another-good-passphrase")
            bob_cookie = (cookie_b or "").split(";")[0]
            status, body, _ = call(
                "/api/decision",
                {"decisions": [{"doc_id": 1, "schedule": "A"}]},
                cookie=bob_cookie,
            )
            conflicts = body.get("conflicts", [])
            check("overlapping edit is flagged to the second reviewer",
                  any(c.get("previous_reviewer") == "alice" for c in conflicts),
                  f"conflicts={conflicts}")
            doc1 = next(d for d in body["documents"] if d["id"] == 1)
            check("second reviewer's change still applies (no deadlock)",
                  doc1["schedule"] == "A" and doc1["reviewed_by"] == "bob")

            # ---- audit trail ----------------------------------------------
            entries = auth.recent_audit(conn, 50)
            actions = [e["action"] for e in entries]
            check("audit records logins", actions.count("login") >= 2, f"{actions}")
            check("audit records failed login", "login_failed" in actions)
            check("audit records schedule changes", "schedule_set" in actions)
            check("audit attributes the schedule change to alice",
                  any(e["username"] == "alice" and e["action"] == "schedule_set"
                      for e in entries))

            # ---- CSRF ------------------------------------------------------
            status, body, _ = call(
                "/api/decision",
                {"decisions": [{"doc_id": 2, "schedule": "A"}]},
                cookie=alice_cookie,
                origin="http://evil.example.com",
            )
            check("cross-origin write refused", status == 403, f"status={status}")

            status, body, _ = call(
                "/api/decision",
                {"decisions": [{"doc_id": 2, "schedule": "A"}]},
                cookie=alice_cookie,
                origin=f"http://127.0.0.1:{PORT}",
            )
            check("same-origin write allowed", status == 200, f"status={status}")

            # ---- admin-only -----------------------------------------------
            status, body, _ = call("/api/audit", cookie=alice_cookie)
            check("non-admin cannot read the audit log", status == 403, f"status={status}")
            status, body, cookie_a = form_login("admin", "administrator-pass-1")
            admin_cookie = (cookie_a or "").split(";")[0]
            status, body, _ = call("/api/audit", cookie=admin_cookie)
            check("admin can read the audit log", status == 200 and "entries" in body)

            # ---- logout ----------------------------------------------------
            status, body, cookie = call("/logout", cookie=alice_cookie)
            check("logout clears the cookie",
                  bool(cookie) and "Max-Age=0" in cookie)
            status, body, _ = call("/api/documents", cookie=alice_cookie)
            check("session no longer valid after logout", status == 303, f"status={status}")

            # ---- disabled account ------------------------------------------
            auth.disable_user(conn, "bob")
            status, body, cookie_b2 = form_login("bob", "another-good-passphrase")
            check("disabled account cannot sign in", status == 401, f"status={status}")
            status, body, _ = call("/api/documents", cookie=bob_cookie)
            check("existing session revoked when account disabled", status == 303,
                  f"status={status}")

            # ---- expiry -----------------------------------------------------
            conn.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00'")
            conn.commit()
            status, body, _ = call("/api/documents", cookie=admin_cookie)
            check("expired session rejected", status == 303, f"status={status}")

        finally:
            httpd.shutdown()

        # ---- refuse to serve with no accounts -----------------------------
        empty_db = tmp_root / "empty.sqlite3"
        conn2 = db.connect(empty_db)
        db.init(conn2)
        auth.init_auth(conn2)
        check("no users means auth cannot start", auth.user_count(conn2) == 0)
        conn2.close()

        conn.close()
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL AUTH CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
