"""Tests for the drop-folder watcher and bundle finalisation.

Covers the promise made to the user: copy a file into a folder and it appears in
the console; export a bundle and it leaves the console for the finished folder.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from affidavit import collections as col  # noqa: E402
from affidavit import db, watcher  # noqa: E402
from affidavit.config import load_config  # noqa: E402

ROOT = Path(__file__).resolve().parent


def make_pdf(path: Path, title: str, date_line: str) -> None:
    import pymupdf

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 90), title, fontsize=13)
    page.insert_text((72, 120), date_line, fontsize=10)
    page.insert_text((72, 150), f"Body text for {title}.", fontsize=10)
    doc.save(str(path))
    doc.close()


def main() -> int:
    failures: list[str] = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
        if not cond:
            failures.append(label)

    tmp = ROOT / "work" / "_watchtest"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    cfg = load_config(ROOT)
    cfg.source_dir = tmp / "intake" / "source"
    cfg.work_dir = tmp / "work"
    cfg.output_dir = tmp / "output"
    cfg.db_path = cfg.work_dir / "pipeline.sqlite3"
    cfg.sync_watch_dir = str(tmp / "intake" / "incoming")
    cfg.sync_reject_dir = str(tmp / "intake" / "rejected")
    cfg.sync_settle_seconds = 1.0
    cfg.sync_poll_seconds = 0.5
    cfg.ensure_dirs()

    conn = db.connect(cfg.db_path)
    db.init(conn)
    w = watcher.Watcher(conn, cfg)

    try:
        # ---------------- folders created --------------------------------
        print("--- folders ---")
        check("the drop folder exists", Path(cfg.sync_watch_dir).exists(),
              cfg.sync_watch_dir)
        check("the library folder exists", cfg.source_dir.exists())
        check("the finished folder exists", cfg.finished_dir.exists(),
              str(cfg.finished_dir))

        # ---------------- settling ---------------------------------------
        print("\n--- a file still being written is left alone ---")
        drop = Path(cfg.sync_watch_dir) / "Affidavit of Service.pdf"
        make_pdf(drop, "AFFIDAVIT OF SERVICE", "Date: 3 September 2026")
        first = w.scan_once()
        check("not taken on the first pass (still settling)", first["taken"] == 0,
              str(first))

        time.sleep(cfg.sync_settle_seconds + 0.4)
        second = w.scan_once()
        check("taken once it has settled", second["taken"] == 1, str(second))

        # ---------------- the user's file is untouched -------------------
        print("\n--- the user's file is not moved ---")
        check("the dropped file is still in the drop folder", drop.exists())
        check("a copy is in the library",
              (cfg.source_dir / drop.name).exists())
        check("it was converted",
              conn.execute("SELECT COUNT(*) c FROM documents WHERE pdf_path IS NOT NULL"
                           ).fetchone()["c"] == 1)

        # ---------------- metadata was read ------------------------------
        print("\n--- it was read, not just copied ---")
        row = conn.execute("SELECT * FROM documents").fetchone()
        check("a title was worked out", bool(row["title_guess"]), str(row["title_guess"]))
        check("the date was found", row["doc_date"] == "2026-09-03",
              str(row["doc_date"]))
        check("the type was worked out", bool(row["doc_type"]), str(row["doc_type"]))
        check("it is marked as processed", bool(row["profiled_at"]))
        check("the file was named after its contents",
              "2026-09-03" in Path(row["pdf_path"]).name,
              Path(row["pdf_path"]).name)

        # ---------------- no repeat work ---------------------------------
        print("\n--- a second pass finds nothing new ---")
        third = w.scan_once()
        check("nothing taken again", third["taken"] == 0, str(third))
        check("nothing reprocessed",
              third["converted"] == 0 and third["extracted"] == 0, str(third))

        # ---------------- a second file ----------------------------------
        # Note: scan_once takes everything that has settled, so a file left
        # settling from an earlier step may be collected here. Assertions
        # therefore check the total, not each individual pass.
        print("\n--- dropping another file ---")
        drop2 = Path(cfg.sync_watch_dir) / "Demand Letter.pdf"
        make_pdf(drop2, "DEMAND LETTER", "Date: 14 May 2024")
        w.scan_once()
        time.sleep(cfg.sync_settle_seconds + 0.4)
        w.scan_once()
        check("the library now holds two documents",
              conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"] == 2)
        check("the user's second file is still in the drop folder", drop2.exists())

        # ---------------- name collisions --------------------------------
        print("\n--- the same file name dropped twice ---")
        make_pdf(Path(cfg.sync_watch_dir) / "Demand Letter.pdf",
                 "DEMAND LETTER", "Date: 14 May 2024")
        w.scan_once()
        time.sleep(cfg.sync_settle_seconds + 0.4)
        w.scan_once()
        copies = list(cfg.source_dir.glob("Demand Letter*"))
        check("the second copy does not overwrite the first",
              len(copies) == 2, str([c.name for c in copies]))
        check("the dropped file is still there", drop2.exists())

        # ---------------- ignored files ----------------------------------
        print("\n--- temporary files are ignored ---")
        junk = Path(cfg.sync_watch_dir) / "half-downloaded.pdf.crdownload"
        junk.write_bytes(b"partial")
        check("a partial download is recognised as ignorable",
              watcher.is_ignorable(junk), junk.name)
        check("a lock file is recognised as ignorable",
              watcher.is_ignorable(Path(cfg.sync_watch_dir) / "x.lock"))
        check("a real document is not ignorable",
              not watcher.is_ignorable(drop2))
        count_before = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
        w.scan_once()
        time.sleep(cfg.sync_settle_seconds + 0.4)
        w.scan_once()
        count_after = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
        check("a partial download never becomes a document",
              count_after == count_before, f"{count_before} -> {count_after}")

        # ---------------- cloud warning ----------------------------------
        print("\n--- cloud-synced folder warning ---")
        original = cfg.sync_watch_dir
        cfg.sync_watch_dir = str(tmp / "OneDrive" / "incoming")
        Path(cfg.sync_watch_dir).mkdir(parents=True, exist_ok=True)
        w2 = watcher.Watcher(conn, cfg)
        warn = w2.check_cloud()
        check("warns when the drop folder is inside OneDrive", bool(warn), warn[:60])
        cfg.sync_watch_dir = original
        check("no warning for a local folder",
              not watcher.Watcher(conn, cfg).check_cloud())

        # ---------------- heartbeat and lock -----------------------------
        print("\n--- watcher health ---")
        status = watcher.watcher_status(conn, cfg)
        check("a heartbeat is recorded", status["ever_run"], str(status["last_heartbeat"]))
        check("it is reported as alive", status["alive"],
              f"{status['seconds_since_heartbeat']}s ago")
        check("the watch folder is reported", status["watch_dir"] == str(cfg.watch_dir))

        # A separate lock name, so this does not disturb the watcher's own lock.
        lock_name = "lock_test"
        me = watcher.Watcher(conn, cfg, lock_name=lock_name)
        check("a lock can be taken", me.acquire_lock())
        check("the same process may re-take its own lock",
              watcher.Watcher(conn, cfg, lock_name=lock_name).acquire_lock())

        # A different owner, as a second machine or process would be.
        other = watcher.Watcher(conn, cfg, lock_name=lock_name)
        other._owner = "another-pc:9999"
        check("a different watcher is refused the lock", not other.acquire_lock())

        # A stale lock must not lock everyone out for ever.
        conn.execute("UPDATE sync_state SET value=? WHERE key=?",
                     ("another-pc:9999|2000-01-01T00:00:00+00:00", lock_name))
        conn.commit()
        check("a stale lock is taken over",
              watcher.Watcher(conn, cfg, lock_name=lock_name).acquire_lock())
        me.release_lock()

        # ---------------- finalisation -----------------------------------
        print("\n--- exporting moves the bundle out of the console ---")
        ids = [r["id"] for r in conn.execute("SELECT id FROM documents ORDER BY id")]
        cid = db.create_collection(conn, "Service Bundle", "Proof of service", "jane")
        db.add_to_collection(conn, cid, ids, "jane")
        check("the collection is live before export",
              "Service Bundle" in [c["name"] for c in db.list_collections(conn)])

        result = col.export_collection(conn, cfg, cid, username="jane")
        bundle = Path(result["bundle"])
        check("it landed in the finished folder", cfg.finished_dir in bundle.parents,
              str(bundle))
        check("a COMPLETE marker was written", (bundle / "COMPLETE").exists())
        marker = json.loads((bundle / "COMPLETE").read_text())
        check("the marker records who exported it",
              marker["exported_by"] == "jane", str(marker.get("exported_by")))
        check("the marker carries a bundle hash", bool(marker.get("bundle_hash")))
        check("the marker counts the documents", marker["documents"] == len(ids),
              str(marker.get("documents")))
        check("the PDFs are numbered",
              all(p.name[:3].isdigit() for p in (bundle / "PDFs").glob("*.pdf")))

        live = [c["name"] for c in db.list_collections(conn)]
        allc = [c["name"] for c in db.list_collections(conn, include_finished=True)]
        check("it left the live list", "Service Bundle" not in live, str(live))
        check("it is still available as finished", "Service Bundle" in allc, str(allc))

        # ---------------- tamper detection -------------------------------
        print("\n--- the bundle hash detects changes ---")
        digest_a, _ = col.bundle_digest(bundle)
        check("re-hashing an unchanged bundle is stable",
              col.bundle_digest(bundle)[0] == digest_a)
        pdf = sorted((bundle / "PDFs").glob("*.pdf"))[0]
        with pdf.open("ab") as fh:
            fh.write(b"% changed")
        digest_b, _ = col.bundle_digest(bundle)
        check("modifying a document changes the hash", digest_a != digest_b)

        # ---------------- events -----------------------------------------
        print("\n--- the activity record ---")
        events = watcher.recent_events(conn, 50)
        kinds = {e["kind"] for e in events}
        check("receipts are recorded", "received" in kinds, str(sorted(kinds)))
        check("ingestion is recorded", "ingested" in kinds)
        check("processing is recorded", "processed" in kinds)

    finally:
        conn.close()
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL WATCHER CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
