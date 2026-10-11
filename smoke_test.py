"""Smoke test for the review console: start it in-process and exercise the API."""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from http.server import ThreadingHTTPServer  # noqa: E402

from affidavit import db, review  # noqa: E402
from affidavit.config import load_config  # noqa: E402

PORT = 8793
BASE = f"http://127.0.0.1:{PORT}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not silently follow redirects, so status codes stay observable."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def call(path: str, payload: dict | None = None) -> tuple[int, dict]:
    url = BASE + path
    if payload is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    try:
        with _OPENER.open(req, timeout=5) as resp:
            body = resp.read()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, {"_bytes": len(body)}
    except urllib.error.HTTPError as exc:
        return exc.code, {"_error": exc.read()[:200].decode("utf-8", "replace")}


def main() -> int:
    cfg = load_config(Path(__file__).resolve().parent)
    conn = db.connect(cfg.db_path)

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), review._make_handler(conn, cfg))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.5)

    failures = 0

    status, body = call("/")
    ok = status == 200 and body.get("_bytes", 0) > 2000
    print(f"[{'PASS' if ok else 'FAIL'}] GET /            status={status} bytes={body.get('_bytes')}")
    failures += 0 if ok else 1

    status, body = call("/api/documents")
    docs = body.get("documents", [])
    ok = status == 200 and len(docs) > 0
    print(f"[{'PASS' if ok else 'FAIL'}] GET documents    status={status} count={len(docs)}")
    failures += 0 if ok else 1

    if docs:
        d = docs[0]
        missing = [k for k in ("id", "schedule", "privilege_flags", "dup_count") if k not in d]
        ok = not missing
        print(f"[{'PASS' if ok else 'FAIL'}] shape            missing={missing}")
        failures += 0 if ok else 1

    target = next((d["id"] for d in docs if d["schedule"] in ("", None)), None)
    if target is None:
        print("[SKIP] no unreviewed document to write to")
    else:
        status, body = call(
            "/api/decision",
            {
                "decisions": [
                    {
                        "doc_id": target,
                        "schedule": "B",
                        "privilege_ground": "Solicitor-client privilege",
                        "reviewed_by": "smoke-test",
                    }
                ]
            },
        )
        after = next((d for d in body.get("documents", []) if d["id"] == target), {})
        # With authentication disabled, edits are attributed to the "local"
        # stand-in rather than a client-supplied name.
        ok = (
            status == 200
            and after.get("schedule") == "B"
            and after.get("privilege_ground") == "Solicitor-client privilege"
            and after.get("reviewed_by") == "local"
        )
        print(
            f"[{'PASS' if ok else 'FAIL'}] POST decision    status={status} "
            f"id={target} schedule={after.get('schedule')!r} "
            f"ground={after.get('privilege_ground')!r}"
        )
        failures += 0 if ok else 1

        # Persistence: read it back through a fresh query.
        row = conn.execute(
            "SELECT schedule, privilege_ground, reviewed_by FROM decisions WHERE doc_id=?",
            (target,),
        ).fetchone()
        ok = row is not None and row["schedule"] == "B"
        print(f"[{'PASS' if ok else 'FAIL'}] persisted        {dict(row) if row else None}")
        failures += 0 if ok else 1

        # Idempotent re-write must not duplicate or error.
        call("/api/decision", {"decisions": [{"doc_id": target, "schedule": "A"}]})
        status, body = call("/api/decision", {"decisions": [{"doc_id": target, "description": "x"}]})
        after = next((d for d in body.get("documents", []) if d["id"] == target), {})
        ok = after.get("schedule") == "A" and after.get("description") == "x"
        print(
            f"[{'PASS' if ok else 'FAIL'}] partial update   schedule={after.get('schedule')!r} "
            f"desc={after.get('description')!r} (earlier fields preserved)"
        )
        failures += 0 if ok else 1

        # Malformed body must not crash the server.
        req = urllib.request.Request(
            BASE + "/api/decision", data=b"{not json", method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                code = resp.status
        except urllib.error.HTTPError as exc:
            code = exc.code
        status, _ = call("/api/documents")
        ok = code == 400 and status == 200
        print(f"[{'PASS' if ok else 'FAIL'}] bad json         code={code} server_alive={status == 200}")
        failures += 0 if ok else 1

    httpd.shutdown()
    conn.close()
    print(f"\n{'ALL PASSED' if failures == 0 else str(failures) + ' FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
