"""Review console: the human gate.

Serves a local-only web page where the supervising lawyer marks each document
Schedule A (produce), B (object / privilege) or C (no longer in possession).

The page markup lives in console.html so it can be edited without touching
Python. Help text comes from help.py, which is also mirrored in the README, so
the on-screen instructions cannot drift from the documentation.

The machine never writes a schedule value on its own. It may *suggest* a
privilege ground from document text, and the UI shows that suggestion clearly
labelled as unconfirmed.
"""

from __future__ import annotations

import json
import socket
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import auth, collections, db, help as help_mod
from .config import Config

CONSOLE_HTML = Path(__file__).resolve().parent / "console.html"
LOGIN_HTML = Path(__file__).resolve().parent / "login.html"
SETUP_HTML = Path(__file__).resolve().parent / "setup.html"


def _template(path: Path, fallback: bytes, error: str = "",
              marker: str = "__ERROR__") -> bytes:
    try:
        html = path.read_text(encoding="utf-8")
    except OSError:
        return fallback
    box = f'<div class="err">{error}</div>' if error else ""
    return html.replace(marker, box).encode("utf-8")


def _error_box(message: str) -> str:
    return f'<div class="err">{message}</div>'


def _console_page() -> bytes:
    try:
        return CONSOLE_HTML.read_bytes()
    except OSError:
        return (
            b"<!DOCTYPE html><html><body style='font-family:sans-serif;padding:40px'>"
            b"<h2>Review console template missing</h2>"
            b"<p>Expected to find <code>affidavit/console.html</code> next to the "
            b"pipeline code. Restore that file and restart the console.</p>"
            b"</body></html>"
        )

def fetch_documents(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT d.id, d.title_guess, d.canonical_src, d.doc_type, d.doc_date,
               d.date_source, d.page_count, d.pdf_status, d.status_detail,
               d.summary, d.privilege_flags, d.needs_ocr,
               d.ocr_status, d.ocr_confidence, d.ocr_chars,
               (SELECT COUNT(*) FROM source_files s WHERE s.doc_id = d.id) AS dup_count,
               COALESCE(dec.schedule, '')          AS schedule,
               COALESCE(dec.privilege_ground, '')  AS privilege_ground,
               COALESCE(dec.description, '')       AS description,
               COALESCE(dec.reviewed_by, '')       AS reviewed_by,
               COALESCE(dec.reviewed_at, '')       AS reviewed_at,
               COALESCE(dec.editing_by, '')        AS editing_by
        FROM documents d
        LEFT JOIN decisions dec ON dec.doc_id = d.id
        ORDER BY (d.doc_date IS NULL), d.doc_date, d.id
        """
    ).fetchall()

    out = []
    tags = db.all_tags(conn)
    memberships: dict[int, list[str]] = {}
    for row in conn.execute(
        """SELECT i.doc_id, i.collection_id, c.name
           FROM collection_items i JOIN collections c ON c.id = i.collection_id
           ORDER BY c.name"""
    ):
        memberships.setdefault(row["doc_id"], []).append(
            {"id": row["collection_id"], "name": row["name"]}
        )

    for r in rows:
        item = dict(r)
        try:
            item["privilege_flags"] = json.loads(item["privilege_flags"] or "[]")
        except json.JSONDecodeError:
            item["privilege_flags"] = []
        item["tags"] = tags.get(item["id"], {})
        cols = memberships.get(item["id"], [])
        item["collections"] = cols
        item["collection_ids"] = [c["id"] for c in cols]
        item["collection_names"] = [c["name"] for c in cols]
        item.update(_ocr_quality(item))
        out.append(item)
    return out


# Below this mean confidence, a scan's text is unreliable enough that a person
# should check it against the image before trusting a date or a total.
OCR_VERIFY_THRESHOLD = 80.0


def _ocr_quality(item: dict) -> dict:
    """Turn a stored OCR confidence into something a reviewer can act on."""
    status = item.get("ocr_status")
    conf = item.get("ocr_confidence")

    if status == "ok" and conf is not None:
        if conf >= OCR_VERIFY_THRESHOLD:
            level, label = "good", f"{conf:.0f}%"
            advice = ""
        elif conf >= 65:
            level, label = "fair", f"{conf:.0f}%"
            advice = "Read roughly - check dates and figures against the scan."
        else:
            level, label = "poor", f"{conf:.0f}%"
            advice = "Read poorly - check this document by eye before relying on it."
        return {"ocr_quality": level, "ocr_quality_label": label,
                "ocr_quality_advice": advice, "needs_verification": level != "good"}

    if status == "no_text_found":
        return {"ocr_quality": "none", "ocr_quality_label": "no text",
                "ocr_quality_advice": "Nothing readable was found. Check the image.",
                "needs_verification": True}
    if status in ("failed", "unavailable"):
        return {"ocr_quality": "failed", "ocr_quality_label": "failed",
                "ocr_quality_advice": "Reading this scan did not succeed.",
                "needs_verification": True}
    if status is None and item.get("needs_ocr"):
        return {"ocr_quality": "unread", "ocr_quality_label": "not read",
                "ocr_quality_advice": "This scan has not been read yet.",
                "needs_verification": True}
    if status is None:
        return {"ocr_quality": "text", "ocr_quality_label": "text",
                "ocr_quality_advice": "", "needs_verification": False}
    return {"ocr_quality": "known", "ocr_quality_label": str(status),
            "ocr_quality_advice": "", "needs_verification": False}


# ---------------------------------------------------------------- handler

class _Ctx:
    """Shared, immutable per-server context."""

    def __init__(self, cfg: Config, require_auth: bool, secure_cookie: bool):
        self.cfg = cfg
        self.require_auth = require_auth
        self.secure_cookie = secure_cookie
        # Where the settings file lives, so a console change can be saved.
        # The source folder sits inside the project root.
        try:
            self.root = cfg.source_dir.resolve().parent.parent
        except (AttributeError, OSError):
            self.root = Path(".").resolve()


def _cookie_token(header: str | None) -> str | None:
    if not header:
        return None
    for part in header.split(";"):
        name, _, value = part.strip().partition("=")
        if name == auth.COOKIE_NAME and value:
            return value
    return None


def _login_page(error: str = "") -> bytes:
    fallback = ("<!DOCTYPE html><html><body style='font-family:sans-serif;padding:40px'>"
                "<h2>Sign in</h2><form method='POST' action='/login'>"
                "<p><input name='username' placeholder='username'></p>"
                "<p><input name='password' type='password' placeholder='password'></p>"
                "<button>Sign in</button></form>__ERROR__</body></html>").encode()
    return _template(LOGIN_HTML, fallback, error)


def _setup_page(error: str = "") -> bytes:
    fallback = ("<!DOCTYPE html><html><body style='font-family:sans-serif;padding:40px'>"
                "<h2>Set up the first account</h2>"
                "<form method='POST' action='/setup'>"
                "<p><input name='display_name' placeholder='Your name'></p>"
                "<p><input name='username' placeholder='username'></p>"
                "<p><input name='password' type='password' placeholder='password'></p>"
                "<p><input name='confirm' type='password' placeholder='confirm password'></p>"
                "<button>Create account</button></form>__ERROR__</body></html>").encode()
    return _template(SETUP_HTML, fallback, error)


def _make_handler(conn, cfg: Config, require_auth: bool = False,
                  secure_cookie: bool = False):
    """Build a request handler.

    The enclosing `conn` is unused for queries: the console is threaded, and a
    sqlite3 connection may only be used on the thread that created it. Each
    request opens its own connection, guarded by a lock so concurrent reviewers
    cannot lose a decision.
    """
    import threading

    lock = threading.Lock()
    ctx = _Ctx(cfg, require_auth, secure_cookie)

    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.0 closes the connection after each response. With HTTP/1.1 a
        # bodyless redirect (303 with Content-Length: 0) leaves the client
        # waiting for a response that never completes, so keep-alive is more
        # trouble than it is worth for a local review console.
        protocol_version = "HTTP/1.0"

        def log_message(self, *args):  # keep the console quiet
            pass

        # ---------------- plumbing ----------------
        def _send(self, code: int, body: bytes, ctype: str,
                  extra: list[tuple[str, str]] | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            for k, v in (extra or []):
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

        def _redirect(self, location: str, cookie: str | None = None) -> None:
            extra = [("Location", location)]
            if cookie:
                extra.append(("Set-Cookie", cookie))
            self._send(303, b"", "text/plain", extra)

        def _cookie_header(self, token: str, max_age: int) -> str:
            bits = [
                f"{auth.COOKIE_NAME}={token}",
                "Path=/", "HttpOnly", "SameSite=Strict", f"Max-Age={max_age}",
            ]
            if ctx.secure_cookie:
                bits.append("Secure")
            return "; ".join(bits)

        def _clear_cookie_header(self) -> str:
            bits = [f"{auth.COOKIE_NAME}=", "Path=/", "HttpOnly",
                    "SameSite=Strict", "Max-Age=0"]
            if ctx.secure_cookie:
                bits.append("Secure")
            return "; ".join(bits)

        def _origin_ok(self) -> bool:
            """Reject cross-site state changes (defence in depth over SameSite)."""
            origin = self.headers.get("Origin")
            if not origin:
                return True  # non-browser client (curl, tests)
            host = self.headers.get("Host", "")
            return origin.split("//", 1)[-1] == host

        def _current_user(self, c):
            if not ctx.require_auth:
                return None
            return auth.resolve_session(c, _cookie_token(self.headers.get("Cookie")))

        def _effective_user(self, c):
            """The identity writes are attributed to.

            With authentication disabled there is no real account, so local
            edits are attributed to a clearly-named stand-in rather than being
            left blank or, worse, taken from the request body.
            """
            if not ctx.require_auth:
                return auth.SessionUser(0, "local", "Local user (no sign-in)", "admin")
            return self._current_user(c)

        def _require_user(self, c):
            """Return the signed-in user, or send a redirect/401 and return None.

            When authentication is disabled this returns None immediately and
            the caller proceeds: no user, but no gate either.
            """
            if not ctx.require_auth:
                return None
            if auth.user_count(c) == 0:
                # Nothing is set up yet; send them to the first-run page rather
                # than a login form with no accounts behind it.
                if self.command == "GET":
                    self._redirect("/setup")
                else:
                    self._json({"error": "not set up yet", "setup": True}, 401)
                return None
            user = self._current_user(c)
            if user is not None:
                return user
            if self.command == "GET":
                self._redirect("/login")
            else:
                self._json({"error": "not signed in"}, 401)
            return None

        def _blocked(self, user) -> bool:
            """True when access must be refused for this caller."""
            return ctx.require_auth and user is None

        # ---------------- GET ----------------
        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            try:
                with lock:
                    with db.connect_for_thread(cfg.db_path) as c:
                        if path == "/login":
                            if not ctx.require_auth:
                                self._redirect("/")
                                return
                            if auth.user_count(c) == 0:
                                self._redirect("/setup")
                                return
                            self._send(200, _login_page(), "text/html; charset=utf-8")
                            return
                        if path == "/setup":
                            if not ctx.require_auth:
                                self._redirect("/")
                                return
                            if auth.user_count(c) > 0:
                                # Setup is a one-time door; close it for good.
                                self._redirect("/login")
                                return
                            self._send(200, _setup_page(), "text/html; charset=utf-8")
                            return
                        if path == "/logout":
                            auth.logout(c, _cookie_token(self.headers.get("Cookie")))
                            self._redirect("/login", self._clear_cookie_header())
                            return
                        if path == "/healthz":
                            self._json({"ok": True})
                            return

                        user = self._require_user(c)
                        if self._blocked(user):
                            return

                        if path in ("/", "/index.html"):
                            self._send(200, _console_page(), "text/html; charset=utf-8")
                        elif path == "/api/help":
                            self._json(help_mod.as_dict())
                        elif path == "/api/documents":
                            self._json({
                                "documents": fetch_documents(c),
                                "me": ({"username": user.username,
                                        "display_name": user.display_name,
                                        "role": user.role} if user else None),
                                "auth": ctx.require_auth,
                            })
                        elif path == "/api/audit":
                            if user is not None and not user.is_admin:
                                self._json({"error": "admin only"}, 403)
                            else:
                                self._json({"entries": auth.recent_audit(c)})
                        elif path == "/api/team":
                            self._handle_team(c, user)
                        elif path == "/api/users":
                            self._handle_users_list(c, user)
                        elif path == "/api/ocr":
                            self._json(self._ocr_summary(c))
                        elif path == "/api/collections":
                            self._json({
                                "collections": db.list_collections(c),
                                "finished": db.list_collections(c, include_finished=True),
                                "collections_dir": str(cfg.collections_dir),
                                "finished_dir": str(cfg.finished_dir),
                            })
                        elif path == "/api/sync":
                            from . import watcher as watcher_mod
                            self._json({
                                "status": watcher_mod.watcher_status(c, cfg),
                                "events": watcher_mod.recent_events(c, limit=40),
                            })
                        elif path.startswith("/api/collections/"):
                            try:
                                cid = int(path.rsplit("/", 1)[-1])
                            except ValueError:
                                self._send(404, b"not found", "text/plain")
                                return
                            self._handle_collection_detail(c, cid)
                        else:
                            self._send(404, b"not found", "text/plain")
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, 500)

        # ---------------- POST ----------------
        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if not self._origin_ok():
                self._json({"error": "cross-origin request refused"}, 403)
                return

            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""

            try:
                with lock:
                    with db.connect_for_thread(cfg.db_path) as c:
                        if path == "/login":
                            self._handle_login(c, raw)
                            return
                        if path == "/setup":
                            self._handle_setup(c, raw)
                            return

                        user = self._require_user(c)
                        if self._blocked(user):
                            return
                        actor = user or self._effective_user(c)
                        if path == "/api/decision":
                            self._handle_decision(c, actor, raw)
                        elif path == "/api/claim":
                            self._handle_claim(c, actor, raw)
                        elif path == "/api/collections/create":
                            self._handle_collection_create(c, actor, raw)
                        elif path == "/api/collections/action":
                            self._handle_collection_action(c, actor, raw)
                        elif path == "/api/collections/export":
                            self._handle_export(c, actor, raw)
                        elif path == "/api/ocr":
                            self._handle_ocr_run(c, actor, raw)
                        elif path == "/api/library/reset":
                            self._handle_library_reset(c, actor, raw)
                        elif path == "/api/watchdir":
                            self._handle_set_watch_dir(c, actor, raw)
                        elif path == "/api/pickfolder":
                            self._handle_pick_folder(c, actor)
                        elif path == "/api/users/create":
                            self._handle_user_create(c, actor, raw)
                        elif path == "/api/users/update":
                            self._handle_user_update(c, actor, raw)
                        elif path == "/api/users/password":
                            self._handle_change_password(c, actor, raw)
                        else:
                            self._send(404, b"not found", "text/plain")
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, 500)

        def _handle_library_reset(self, c, actor: str | None, raw: bytes) -> None:
            """Clear the record, for replacing the sample documents with real ones.

            Only generated material is removed. A document the user supplied is
            never deleted by a button press, so the caller has to say explicitly
            that it is clearing the sample set.
            """
            try:
                body = json.loads(raw or b"{}")
            except (json.JSONDecodeError, TypeError):
                body = {}

            if not self._require_admin(c, actor):
                return

            include_source = bool(body.get("clear_samples"))
            result = {"removed": 0}
            if include_source:
                result = db.reset_library(c, ctx.cfg)
            else:
                db.reset(c)
                c.commit()
                import shutil

                for d in (ctx.cfg.work_dir / "normalized", ctx.cfg.work_dir / "ocr"):
                    shutil.rmtree(d, ignore_errors=True)

            # The watcher has its own memory of what it has handled. Clearing the
            # library is meaningless to it otherwise, and files already sitting
            # in the drop folder would sit there for good.
            from . import watcher as watcher_mod

            forgot = watcher_mod.forget_tracked_files()
            result["watcher_notified"] = forgot

            auth.audit(c, actor, None, "library_reset",
                       f"clear_samples={include_source} removed={result['removed']}")
            self._json({"ok": True, **result})

        def _handle_set_watch_dir(self, c, actor: str | None, raw: bytes) -> None:
            """Point the watched folder at a shared or synced folder.

            A team that all drop documents into one shared folder needs the
            watcher to look there instead of the local default. The setting is
            written to the config file so it survives a restart.
            """
            from . import config as config_mod
            from . import watcher as watcher_mod

            try:
                body = json.loads(raw or b"{}")
            except (json.JSONDecodeError, TypeError):
                body = {}

            if not self._require_admin(c, actor):
                return

            ok, detail = config_mod.set_watch_dir(ctx.cfg, body.get("folder", ""))
            if not ok:
                self._json({"error": detail}, 400)
                return

            saved = config_mod.save_config(ctx.cfg, ctx.root)
            ctx.cfg.ensure_dirs()

            # The running watcher reads its folder from the config object, which
            # is the one just changed, so it follows on its next pass with no
            # restart. Its status row is updated so the panel shows the new path
            # immediately rather than one poll later.
            try:
                c.execute(
                    "UPDATE sync_state SET value=? WHERE key=?",
                    (json.dumps({"watch_dir": str(ctx.cfg.watch_dir)}),
                     "watcher_display"),
                )
                c.commit()
            except Exception:  # noqa: BLE001
                pass

            cloud = watcher_mod.looks_like_cloud_folder(ctx.cfg.watch_dir)
            auth.audit(c, actor, None, "watch_dir_set", detail)
            self._json({
                "ok": True, "folder": detail, "saved_to": str(saved),
                "cloud_warning": cloud,
            })

        def _handle_pick_folder(self, c, actor: str | None) -> None:
            """Open a real folder chooser on the computer running this app.

            Much better than asking a non-technical user to type a UNC path.

            Only meaningful when the browser is on the same machine. The server
            binds 0.0.0.0 so colleagues can connect, and a dialog cannot appear
            on somebody else's screen, so a remote request is refused with an
            explanation rather than silently doing nothing.
            """
            import platform
            import subprocess
            import tempfile

            if not self._require_admin(c, actor):
                return

            client = self.client_address[0] if self.client_address else ""
            if client not in ("127.0.0.1", "::1", "localhost"):
                self._json({
                    "error": "The folder chooser only works on the computer running "
                             "this app. A dialog cannot open on someone else's screen, "
                             "so type the path instead.",
                }, 400)
                return

            system = platform.system()
            try:
                if system == "Windows":
                    script = (
                        "Add-Type -AssemblyName System.Windows.Forms | Out-Null\n"
                        "$d = New-Object System.Windows.Forms.FolderBrowserDialog\n"
                        "$d.Description = 'Choose the folder to watch for documents'\n"
                        "$d.ShowNewFolderButton = $true\n"
                        "if ($d.ShowDialog() -eq 'OK') { "
                        "[Console]::Out.Write($d.SelectedPath) }\n"
                    )
                    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False,
                                                     encoding="utf-8") as fh:
                        fh.write(script)
                        script_path = fh.name
                    try:
                        proc = subprocess.run(
                            ["powershell", "-NoProfile", "-STA",
                             "-ExecutionPolicy", "Bypass", "-File", script_path],
                            capture_output=True, text=True, timeout=300,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                    finally:
                        try:
                            Path(script_path).unlink()
                        except OSError:
                            pass
                elif system == "Darwin":
                    proc = subprocess.run(
                        ["osascript", "-e",
                         'POSIX path of (choose folder with prompt '
                         '"Choose the folder to watch for documents")'],
                        capture_output=True, text=True, timeout=300)
                else:
                    # No dependable dialog across Linux desktops, so ask the
                    # browser to accept a typed path rather than fail.
                    self._json({"error": "This system has no folder chooser here. "
                                         "Type the path instead."}, 400)
                    return
            except subprocess.TimeoutExpired:
                self._json({"error": "The folder chooser was left open and timed out."}, 400)
                return
            except FileNotFoundError:
                self._json({"error": "The folder chooser is not available on this "
                                     "computer. Type the path instead."}, 400)
                return

            picked = (proc.stdout or "").strip()
            if not picked:
                self._json({"ok": False, "cancelled": True})
                return
            self._json({"ok": True, "folder": picked})

        def _handle_login(self, c, raw: bytes) -> None:
            from urllib.parse import parse_qs

            form = parse_qs(raw.decode("utf-8", "replace"))
            username = (form.get("username") or [""])[0]
            password = (form.get("password") or [""])[0]

            token, user = auth.login(c, username, password,
                                     self.headers.get("User-Agent", ""))
            if user is None:
                auth.audit(c, username or "(blank)", None, "login_failed", "")
                self._send(401, _login_page("Incorrect username or password."),
                           "text/html; charset=utf-8")
                return
            auth.audit(c, user.username, None, "login", "")
            self._redirect("/", self._cookie_header(token, auth.SESSION_HOURS * 3600))

        def _read_json(self, raw: bytes) -> dict | None:
            try:
                payload = json.loads(raw or b"{}")
                return payload if isinstance(payload, dict) else None
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None

        def _ocr_summary(self, c) -> dict:
            from . import ocr as ocr_mod

            tool = ocr_mod.find_tesseract()
            rows = c.execute(
                """SELECT COALESCE(ocr_status,'pending') s, COUNT(*) n
                   FROM documents WHERE pdf_path IS NOT NULL GROUP BY s"""
            ).fetchall()
            counts = {r["s"]: r["n"] for r in rows}
            unread = c.execute(
                "SELECT COUNT(*) n FROM documents WHERE needs_ocr=1"
            ).fetchone()["n"]
            chars = c.execute(
                "SELECT COALESCE(SUM(ocr_chars),0) n FROM documents"
            ).fetchone()["n"]
            return {
                "engine_available": tool.available,
                "engine": tool.version,
                "languages": tool.languages,
                "default_language": cfg.ocr_lang,
                "unread": unread,
                "read": counts.get("ok", 0),
                "no_text": counts.get("no_text_found", 0),
                "failed": counts.get("failed", 0) + counts.get("unavailable", 0),
                "characters": chars,
            }

        def _handle_ocr_run(self, c, user, raw: bytes) -> None:
            payload = self._read_json(raw) or {}
            who = user.username if user else "local"
            from . import ocr as ocr_mod
            from . import pipeline as pipeline_mod

            tool = ocr_mod.find_tesseract()
            if not tool.available:
                self._json({
                    "error": "Tesseract is not installed on this machine.",
                    "hint": "winget install UB-Mannheim.TesseractOCR",
                    "ocr": self._ocr_summary(c),
                }, 400)
                return

            pending = c.execute(
                "SELECT COUNT(*) n FROM documents WHERE pdf_path IS NOT NULL "
                "AND needs_ocr=1 AND (ocr_status IS NULL "
                "OR ocr_status IN ('failed','no_text_found'))"
            ).fetchone()["n"]
            if payload.get("force") or pending:
                stats = pipeline_mod.run_ocr_stage(c, cfg, {},
                                                   force=bool(payload.get("force")))
                auth.audit(c, who, None, "ocr_run",
                           f"read={stats['succeeded']} empty={stats['empty']} "
                           f"failed={stats['failed']}")
            else:
                stats = {"processed": 0, "succeeded": 0, "empty": 0,
                         "failed": 0, "chars": 0}
            self._json({"ok": True, "stats": stats,
                        "ocr": self._ocr_summary(c),
                        "documents": fetch_documents(c)})

        def _handle_setup(self, c, raw: bytes) -> None:
            """Create the very first account, from the browser.

            Only possible while the instance has no users at all, so this cannot
            be used to add accounts later.
            """
            from urllib.parse import parse_qs

            if auth.user_count(c) > 0:
                self._redirect("/login")
                return

            form = parse_qs(raw.decode("utf-8", "replace"))
            username = (form.get("username") or [""])[0].strip().lower()
            display = (form.get("display_name") or [""])[0].strip()
            password = (form.get("password") or [""])[0]
            confirm = (form.get("confirm") or [""])[0]

            def fail(message: str) -> None:
                self._send(400, _setup_page(message), "text/html; charset=utf-8")

            if not username or not display:
                return fail("Please fill in both your name and a username.")
            if password != confirm:
                return fail("The two passwords do not match.")
            if len(password) < 10:
                return fail("The password must be at least 10 characters.")
            try:
                auth.create_user(c, username, display, password, "admin")
            except ValueError as exc:
                return fail(str(exc))

            auth.audit(c, username, None, "account_created", "first account (administrator)")
            token, user = auth.login(c, username, password,
                                     self.headers.get("User-Agent", ""))
            if user is None:
                return fail("Account created, but sign-in failed. Try signing in.")
            self._redirect("/", self._cookie_header(token, auth.SESSION_HOURS * 3600))

        def _require_admin(self, c, user) -> bool:
            """Guard for account management. Sends its own error response."""
            # Check the server's mode, not just the user object: with sign-in
            # off the stand-in identity carries the admin role, so relying on
            # the role alone would let accounts be created on an instance where
            # nobody signs in and every action is attributed to "local".
            if not ctx.require_auth:
                self._json({"error": "Sign-in is switched off, so account "
                                     "management is unavailable. Start the app "
                                     "with --users (or start-windows.bat) to give "
                                     "each person their own sign-in.",
                            "auth_disabled": True}, 400)
                return False
            if user is None:
                self._json({"error": "Not signed in."}, 401)
                return False
            if not user.is_admin:
                self._json({"error": "Only an administrator can manage accounts."}, 403)
                return False
            return True

        def _handle_users_list(self, c, user) -> None:
            if not self._require_admin(c, user):
                return
            self._json({"users": auth.list_users(c),
                        "me": {"username": user.username, "role": user.role}})

        def _handle_user_create(self, c, user, raw: bytes) -> None:
            # _require_admin sends its own response; we must stop here or the
            # account would be created despite the refusal.
            if not self._require_admin(c, user):
                return
            payload = self._read_json(raw)
            if payload is None:
                self._json({"error": "bad json"}, 400)
                return

            username = (payload.get("username") or "").strip()
            role = (payload.get("role") or "reviewer").strip().lower()
            if role not in auth.ROLES:
                self._json({"error": f"Unknown role '{role}'."}, 400)
                return
            if not username:
                self._json({"error": "A username is required."}, 400)
                return

            try:
                auth.create_user(
                    c, username, payload.get("display_name", ""),
                    payload.get("password", ""), role,
                )
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            auth.audit(c, user.username, None, "account_created", username)
            self._json({"ok": True, "users": auth.list_users(c)})

        def _handle_user_update(self, c, user, raw: bytes) -> None:
            if not self._require_admin(c, user):
                return
            payload = self._read_json(raw)
            if payload is None:
                self._json({"error": "bad json"}, 400)
                return
            target = (payload.get("username") or "").strip().lower()
            if not target:
                self._json({"error": "username is required"}, 400)
                return

            action = payload.get("action", "")
            if action == "reset_password":
                try:
                    ok = auth.set_password(c, target, payload.get("password", ""))
                except ValueError as exc:
                    self._json({"error": str(exc)}, 400)
                    return
                if not ok:
                    self._json({"error": f"No account called '{target}'."}, 404)
                    return
                auth.audit(c, user.username, None, "password_reset", target)
            elif action == "disable":
                if target == user.username:
                    self._json({"error": "You cannot disable your own account."}, 400)
                    return
                auth.disable_user(c, target, True)
                auth.audit(c, user.username, None, "account_disabled", target)
            elif action == "enable":
                auth.disable_user(c, target, False)
                auth.audit(c, user.username, None, "account_enabled", target)
            else:
                self._json({"error": f"unknown action '{action}'"}, 400)
                return

            self._json({"ok": True, "users": auth.list_users(c)})

        def _handle_change_password(self, c, user, raw: bytes) -> None:
            """A user changing their own password. Requires the current one."""
            if not ctx.require_auth or user is None:
                self._json({"error": "Sign-in is switched off, so there is no "
                                     "password to change.", "auth_disabled": True}, 400)
                return
            payload = self._read_json(raw)
            if payload is None:
                self._json({"error": "bad json"}, 400)
                return

            row = c.execute("SELECT pw_salt, pw_hash, iterations FROM users WHERE username=?",
                            (user.username,)).fetchone()
            if row is None or not auth.verify_password(
                    payload.get("current_password", ""), row["pw_salt"],
                    row["pw_hash"], row["iterations"]):
                auth.audit(c, user.username, None, "password_change_failed", "")
                self._json({"error": "That is not your current password."}, 403)
                return
            try:
                auth.set_password(c, user.username, payload.get("new_password", ""))
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            auth.audit(c, user.username, None, "password_changed", "")
            self._json({"ok": True})

        def _handle_team(self, c, user) -> None:
            """Who is on the team and what they have been doing.

            Deliberately readable by every signed-in user, not just admins:
            on a shared pool of collections, knowing who else is working and on
            what is the difference between collaboration and collision.
            """
            if not ctx.require_auth:
                self._json({
                    "auth_enabled": False,
                    "me": None,
                    "users": [],
                    "active": [],
                    "activity": auth.activity_feed(c, limit=25),
                    "note": ("Sign-in is switched off, so edits are recorded "
                             "against 'local' rather than a person. Start the "
                             "console with --require-auth to record who did what."),
                })
                return
            self._json({
                "auth_enabled": True,
                "me": ({"username": user.username, "display_name": user.display_name,
                        "role": user.role} if user else None),
                "users": auth.list_users(c),
                "active": auth.active_users(c),
                "activity": auth.activity_feed(c, limit=25),
                "note": "",
            })

        def _handle_collections_get(self, c) -> None:
            self._json({"collections": db.list_collections(c)})

        def _handle_collection_detail(self, c, collection_id: int) -> None:
            collection = db.get_collection(c, collection_id)
            if collection is None:
                self._json({"error": "no such collection"}, 404)
                return
            items = db.collection_items(c, collection_id)
            for it in items:
                it["tags"] = db.tags_for(c, it["id"])
            self._json({
                "collection": collection,
                "items": items,
                "contents": [str(p) for p in
                             sorted((Path(collection["export_path"]) / "PDFs").glob("*.pdf"))
                             ] if collection.get("export_path")
                and (Path(collection["export_path"]) / "PDFs").exists() else [],
            })

        def _handle_collection_create(self, c, user, raw: bytes) -> None:
            payload = self._read_json(raw)
            if payload is None:
                self._json({"error": "bad json"}, 400)
                return
            try:
                cid = db.create_collection(
                    c, payload.get("name", ""), payload.get("description", ""),
                    user.username if user else "local")
            except db.CollectionError as exc:
                self._json({"error": str(exc)}, 400)
                return
            auth.audit(c, user.username if user else "local", None,
                       "collection_created", payload.get("name", ""))
            self._json({"ok": True, "collection_id": cid,
                        "collections": db.list_collections(c)})

        def _handle_collection_action(self, c, user, raw: bytes) -> None:
            payload = self._read_json(raw)
            if payload is None:
                self._json({"error": "bad json"}, 400)
                return
            who = user.username if user else "local"
            action = payload.get("action", "")
            cid = payload.get("collection_id")
            doc_ids = [d for d in payload.get("doc_ids", []) if isinstance(d, int)]

            # Tagging a document is not a collection operation, so it needs no
            # collection id. Everything else does.
            if action != "tag" and not isinstance(cid, int):
                self._json({"error": "collection_id is required"}, 400)
                return

            try:
                if action == "add":
                    n = db.add_to_collection(c, cid, doc_ids, who)
                    auth.audit(c, who, None, "collection_add",
                               f"{n} document(s) -> {cid}")
                elif action == "remove":
                    n = db.remove_from_collection(c, cid, doc_ids)
                    auth.audit(c, who, None, "collection_remove",
                               f"{n} document(s) <- {cid}")
                elif action == "rename":
                    db.set_collection_fields(
                        c, cid, name=payload.get("name", ""),
                        expected_version=payload.get("expected_version"))
                elif action == "describe":
                    db.set_collection_fields(
                        c, cid, description=payload.get("description", ""),
                        expected_version=payload.get("expected_version"))
                elif action == "delete":
                    db.delete_collection(c, cid)
                    auth.audit(c, who, None, "collection_deleted", str(cid))
                elif action == "move":
                    doc_id = payload.get("doc_id")
                    if isinstance(doc_id, int):
                        db.move_item(c, cid, doc_id, int(payload.get("direction", 0)))
                elif action == "reorder":
                    db.reorder_collection(c, cid, doc_ids)
                elif action == "name_item":
                    doc_id = payload.get("doc_id")
                    if isinstance(doc_id, int):
                        db.set_item_field(c, cid, doc_id, "display_name",
                                          payload.get("display_name", ""),
                                          expected_version=payload.get("expected_version"))
                elif action == "note_item":
                    doc_id = payload.get("doc_id")
                    if isinstance(doc_id, int):
                        db.set_item_field(c, cid, doc_id, "note",
                                          payload.get("note", ""),
                                          expected_version=payload.get("expected_version"))
                elif action == "tag":
                    doc_id = payload.get("doc_id")
                    if isinstance(doc_id, int):
                        db.set_tags(c, doc_id, {payload.get("key", "tag"):
                                                payload.get("value", "")})
                else:
                    self._json({"error": f"unknown action '{action}'"}, 400)
                    return
            except db.ConflictError as exc:
                # 409 means "your copy is stale". The current value is returned
                # so the user can decide rather than silently losing their typing.
                self._json({"error": str(exc), "conflict": True,
                            "current": exc.current}, 409)
                return
            except db.CollectionError as exc:
                self._json({"error": str(exc)}, 400)
                return

            self._json({"ok": True, "collections": db.list_collections(c),
                        "items": db.collection_items(c, cid) if isinstance(cid, int) else []})

        def _handle_export(self, c, user, raw: bytes) -> None:
            payload = self._read_json(raw)
            if payload is None:
                self._json({"error": "bad json"}, 400)
                return
            cid = payload.get("collection_id")
            if not isinstance(cid, int):
                self._json({"error": "collection_id is required"}, 400)
                return
            who = user.username if user else "local"
            try:
                result = collections.export_collection(c, cfg, cid, username=who)
            except db.CollectionError as exc:
                self._json({"error": str(exc)}, 400)
                return
            auth.audit(c, who, None, "collection_exported",
                       f"{result['collection']['name']} :: "
                       f"{len(result['exported'])} document(s)")
            self._json({
                "ok": True,
                "bundle": result["bundle"],
                "exported": len(result["exported"]),
                "skipped": result["skipped"],
                "pages": result["pages"],
                "ocr_flagged": len(result["ocr_flagged"]),
                "collections": db.list_collections(c),
                "files": sorted(
                    p.name for p in (Path(result["bundle"]) / "PDFs").glob("*.pdf")
                ),
                "cover_doc": next(
                    (p.name for p in Path(result["bundle"]).glob("*.docx")), ""),
            })

        def _handle_claim(self, c, user, raw: bytes) -> None:
            try:
                payload = json.loads(raw or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._json({"error": "bad json"}, 400)
                return
            doc_id = payload.get("doc_id")
            if isinstance(doc_id, int):
                db.claim_document(c, doc_id, user.username)
            self._json({"ok": True})

        def _handle_decision(self, c, user, raw: bytes) -> None:
            try:
                payload = json.loads(raw or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._json({"error": "bad json"}, 400)
                return

            allowed = {"schedule", "privilege_ground", "description", "notes"}
            conflicts: list[dict] = []
            applied = 0

            for item in payload.get("decisions", []):
                doc_id = item.get("doc_id")
                if not isinstance(doc_id, int):
                    continue
                fields = {k: v for k, v in item.items() if k in allowed}
                if not fields:
                    continue

                # Warn if someone else is mid-edit, but never block: a stale
                # lock must not be able to freeze the affidavit before a deadline.
                row = c.execute(
                    "SELECT editing_by, reviewed_by FROM decisions WHERE doc_id=?",
                    (doc_id,),
                ).fetchone()
                if row and row["editing_by"] and row["editing_by"] != user.username:
                    conflicts.append({"doc_id": doc_id, "editing_by": row["editing_by"]})
                if row and row["reviewed_by"] and row["reviewed_by"] != user.username \
                        and "schedule" in fields and fields["schedule"]:
                    conflicts.append({"doc_id": doc_id, "previous_reviewer": row["reviewed_by"]})

                # The reviewer is always the authenticated user, never a
                # client-supplied string, so attribution cannot be forged.
                fields["reviewed_by"] = user.username
                db.set_decision(c, doc_id, **fields)
                db.claim_document(c, doc_id, user.username)
                applied += 1

                if "schedule" in fields and fields["schedule"]:
                    auth.audit(c, user.username, doc_id, "schedule_set",
                               f"{fields['schedule']} :: {fields.get('privilege_ground', '')}")
                else:
                    auth.audit(c, user.username, doc_id, "field_edit",
                               ",".join(sorted(fields)))

            self._json({
                "ok": True,
                "applied": applied,
                "documents": fetch_documents(c),
                "conflicts": conflicts,
                "me": {"username": user.username, "display_name": user.display_name,
                       "role": user.role},
                "auth": ctx.require_auth,
            })

    return Handler


def serve(conn, cfg: Config, port: int = 8765, open_browser: bool = True,
          host: str = "127.0.0.1", require_auth: bool = False,
          secure_cookie: bool = False) -> None:
    if require_auth:
        auth.init_auth(conn)

    handler = _make_handler(conn, cfg, require_auth, secure_cookie)
    try:
        httpd = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        print(f"Could not bind {host}:{port} ({exc}). Try --port with another number.")
        return

    no_users = require_auth and auth.user_count(conn) == 0
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{display_host}:{port}/"

    print("=" * 66)
    print("  DOCUMENT PREPARATION CONSOLE")
    print("=" * 66)
    print(f"  {url}")

    if no_users:
        print()
        print("  FIRST RUN - no accounts yet.")
        print("  Open the address above and create your account in the browser.")
        print("  That first account is the administrator; you can add")
        print("  colleagues from inside the app afterwards.")
        print()
        print("  *** Create it before sharing this address. ***")
        print("  *** Whoever opens it first becomes the administrator. ***")
    elif require_auth:
        print(f"  {auth.user_count(conn)} account(s). Sign in to continue.")

    if host in ("0.0.0.0", "::"):
        print()
        print(f"  Listening on ALL interfaces (port {port}).")
        print(f"  Colleagues reach this at http://<this-machine-ip>:{port}/")
        if not require_auth:
            print()
            print("  *** WARNING: reachable on the network with NO sign-in. ***")
            print("  *** Anyone who can reach this port can read every document. ***")
            print("  *** Use --require-auth for anything other than a quick test. ***")
        if not secure_cookie:
            print()
            print("  NOTE: cookies are not marked Secure. Put this behind HTTPS")
            print("  (a reverse proxy) and start with --secure-cookie.")
    else:
        print("  Reachable from this computer only.")
    print(f"  Sign-in: {'required' if require_auth else 'OFF (local use only)'}")
    print("  Press Ctrl+C to stop.\n")

    if open_browser and host in ("127.0.0.1", "localhost"):
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Review console stopped.")
    finally:
        httpd.server_close()


def port_available(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0

