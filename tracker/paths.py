"""Where your data lives: one folder, separate from the code.

Default: ~/.time_tracker (on Windows C:\\Users\\<you>\\.time_tracker). Set the
TIME_TRACKER_HOME environment variable to use another folder.

    ~/.time_tracker/
      timesheet.db       all subjects, hours, reflections and goals
      history_exports/   the end-of-week Excel reports
      gui.log            errors of the app, when started without a console

Kept outside the git clone on purpose: `git pull`, a fresh clone or deleting
the clone never touches your data. Before this folder existed the database
was <clone>/data/timesheet.db; adopt_legacy_db() copies it here once.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_NAME = "timesheet.db"


def home() -> Path:
    return Path(os.environ.get("TIME_TRACKER_HOME") or Path.home() / ".time_tracker").expanduser()


def db_path() -> Path:
    return home() / DB_NAME


def export_dir() -> Path:
    return home() / "history_exports"


def log_path() -> Path:
    return home() / "gui.log"


def legacy_db_path() -> Path:
    # Where versions before the package (Streamlit, up to Sep 2026) kept the
    # database: data/ next to the tracker/ folder of the clone. Only
    # meaningful with an editable install (pip install -e .), where
    # __file__ is inside the clone.
    return Path(__file__).resolve().parent.parent / "data" / DB_NAME


def _ro_uri(path: Path) -> str:
    # as_uri() gives file:///C:/... with spaces escaped; a bare "file:C:\\..."
    # is not a valid SQLite URI on Windows.
    return path.resolve().as_uri() + "?mode=ro"


def _copy_sqlite(src: Path, dst: Path) -> None:
    """Copy a database with SQLite's backup API: a consistent copy even if
    another program has it open, unlike a plain file copy.

    Written to a .part file and renamed at the end, so a failed copy never
    leaves a half-written dst (adopt_legacy_db would then skip it for good).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + ".part")
    s = sqlite3.connect(_ro_uri(src), uri=True)
    d = sqlite3.connect(part)
    try:
        s.backup(d)
    finally:
        s.close()
        d.close()
    os.replace(part, dst)


def _check_is_timesheet(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f"{path} does not exist")
    try:
        conn = sqlite3.connect(_ro_uri(path), uri=True)
        try:
            ok = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='time_entries'"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise ValueError(f"{path} is not a SQLite database ({e})") from e
    if not ok:
        raise ValueError(f"{path} is not a Time Tracker database (it has no time_entries table)")


def adopt_legacy_db() -> Optional[Path]:
    """Copy <clone>/data/timesheet.db into the data folder if there is no database there yet.

    Runs at every start and does nothing once a database exists, so it can
    never overwrite newer data. The old file is copied, not moved: it stays
    as a backup until you delete it. Returns the copied file, or None.
    """
    src, dst = legacy_db_path(), db_path()
    if dst.exists() or not src.is_file():
        return None
    _copy_sqlite(src, dst)
    return src


def import_db(src: Path, force: bool = False) -> Optional[Path]:
    """Make a copy of src the database. Returns the backup of the replaced database, if any.

    Without force an existing database is never replaced. With force it is
    first saved as timesheet.backup-<date-time>.db next to it.
    """
    src = Path(src).expanduser().resolve()
    _check_is_timesheet(src)
    dst = db_path()
    if src == dst.resolve():
        raise ValueError("That is already the database in use")
    backup = None
    if dst.exists():
        if not force:
            raise FileExistsError(f"{dst} already exists. Use --force to replace it (a backup is kept).")
        backup = dst.with_name(f"timesheet.backup-{datetime.now():%Y-%m-%d-%H%M%S}.db")
        _copy_sqlite(dst, backup)
    _copy_sqlite(src, dst)
    return backup
