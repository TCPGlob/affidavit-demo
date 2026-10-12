"""Folder watcher: drop a file in a folder and it appears in the console.

A user copies documents into the watch folder (locally, or through a shared
folder their cloud client already syncs). The watcher picks them up, copies them
into the library, and processes *only* the new ones, so the review list fills up
without anyone running a command.

Design notes, each for a specific reason:

* **Polling, not filesystem events.** No dependency to install, and it behaves
  predictably on locked-down machines and with cloud-synced folders, which
  deliver files in bursts and often as a temporary partial file first.
* **Settle test.** A file is only taken once its size has stopped changing for
  `sync_settle_seconds`. Copying a 200MB scan takes time; ingesting half of one
  would be worse than waiting.
* **Copy, never move, the original out of the drop folder.** The user's own
  folder stays as they left it. Deleting somebody's file is not this program's
  business, and a failed copy must not lose the only copy of a document.
* **One watcher per folder.** A lock row in the database; two watchers racing
  over the same drop folder would duplicate work.
"""

from __future__ import annotations

import os
import shutil
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .config import Config

# A drop folder inside one of these is a confidentiality problem: the document
# is being copied to a third party because of where the folder happens to live.
CLOUD_MARKERS = (
    "onedrive", "dropbox", "google drive", "googledrive", "icloud",
    "box sync", "sharepoint", "mega", "pcloud",
)

SKIP_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
SKIP_SUFFIXES = {".tmp", ".part", ".crdownload", ".lock", ".swp"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    """Content hash, so a file is recognised however it was named."""
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


# The watcher running in this process, if any. Held so that an action taken in
# the console, clearing the library for instance, can tell it to forget what it
# was tracking rather than waiting for it to notice by itself.
_running: "Watcher | None" = None


def register(watcher: "Watcher | None") -> None:
    global _running
    _running = watcher


def forget_tracked_files() -> bool:
    """Drop the pending set of the running watcher. True if there was one."""
    if _running is None:
        return False
    _running._seen.clear()
    return True


def looks_like_cloud_folder(path: Path) -> str | None:
    """Return the cloud service name if the path sits inside a synced folder."""
    try:
        text = str(path.resolve()).lower()
    except OSError:
        text = str(path).lower()
    for marker in CLOUD_MARKERS:
        if marker in text:
            return marker
    return None


def is_ignorable(path: Path) -> bool:
    name = path.name.lower()
    if name in SKIP_NAMES or name.startswith("~$") or name.startswith("."):
        return True
    return path.suffix.lower() in SKIP_SUFFIXES


@dataclass
class WatcherState:
    """What the watcher is doing, for the console to display."""

    running: bool = False
    watch_dir: str = ""
    last_scan: str = ""
    last_change: str = ""
    ingested: int = 0
    failed: int = 0
    pending: int = 0
    note: str = ""
    cloud_warning: str = ""


class Watcher:
    """Polls the drop folder and ingests anything that has settled."""

    def __init__(self, conn, cfg: Config, lock_name: str = "watcher_lock"):
        self.conn = conn
        self.cfg = cfg
        self.lock_name = lock_name
        # path -> (size, mtime_ns, first_seen_monotonic)
        self._seen: dict[Path, tuple[int, int, float]] = {}
        self._owner = f"{socket.gethostname()}:{os.getpid()}"
        self.state = WatcherState(watch_dir=str(self.watch_dir))

    # ----------------------------------------------------------- locations
    #
    # These read through to the config rather than being copied at start-up, so
    # the watched folder can be pointed at a shared drive from the console
    # without restarting the app.

    @property
    def watch_dir(self) -> Path:
        return self.cfg.watch_dir

    @property
    def source_dir(self) -> Path:
        return self.cfg.source_dir

    @property
    def reject_dir(self) -> Path:
        return self.cfg.reject_dir

    def refresh_locations(self) -> None:
        """Pick up a changed watch folder.

        The pending set is dropped, because every entry in it belongs to the
        previous folder. Files already taken are still remembered by content
        hash, so nothing is copied in twice.
        """
        self._seen.clear()
        self.state.watch_dir = str(self.watch_dir)

    # ---------------------------------------------------------------- lock

    def acquire_lock(self) -> bool:
        """Claim the watcher role. Steals a lock whose heartbeat is stale."""
        existing = self.conn.execute(
            "SELECT value FROM sync_state WHERE key=?", (self.lock_name,)
        ).fetchone()
        if existing:
            value = existing["value"] or ""
            owner, _, stamp = value.partition("|")
            if owner and owner != self._owner and self._fresh(stamp):
                return False
        self.conn.execute(
            "INSERT INTO sync_state (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (self.lock_name, f"{self._owner}|{now_iso()}"),
        )
        self.conn.commit()
        return True

    def release_lock(self) -> None:
        self.conn.execute("DELETE FROM sync_state WHERE key=?", (self.lock_name,))
        self.conn.commit()

    @staticmethod
    def _fresh(stamp: str, minutes: int = 10) -> bool:
        try:
            when = datetime.fromisoformat(stamp)
        except (TypeError, ValueError):
            return False
        age = (datetime.now(timezone.utc) - when.astimezone(timezone.utc)).total_seconds()
        return age < minutes * 60

    def heartbeat(self) -> None:
        self.conn.execute(
            "INSERT INTO sync_state (key, value) VALUES ('watcher_heartbeat',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (now_iso(),),
        )
        self.conn.execute(
            "INSERT INTO sync_state (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (self.lock_name, f"{self._owner}|{now_iso()}"),
        )
        self.conn.commit()
        self.state.last_scan = now_iso()

    # ------------------------------------------------------------- scanning

    def check_cloud(self) -> str:
        """Warn if the drop folder is inside a cloud-synced tree."""
        service = looks_like_cloud_folder(self.watch_dir)
        if service and self.cfg.sync_warn_cloud_paths:
            return (
                f"The drop folder is inside a {service.title()} sync folder. "
                "Documents placed there will be copied to that cloud service. "
                "If that is deliberate, fine - otherwise move intake/ to local "
                "storage."
            )
        return ""

    def settled(self) -> list[Path]:
        """Files that have stopped changing, ready to be taken."""
        ready: list[Path] = []
        now = time.monotonic()
        try:
            candidates = [p for p in self.watch_dir.rglob("*") if p.is_file()]
        except OSError:
            return ready

        alive: set[Path] = set()
        for path in candidates:
            if is_ignorable(path):
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            alive.add(path)
            fingerprint = (st.st_size, st.st_mtime_ns)
            previous = self._seen.get(path)

            if previous is None or previous[:2] != fingerprint:
                self._seen[path] = (fingerprint[0], fingerprint[1], now)
                continue

            if now - previous[2] >= self.cfg.sync_settle_seconds:
                ready.append(path)

        for gone in set(self._seen) - alive:
            del self._seen[gone]

        self.state.pending = len(self._seen) - len(ready)
        return ready

    # ------------------------------------------------------------ ingestion

    def _free_name(self, name: str) -> Path:
        """A name in the library that will not overwrite an existing file."""
        target = self.source_dir / name
        if not target.exists():
            return target
        stem, suffix = Path(name).stem, Path(name).suffix
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = self.source_dir / f"{stem}__{stamp}{suffix}"
        n = 2
        while candidate.exists():
            candidate = self.source_dir / f"{stem}__{stamp}-{n}{suffix}"
            n += 1
        return candidate

    def _already_taken(self, path: Path) -> bool:
        """Has this exact content already been copied in, and is that copy there?

        Read-only. Two jobs:

        A file the pipeline cannot use (a .zip, say) stays in the drop folder, so
        without a record it would be copied into the library on every scan.

        But the record is only meaningful while the library copy exists. Clearing
        the library deletes the copies, and a record without a destination would
        then refuse the file forever, leaving it stuck in the drop folder with an
        empty Library and nothing to explain why.
        """
        try:
            digest = _sha256(path)
        except OSError:
            return False

        try:
            row = self.conn.execute(
                "SELECT dest FROM sync_files WHERE sha256=?", (digest,)
            ).fetchone()
        except Exception:  # noqa: BLE001 - an old database without the column
            return False
        if row is None:
            return False

        dest = row["dest"] if "dest" in row.keys() else None
        if not dest:
            # Recorded before destinations were kept, so it cannot be trusted.
            return False
        return Path(dest).exists()

    def take(self, path: Path) -> Path | None:
        """Copy a dropped file into the library. Returns the new path.

        Returns None when this exact content has already been taken, so the
        caller knows nothing was copied.
        """
        if self._already_taken(path):
            return None

        try:
            relative_parent = path.parent.relative_to(self.watch_dir)
        except ValueError:
            relative_parent = Path(".")
        dest_dir = self.source_dir / relative_parent
        dest_dir.mkdir(parents=True, exist_ok=True)

        # A different file that happens to share the name gets a suffix rather
        # than overwriting what is already there.
        dest = dest_dir / path.name
        if dest.exists():
            dest = self._free_name(str(relative_parent / path.name))

        try:
            shutil.copy2(path, dest)
        except OSError as exc:
            self._reject(path, f"could not copy into the library: {exc}")
            return None
        self._remember(path, dest)
        return dest

    def _remember(self, path: Path, dest: Path | None = None) -> None:
        """Record a file as handled, and where its library copy went."""
        try:
            digest = _sha256(path)
        except OSError:
            return
        try:
            self.conn.execute(
                "INSERT INTO sync_files (sha256, name, dest, first_seen) "
                "VALUES (?,?,?,?) "
                "ON CONFLICT(sha256) DO UPDATE SET dest=excluded.dest, "
                "name=excluded.name",
                (digest, path.name[:200], str(dest) if dest else None, now_iso()),
            )
            self.conn.commit()
        except Exception:  # noqa: BLE001
            pass

    def _reject(self, path: Path, reason: str) -> None:
        self.state.failed += 1
        try:
            self.reject_dir.mkdir(parents=True, exist_ok=True)
            # Never move the user's file: write a note beside a copy instead.
            note = self.reject_dir / f"{path.name}.reason.txt"
            note.write_text(f"{now_iso()}\n{path}\n{reason}\n", encoding="utf-8")
        except OSError:
            pass
        self._event("rejected", f"{path.name}: {reason}", str(path))

    def _event(self, kind: str, detail: str, path: str = "") -> None:
        try:
            self.conn.execute(
                "INSERT INTO sync_events (ts, kind, detail, path) VALUES (?,?,?,?)",
                (now_iso(), kind, detail[:500], path[:500]),
            )
            self.conn.commit()
        except Exception:  # noqa: BLE001 - logging must never break the watcher
            pass

    # ----------------------------------------------------------------- loop

    def scan_once(self) -> dict:
        """One pass: take everything that has settled, then process."""
        from . import pipeline

        self.cfg.ensure_dirs()
        ready = self.settled()
        taken: list[Path] = []
        already = 0

        for path in ready:
            dest = self.take(path)
            # Drop it from the pending set either way, so a file already taken
            # is not reconsidered on every pass.
            self._seen.pop(path, None)
            if dest is not None:
                taken.append(dest)
                self.state.ingested += 1
                self._event("received", f"{path.name} -> {dest.name}", str(path))
            else:
                already += 1

        result = {"taken": len(taken), "documents": 0, "converted": 0,
                  "extracted": 0, "already_taken": already}

        if taken:
            # Register the new files, then process only what is new. Re-running
            # the whole pipeline per drop would be O(n^2).
            from .ingest import ingest as run_ingest

            run_ingest(self.conn, self.cfg)
            stats = pipeline.process_pending(self.conn, self.cfg)
            result.update(stats)
            result["documents"] = len(taken)
            self.state.last_change = now_iso()
            for dest in taken:
                self._event("ingested", dest.name, str(dest))
            self._event(
                "processed",
                f"{stats['converted']} converted, {stats['extracted']} read",
            )

        self.heartbeat()
        return result

    def run_forever(self, on_scan=None) -> None:
        """Poll until interrupted."""
        self.state.running = True
        self.state.cloud_warning = self.check_cloud()
        self._event("watcher", f"watching {self.watch_dir}")

        if not self.acquire_lock():
            self.state.running = False
            self.state.note = "Another watcher is already running for this folder."
            self._event("watcher", "not started: another watcher holds the lock")
            return

        try:
            while True:
                try:
                    result = self.scan_once()
                    if on_scan and result["taken"]:
                        on_scan(result)
                except Exception as exc:  # noqa: BLE001 - keep watching
                    self.state.note = f"{type(exc).__name__}: {exc}"
                    self._event("error", self.state.note)
                time.sleep(max(1.0, self.cfg.sync_poll_seconds))
        except KeyboardInterrupt:
            pass
        finally:
            self.state.running = False
            self._event("watcher", "stopped")
            self.release_lock()

    # ------------------------------------------------------------ reporting

    def status(self) -> dict:
        heartbeat = self.conn.execute(
            "SELECT value FROM sync_state WHERE key='watcher_heartbeat'"
        ).fetchone()
        last = heartbeat["value"] if heartbeat else ""
        age = None
        if last:
            try:
                age = int((datetime.now(timezone.utc)
                           - datetime.fromisoformat(last).astimezone(timezone.utc)
                           ).total_seconds())
            except (TypeError, ValueError):
                age = None
        return {
            "watch_dir": str(self.watch_dir),
            "running_here": self.state.running,
            "last_scan": last,
            "seconds_since_scan": age,
            "ingested": self.state.ingested,
            "pending": self.state.pending,
            "note": self.state.note,
            "cloud_warning": self.state.cloud_warning or self.check_cloud(),
        }


def watcher_status(conn, cfg: Config) -> dict:
    """Watcher health, for the console banner. Safe to call with no watcher."""
    row = conn.execute(
        "SELECT value FROM sync_state WHERE key='watcher_heartbeat'"
    ).fetchone()
    last = row["value"] if row else ""
    age = None
    if last:
        try:
            age = int((datetime.now(timezone.utc)
                       - datetime.fromisoformat(last).astimezone(timezone.utc)
                       ).total_seconds())
        except (TypeError, ValueError):
            age = None
    lock = conn.execute(
        "SELECT value FROM sync_state WHERE key='watcher_lock'"
    ).fetchone()
    return {
        "watch_dir": str(cfg.watch_dir),
        "exists": cfg.watch_dir.exists(),
        "last_heartbeat": last,
        "seconds_since_heartbeat": age,
        "alive": age is not None and age < 180,
        "ever_run": bool(last),
        "owner": (lock["value"].split("|")[0] if lock else ""),
        "cloud_warning": (looks_like_cloud_folder(cfg.watch_dir)
                          if cfg.sync_warn_cloud_paths else None),
    }


def recent_events(conn, limit: int = 60) -> list[dict]:
    try:
        rows = conn.execute(
            "SELECT ts, kind, detail, path FROM sync_events "
            "ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:  # noqa: BLE001
        return []
