"""Tests for browser-based account management.

Covers the first-run setup page and the admin panel, so that a non-technical user
never needs the command line to add colleagues.
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
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))

from affidavit import auth, db, review  # noqa: E402
from affidavit.config import load_config  # noqa: E402

PORT = 8847
NOAUTH_PORT = 8849
BASE = f"http://127.0.0.1:{PORT}"
BASE_NOAUTH = f"http://127.0.0.1:{NOAUTH_PORT}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(_NoRedirect)


def _do(req) -> tuple[int, bytes, str | None]:
    try:
        with OPENER.open(req, timeout=15) as resp:
            return resp.status, resp.read(), resp.headers.get("Set-Cookie")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Set-Cookie")


def get(path: str, cookie: str | None = None, base: str = BASE):
    headers = {"Cookie": cookie} if cookie else {}
    return _do(urllib.request.Request(base + path, headers=headers))


def post_json(path: str, payload: dict, cookie: str | None = None, base: str = BASE):
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    return _do(urllib.request.Request(
        base + path, data=json.dumps(payload).encode(), headers=headers, method="POST"))


def post_form(path: str, fields: dict):
    return _do(urllib.request.Request(
        BASE + path, data=urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST"))


def main() -> int:
    failures: list[str] = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
        if not cond:
            failures.append(label)

    root = Path(__file__).resolve().parent
    cfg = load_config(root)
    tmp = root / "work" / "_usertest"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    cfg.db_path = tmp / "users.sqlite3"
    cfg.output_dir = tmp / "output"
    cfg.ensure_dirs()

    conn = db.connect(cfg.db_path)
    db.init(conn)
    auth.init_auth(conn)

    doc_id = db.upsert_document(conn, sha256="u1", canonical_src="a.pdf", ext=".pdf",
                                pdf_path=None, pdf_status="ok", title_guess="Doc A",
                                doc_type="Document")
    conn.commit()

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT),
                                review._make_handler(conn, cfg, require_auth=True))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.5)

    try:
        # ---------------- first run -------------------------------------
        print("--- first run, no accounts ---")
        status, body, _ = get("/")
        check("with no accounts the browser is sent to setup", status == 303)

        status, body, _ = get("/login")
        check("the login page redirects to setup when there is nobody to sign in as",
              status == 303)

        status, body, _ = get("/setup")
        check("the setup page is served", status == 200 and b"first" in body.lower())
        check("it warns who becomes the administrator",
              b"administrator" in body.lower())
        check("it asks for a name, username and password",
              b"display_name" in body and b"username" in body and b"password" in body)

        # Deliberately bad submissions.
        status, body, _ = post_form("/setup", {
            "display_name": "Jane", "username": "jane",
            "password": "short", "confirm": "short"})
        check("a too-short password is refused", status == 400, f"status={status}")

        status, body, _ = post_form("/setup", {
            "display_name": "Jane", "username": "jane",
            "password": "long-enough-pass", "confirm": "different-pass-x"})
        check("mismatched passwords are refused", status == 400, f"status={status}")

        status, body, _ = post_form("/setup", {
            "display_name": "", "username": "jane",
            "password": "long-enough-pass", "confirm": "long-enough-pass"})
        check("a missing name is refused", status == 400, f"status={status}")

        check("no account was created by the failed attempts",
              auth.user_count(conn) == 0, f"count={auth.user_count(conn)}")

        # The real thing.
        status, body, cookie = post_form("/setup", {
            "display_name": "Jane Smith", "username": "Jane",
            "password": "harbour-2024-storage", "confirm": "harbour-2024-storage"})
        check("setup succeeds", status == 303, f"status={status}")
        check("setup signs the new administrator in",
              bool(cookie) and "aod_session=" in cookie, str(cookie)[:60])
        admin = (cookie or "").split(";")[0]

        users = auth.list_users(conn)
        check("exactly one account exists", len(users) == 1, str(len(users)))
        check("the first account is an administrator",
              users and users[0]["role"] == "admin")
        check("the username was normalised to lowercase",
              users and users[0]["username"] == "jane")

        status, body, _ = get("/setup")
        check("setup is closed once an account exists", status == 303)

        # ---------------- signed-in console ----------------------------
        print("\n--- the console ---")
        status, body, _ = get("/api/documents", cookie=admin)
        data = json.loads(body)
        check("the administrator can read documents", status == 200)
        check("the server reports who is signed in",
              data.get("me", {}).get("username") == "jane", str(data.get("me")))

        status, body, _ = get("/api/users", cookie=admin)
        check("an administrator can list accounts", status == 200)
        check("the account list includes roles",
              all("role" in u for u in json.loads(body).get("users", [])))

        # ---------------- add a colleague ------------------------------
        print("\n--- adding a colleague from the browser ---")
        status, body, _ = post_json("/api/users/create", {
            "username": "raj", "display_name": "Raj Patel",
            "password": "storage-2024-harbour", "role": "reviewer"}, cookie=admin)
        check("an administrator can create an account", status == 200, f"status={status}")
        check("the new account appears in the list",
              any(u["username"] == "raj" for u in json.loads(body).get("users", [])))

        status, body, _ = post_json("/api/users/create", {
            "username": "raj", "display_name": "Dup",
            "password": "another-long-password", "role": "reviewer"}, cookie=admin)
        check("a duplicate username is refused", status == 400, f"status={status}")

        status, body, _ = post_json("/api/users/create", {
            "username": "weak", "display_name": "Weak",
            "password": "short", "role": "reviewer"}, cookie=admin)
        check("a short password is refused", status == 400, f"status={status}")

        # The new colleague can actually sign in.
        status, body, raj_cookie = post_form("/login", {
            "username": "raj", "password": "storage-2024-harbour"})
        check("the new colleague can sign in", status == 303 and bool(raj_cookie))
        raj = (raj_cookie or "").split(";")[0]
        status, body, _ = get("/api/documents", cookie=raj)
        check("the colleague sees the shared library", status == 200)

        # ---------------- permissions ----------------------------------
        print("\n--- who is allowed to manage accounts ---")
        status, body, _ = post_json("/api/users/create", {
            "username": "sneaky", "display_name": "S", "password": "long-enough-passx",
            "role": "admin"}, cookie=raj)
        check("a reviewer cannot create accounts", status == 403, f"status={status}")
        status, body, _ = get("/api/users", cookie=raj)
        check("a reviewer cannot list accounts", status == 403, f"status={status}")
        status, body, _ = post_json("/api/users/update",
                                    {"action": "disable", "username": "jane"}, cookie=raj)
        check("a reviewer cannot disable the administrator", status == 403,
              f"status={status}")

        # ---------------- reset, disable, re-enable --------------------
        print("\n--- reset, disable, re-enable ---")
        status, body, _ = post_json("/api/users/update", {
            "action": "reset_password", "username": "raj",
            "password": "brand-new-passphrase"}, cookie=admin)
        check("an administrator can reset a password", status == 200, f"status={status}")
        status, _, _ = post_form("/login", {"username": "raj", "password": "brand-new-passphrase"})
        check("the new password works", status == 303, f"status={status}")
        status, _, _ = post_form("/login", {"username": "raj", "password": "storage-2024-harbour"})
        check("the old password no longer works", status == 401, f"status={status}")

        status, body, _ = post_json("/api/users/update",
                                    {"action": "disable", "username": "jane"}, cookie=admin)
        check("an administrator cannot disable their own account", status == 400,
              f"status={status}")

        status, body, _ = post_json("/api/users/update",
                                    {"action": "disable", "username": "raj"}, cookie=admin)
        check("an administrator can disable someone", status == 200, f"status={status}")
        status, _, _ = post_form("/login", {"username": "raj", "password": "brand-new-passphrase"})
        check("a disabled colleague cannot sign in", status == 401, f"status={status}")
        status, _, _ = get("/api/documents", cookie=raj)
        check("a disabled colleague's open session stops working", status == 303,
              f"status={status}")

        status, body, _ = post_json("/api/users/update",
                                    {"action": "enable", "username": "raj"}, cookie=admin)
        check("an administrator can re-enable someone", status == 200, f"status={status}")
        status, _, _ = post_form("/login", {"username": "raj", "password": "brand-new-passphrase"})
        check("the re-enabled colleague can sign in again", status == 303, f"status={status}")

        # ---------------- self-service password ------------------------
        print("\n--- changing your own password ---")
        status, _, raj_cookie = post_form("/login", {
            "username": "raj", "password": "brand-new-passphrase"})
        raj = (raj_cookie or "").split(";")[0]
        status, body, _ = post_json("/api/users/password", {
            "current_password": "wrong-password", "new_password": "yet-another-passphrase"},
            cookie=raj)
        check("the wrong current password is refused", status == 403, f"status={status}")
        status, body, _ = post_json("/api/users/password", {
            "current_password": "brand-new-passphrase", "new_password": "short"},
            cookie=raj)
        check("a short new password is refused", status == 400, f"status={status}")
        status, body, _ = post_json("/api/users/password", {
            "current_password": "brand-new-passphrase", "new_password": "yet-another-passphrase"},
            cookie=raj)
        check("a colleague can change their own password", status == 200, f"status={status}")
        status, _, _ = post_form("/login", {"username": "raj", "password": "yet-another-passphrase"})
        check("the changed password works", status == 303, f"status={status}")

        # ---------------- account management is audited ----------------
        print("\n--- the trail ---")
        entries = auth.recent_audit(conn, 80)
        actions = {e["action"] for e in entries}
        check("creating an account is recorded", "account_created" in actions, str(sorted(actions)))
        check("resetting a password is recorded", "password_reset" in actions)
        check("disabling an account is recorded", "account_disabled" in actions)
        check("re-enabling an account is recorded", "account_enabled" in actions)
        check("a colleague changing their own password is recorded",
              "password_changed" in actions)

        # ---------------- sign-in switched off -------------------------
        # A separate server and port: rebinding the same port races with the
        # shutting-down listener.
        print("\n--- sign-in switched off ---")
        httpd2 = ThreadingHTTPServer(("127.0.0.1", NOAUTH_PORT),
                                     review._make_handler(conn, cfg, require_auth=False))
        threading.Thread(target=httpd2.serve_forever, daemon=True).start()
        time.sleep(0.5)
        try:
            status, body, _ = post_json("/api/users/create", {
                "username": "x", "display_name": "X", "password": "long-enough-passx"},
                base=BASE_NOAUTH)
            check("with sign-in off, account creation is refused with an explanation",
                  status == 400 and b"switched off" in body, f"status={status}")
            status, body, _ = get("/setup", base=BASE_NOAUTH)
            check("the setup page is not reachable with sign-in off", status == 303)
            status, body, _ = get("/api/team", base=BASE_NOAUTH)
            check("the team view explains that sign-in is off",
                  status == 200 and json.loads(body).get("auth_enabled") is False)
            status, body, _ = get("/api/documents", base=BASE_NOAUTH)
            check("the console still works with sign-in off", status == 200)
        finally:
            httpd2.shutdown()

    finally:
        try:
            httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass
        conn.close()
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL ACCOUNT-MANAGEMENT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
