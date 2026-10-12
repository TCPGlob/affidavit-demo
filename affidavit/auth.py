"""Authentication, sessions and audit for the shared review console.

Local use needs no login. Shared/cloud use does, so authentication is an
opt-in mode: enable it and every request must present a valid session.

Security choices, and why:

* Passwords are stored as PBKDF2-HMAC-SHA256 with a per-user random salt and a
  high iteration count. Never plaintext, never a bare hash.
* Session tokens are 256 bits from `secrets`, stored server-side. The cookie is
  HttpOnly and SameSite=Strict, which blocks script access and cross-site
  requests carrying the cookie.
* Sessions expire. Expired rows are deleted on access.
* State-changing requests are refused if the Origin header does not match the
  host, a second line of defence against CSRF on top of SameSite.

This is deliberately dependency-free (stdlib only). It is appropriate for a
small internal team behind TLS. It is not a substitute for an identity provider
if the firm later wants SSO.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

PBKDF2_ITERATIONS = 240_000
SESSION_HOURS = 12
COOKIE_NAME = "aod_session"

ROLES = ("reviewer", "admin")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'reviewer',
    pw_salt       TEXT NOT NULL,
    pw_hash       TEXT NOT NULL,
    iterations    INTEGER NOT NULL,
    disabled      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT,
    last_login    TEXT,
    -- One-time code that gets somebody back in when they have forgotten their
    -- password. Stored hashed, like a password, and cleared once used. There is
    -- no email and no network here to send a reset link with.
    recovery_salt       TEXT,
    recovery_hash       TEXT,
    recovery_iterations INTEGER,
    recovery_used_at    TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT,
    expires_at TEXT,
    user_agent TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY,
    at        TEXT,
    username  TEXT,
    doc_id    INTEGER,
    action    TEXT,
    detail    TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_doc ON audit_log(doc_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- schema

def init_auth(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def user_count(conn: sqlite3.Connection) -> int:
    try:
        return int(conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"])
    except sqlite3.OperationalError:
        return 0


# ---------------------------------------------------------------- passwords

def hash_password(password: str, salt: str | None = None,
                  iterations: int = PBKDF2_ITERATIONS) -> tuple[str, str, int]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return salt, digest.hex(), iterations


def verify_password(password: str, salt: str, expected: str, iterations: int) -> bool:
    _, actual, _ = hash_password(password, salt, iterations)
    return hmac.compare_digest(actual, expected)


# ---------------------------------------------------------------- users

def create_user(conn: sqlite3.Connection, username: str, display_name: str,
                password: str, role: str = "reviewer") -> int:
    username = username.strip().lower()
    if not username:
        raise ValueError("username is required")
    if len(password) < 10:
        raise ValueError("password must be at least 10 characters")
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")

    salt, digest, iterations = hash_password(password)
    try:
        cur = conn.execute(
            """INSERT INTO users (username, display_name, role, pw_salt, pw_hash,
                                  iterations, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (username, display_name or username, role, salt, digest, iterations,
             utcnow().isoformat(timespec="seconds")),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"user '{username}' already exists") from exc
    conn.commit()
    return int(cur.lastrowid)


def set_password(conn: sqlite3.Connection, username: str, password: str) -> bool:
    if len(password) < 10:
        raise ValueError("password must be at least 10 characters")
    salt, digest, iterations = hash_password(password)
    cur = conn.execute(
        "UPDATE users SET pw_salt=?, pw_hash=?, iterations=? WHERE username=?",
        (salt, digest, iterations, username.strip().lower()),
    )
    conn.commit()
    return cur.rowcount > 0


# ------------------------------------------------------------- recovery code
#
# A one-time code that gets somebody back into their own account when they have
# forgotten their password, with no email and no network involved.
#
# Deliberately not a security question. Answers to those are guessable and often
# findable, and this program makes no network calls so there is nothing to send a
# reset link with. A long random code that is written down and kept somewhere
# safe is stronger than either.

# No 0/O or 1/I/L, because these get read off paper and typed by hand.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_GROUPS = 4
_CODE_GROUP_LEN = 4


def generate_recovery_code() -> str:
    """A code in four groups, so it can be read aloud and copied accurately."""
    groups = [
        "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_GROUP_LEN))
        for _ in range(_CODE_GROUPS)
    ]
    return "-".join(groups)


def normalise_recovery_code(code: str) -> str:
    """Accept it however it was typed: spaces, dashes, lower case."""
    kept = [c for c in (code or "").upper() if c.isalnum()]
    return "".join(kept)


def set_recovery_code(conn: sqlite3.Connection, username: str,
                      code: str | None = None) -> str:
    """Store a recovery code for a user, hashed like a password.

    Returns the plain code, which is the only time it exists in readable form.
    """
    code = code or generate_recovery_code()
    salt, digest, iterations = hash_password(normalise_recovery_code(code))
    conn.execute(
        "UPDATE users SET recovery_salt=?, recovery_hash=?, recovery_iterations=?, "
        "recovery_used_at=NULL WHERE username=?",
        (salt, digest, iterations, username.strip().lower()),
    )
    conn.commit()
    return code


def has_recovery_code(conn: sqlite3.Connection, username: str) -> bool:
    row = conn.execute(
        "SELECT recovery_hash FROM users WHERE username=?", (username.strip().lower(),)
    ).fetchone()
    return bool(row and row["recovery_hash"])


def verify_recovery_code(conn: sqlite3.Connection, username: str, code: str) -> bool:
    username = username.strip().lower()
    row = conn.execute(
        """SELECT recovery_salt, recovery_hash, recovery_iterations
             FROM users WHERE username=?""",
        (username,),
    ).fetchone()
    if row is None or not row["recovery_hash"]:
        # Spend the same work as a real check, so a missing code and a wrong code
        # take the same time and cannot be told apart by timing.
        hash_password("x", secrets.token_hex(16), PBKDF2_ITERATIONS)
        return False
    supplied = normalise_recovery_code(code)
    if not supplied:
        return False
    return verify_password(supplied, row["recovery_salt"], row["recovery_hash"],
                           int(row["recovery_iterations"] or PBKDF2_ITERATIONS))


def reset_with_recovery_code(conn: sqlite3.Connection, username: str,
                             code: str, new_password: str) -> tuple[bool, str]:
    """Set a new password if the recovery code is right, then burn the code.

    Returns (ok, message). The message is shown to the user, so it never says
    which of the two was wrong.
    """
    username = username.strip().lower()
    if len(new_password or "") < 10:
        return False, "The new password needs at least 10 characters."
    if not verify_recovery_code(conn, username, code):
        return False, ("That username and recovery code do not match. Check both, "
                       "and note that a code only works once.")

    set_password(conn, username, new_password)
    # One use only: the code is cleared, so a lost piece of paper cannot be
    # reused by whoever finds it.
    conn.execute(
        "UPDATE users SET recovery_hash=NULL, recovery_salt=NULL, "
        "recovery_used_at=? WHERE username=?",
        (utcnow().isoformat(timespec="seconds"), username),
    )
    conn.commit()
    audit(conn, username, None, "password_reset_with_recovery_code",
          "recovery code used, code cleared")
    return True, "Password changed. The recovery code has now been used up."


def list_users(conn: sqlite3.Connection) -> list[dict]:
    try:
        rows = conn.execute(
            """SELECT u.id, u.username, u.display_name, u.role, u.disabled,
                      u.last_login,
                      (SELECT COUNT(*) FROM decisions d WHERE d.reviewed_by = u.username
                        AND d.schedule IS NOT NULL) AS reviewed
               FROM users u ORDER BY u.username"""
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def disable_user(conn: sqlite3.Connection, username: str, disabled: bool = True) -> bool:
    cur = conn.execute(
        "UPDATE users SET disabled=? WHERE username=?",
        (1 if disabled else 0, username.strip().lower()),
    )
    if disabled:
        conn.execute(
            "DELETE FROM sessions WHERE user_id=(SELECT id FROM users WHERE username=?)",
            (username.strip().lower(),),
        )
    conn.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------- sessions

@dataclass
class SessionUser:
    id: int
    username: str
    display_name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def login(conn: sqlite3.Connection, username: str, password: str,
          user_agent: str = "") -> tuple[str, SessionUser] | tuple[None, None]:
    row = conn.execute(
        "SELECT * FROM users WHERE username=?", (username.strip().lower(),)
    ).fetchone()
    if row is None or row["disabled"]:
        # Same failure whether the user is unknown or the password is wrong.
        return None, None
    if not verify_password(password, row["pw_salt"], row["pw_hash"], row["iterations"]):
        return None, None

    token = secrets.token_urlsafe(32)
    now = utcnow()
    expires = now + timedelta(hours=SESSION_HOURS)
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at, user_agent) "
        "VALUES (?,?,?,?,?)",
        (token, row["id"], now.isoformat(timespec="seconds"),
         expires.isoformat(timespec="seconds"), user_agent[:200]),
    )
    conn.execute("UPDATE users SET last_login=? WHERE id=?",
                 (now.isoformat(timespec="seconds"), row["id"]))
    conn.commit()
    return token, SessionUser(row["id"], row["username"], row["display_name"], row["role"])


def resolve_session(conn: sqlite3.Connection, token: str | None) -> SessionUser | None:
    if not token:
        return None
    row = conn.execute(
        """SELECT u.id, u.username, u.display_name, u.role, u.disabled, s.expires_at
           FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token=?""",
        (token,),
    ).fetchone()
    if row is None:
        return None
    if row["disabled"]:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()
        return None
    try:
        expires = datetime.fromisoformat(row["expires_at"])
    except (TypeError, ValueError):
        expires = utcnow() - timedelta(seconds=1)
    if expires <= utcnow():
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()
        return None
    return SessionUser(row["id"], row["username"], row["display_name"], row["role"])


def logout(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()


def purge_expired(conn: sqlite3.Connection) -> int:
    cur = conn.execute("DELETE FROM sessions WHERE expires_at <= ?",
                       (utcnow().isoformat(timespec="seconds"),))
    conn.commit()
    return cur.rowcount


# ---------------------------------------------------------------- audit

def audit(conn: sqlite3.Connection, username: str, doc_id: int | None,
          action: str, detail: str = "") -> None:
    """Append to an immutable trail. Never raises into a request handler."""
    try:
        conn.execute(
            "INSERT INTO audit_log (at, username, doc_id, action, detail) VALUES (?,?,?,?,?)",
            (utcnow().isoformat(timespec="seconds"), username, doc_id, action, detail[:500]),
        )
        conn.commit()
    except sqlite3.Error:
        pass


def recent_audit(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    try:
        rows = conn.execute(
            """SELECT a.at, a.username, a.doc_id, a.action, a.detail,
                      d.title_guess
               FROM audit_log a LEFT JOIN documents d ON d.id = a.doc_id
               ORDER BY a.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


# Human-readable phrasing for the activity feed, so the console does not have
# to know about internal action names.
ACTION_LABELS = {
    "login": "signed in",
    "login_failed": "failed to sign in",
    "logout": "signed out",
    "collection_created": "created a collection",
    "collection_add": "added documents to a collection",
    "collection_remove": "removed documents from a collection",
    "collection_exported": "exported a bundle",
    "collection_deleted": "deleted a collection",
    "schedule_set": "set a schedule",
    "field_edit": "edited a document",
}

# Actions that are noise in a team feed.
QUIET_ACTIONS = {"login", "field_edit"}


def activity_feed(conn: sqlite3.Connection, limit: int = 40,
                  include_logins: bool = False) -> list[dict]:
    """Recent work by the team, phrased for display.

    Returns an empty list rather than raising when authentication has never been
    initialised, so the console still renders with sign-in switched off.
    """
    try:
        rows = conn.execute(
            """SELECT a.at, a.username, a.action, a.detail, a.doc_id, d.title_guess
               FROM audit_log a LEFT JOIN documents d ON d.id = a.doc_id
               ORDER BY a.id DESC LIMIT ?""",
            (limit * 3,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    out: list[dict] = []
    for r in rows:
        if r["action"] in QUIET_ACTIONS and not include_logins:
            continue
        who = r["username"] or "unknown"
        label = ACTION_LABELS.get(r["action"], r["action"].replace("_", " "))
        detail = r["detail"] or ""
        # Collection ids are noise to a reader; the name is what matters.
        if r["action"] == "collection_add" and "->" in detail:
            detail = detail.split("->")[-1].strip()
            detail = f"collection #{detail}"
        out.append({
            "at": r["at"],
            "username": who,
            "action": r["action"],
            "label": label,
            "detail": detail[:160],
            "document": r["title_guess"] or "",
        })
        if len(out) >= limit:
            break
    return out


def active_users(conn: sqlite3.Connection, within_minutes: int = 30) -> list[dict]:
    """Who currently holds a live session."""
    cutoff = (utcnow() - timedelta(minutes=within_minutes)).isoformat(timespec="seconds")
    try:
        rows = conn.execute(
            """SELECT u.username, u.display_name, u.role,
                      MAX(s.created_at) AS signed_in_at, COUNT(s.token) AS sessions
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.expires_at > ? AND s.created_at >= ?
               GROUP BY u.username, u.display_name, u.role
               ORDER BY signed_in_at DESC""",
            (utcnow().isoformat(timespec="seconds"), cutoff),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
