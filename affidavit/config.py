"""Configuration for the affidavit pipeline.

Everything is local. No network calls, no third-party APIs. Client documents
never leave the machine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

CONFIG_FILENAME = "affidavit.config.json"


@dataclass
class Config:
    # Where raw client documents arrive (the only folder a human drops files into)
    source_dir: Path = Path("intake/source")

    # All derived artefacts live under here
    work_dir: Path = Path("work")
    output_dir: Path = Path("output")

    # --- Matter metadata: drives the cover sheet and index headers ---
    court: str = "ONTARIO\nSUPERIOR COURT OF JUSTICE"
    court_file_no: str = ""
    proceeding_between_plaintiff: str = ""
    proceeding_between_defendant: str = ""
    deponent_name: str = ""
    deponent_role: str = ""
    jurisdiction_rules: str = "Rules of Civil Procedure, R.R.O. 1990, Reg. 194, Rule 30.03"

    # --- Naming convention for normalised files ---
    # Rendered with {date} {doctype} {title} {hash8} {seq}. Plain text, so it
    # can be changed to taste; see build_filename() in pipeline.py.
    filename_template: str = "{date}_{doctype}_{title}"

    # --- Near-duplicate detection ---
    # Two documents are treated as the same instrument when BOTH the character
    # similarity and the significant-token overlap clear these bars. The token
    # test prevents two unrelated documents that merely share legal vocabulary
    # from being silently merged -- which in an affidavit would drop a document.
    near_dup_threshold: float = 0.90
    near_dup_min_token_overlap: float = 0.85

    # Bates-style numbering of the assembled package. Ontario practice does not
    # require it; leave False to emit plain sequential exhibit numbers.
    bates_numbering: bool = False
    bates_prefix: str = "DOC"

    # --- OCR (optional; requires Tesseract installed locally) ---
    # Language data must be installed alongside Tesseract. For Canadian matters
    # "eng+fra" is often wanted; check with `tesseract --list-langs`.
    ocr_lang: str = "eng"
    ocr_dpi: int = 200
    ocr_max_pages: int = 25
    ocr_enabled: bool = True

    # --- Auto-sync: the folder a user drops files into ---
    # Drop a file in the watch folder and it is picked up, copied into the
    # library and appears in the console on its own. Polling is used rather
    # than filesystem events: it works on locked-down machines and behaves
    # predictably with cloud-synced folders that appear in bursts.
    auto_sync_enabled: bool = True
    sync_watch_dir: str = "intake/incoming"
    sync_poll_seconds: float = 4.0
    sync_settle_seconds: float = 3.0
    sync_reject_dir: str = "intake/rejected"

    # Warn if the drop folder sits inside a cloud-synced tree: client documents
    # would then be copied to a third party without anyone deciding to.
    sync_warn_cloud_paths: bool = True

    # Overridable so a test can work against a throwaway database.
    db_path: Path = Path("work/pipeline.sqlite3")

    extra: dict = field(default_factory=dict)

    # ---- derived paths ----
    @property
    def normalized_dir(self) -> Path:
        return self.work_dir / "normalized"

    @property
    def quarantine_dir(self) -> Path:
        return self.work_dir / "quarantine"

    @property
    def log_dir(self) -> Path:
        return self.work_dir / "logs"

    @property
    def reports_dir(self) -> Path:
        return self.output_dir / "reports"

    @property
    def schedules_dir(self) -> Path:
        return self.output_dir / "schedules"

    @property
    def package_dir(self) -> Path:
        return self.output_dir / "package"

    @property
    def collections_dir(self) -> Path:
        return self.output_dir / "collections"

    @property
    def finished_dir(self) -> Path:
        """Where exported bundles land. They leave the console once here."""
        return self.collections_dir / "finished"

    @property
    def watch_dir(self) -> Path:
        p = Path(self.sync_watch_dir)
        return p if p.is_absolute() else self.source_dir.parent.parent / p

    @property
    def reject_dir(self) -> Path:
        p = Path(self.sync_reject_dir)
        return p if p.is_absolute() else self.source_dir.parent.parent / p

    def ensure_dirs(self) -> None:
        for d in (
            self.source_dir,
            self.work_dir,
            self.normalized_dir,
            self.quarantine_dir,
            self.log_dir,
            self.output_dir,
            self.reports_dir,
            self.schedules_dir,
            self.package_dir,
            self.collections_dir,
            self.finished_dir,
            self.watch_dir,
            self.reject_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def to_json(self) -> str:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, Path):
                d[k] = str(v)
        return json.dumps(d, indent=2)


def save_config(cfg: Config, root: Path | str = ".") -> Path:
    """Write the settings file, so a change made in the console survives a restart.

    Paths that live inside the project are stored relative to it, so the folder
    can be moved or copied to another machine without breaking.
    """
    root = Path(root).resolve()
    d = asdict(cfg)
    d.pop("extra", None)
    for key in ("source_dir", "work_dir", "output_dir", "db_path"):
        value = d.get(key)
        if value:
            try:
                d[key] = str(Path(value).resolve().relative_to(root))
            except (ValueError, OSError):
                d[key] = str(value)
    path = root / CONFIG_FILENAME
    path.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    return path


def set_watch_dir(cfg: Config, folder: str) -> tuple[bool, str]:
    """Point the watcher at a folder, checking it is usable first.

    A shared or synced folder is a normal thing to watch, so a path that does
    not exist yet is created rather than refused. A path that exists but cannot
    be written to is refused, because the rejected-file notes are written back
    into the watched area.
    """
    folder = (folder or "").strip().strip('"')
    if not folder:
        return False, "Give a folder path."

    candidate = Path(folder).expanduser()
    try:
        candidate = candidate.resolve()
    except OSError:
        pass

    if candidate.exists() and not candidate.is_dir():
        return False, f"That is a file, not a folder: {candidate}"

    try:
        candidate.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, (f"That folder cannot be created or reached: {exc}. "
                       "Check the path, and that the drive is connected.")

    # A quick write test. A network share that has dropped out looks like a
    # normal path until something tries to use it.
    probe = candidate / ".affidavit-write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return False, (f"That folder cannot be written to: {exc}. "
                       "If it is a shared drive, check it is connected and that "
                       "you have permission to create files there.")

    cfg.sync_watch_dir = str(candidate)
    return True, str(candidate)


def load_config(root: Path | str = ".") -> Config:
    """Load config from affidavit.config.json if present, else defaults."""
    root = Path(root)
    cfg = Config()
    cfg.db_path = root / "work" / "pipeline.sqlite3"
    path = root / CONFIG_FILENAME
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        known = {f for f in Config.__dataclass_fields__}
        for k, v in raw.items():
            if k not in known:
                cfg.extra[k] = v
                continue
            if k in {"source_dir", "work_dir", "output_dir", "db_path"}:
                setattr(cfg, k, root / v)
            else:
                setattr(cfg, k, v)
    else:
        cfg.source_dir = root / cfg.source_dir
        cfg.work_dir = root / cfg.work_dir
        cfg.output_dir = root / cfg.output_dir
    return cfg
