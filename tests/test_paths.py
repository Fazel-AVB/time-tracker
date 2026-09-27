"""Tests for tracker/paths.py — the data folder and moving data out of the clone."""

import sqlite3
from pathlib import Path

import pytest

from tracker import paths
from tracker.database import TimesheetDB
from tracker.models import Subject


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TIME_TRACKER_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def make_db(path: Path, name="Reading") -> Path:
    with TimesheetDB(str(path)) as db:
        db.add_subject(Subject(name=name, low_level_label="l", high_level_label="H"))
    return path


def subject_names(path: Path) -> list:
    with TimesheetDB(str(path)) as db:
        return [s.name for s in db.get_all_subjects()]


def test_home_from_env(home):
    assert paths.home() == home
    assert paths.db_path() == home / "timesheet.db"


def test_adopt_copies_legacy_once(home, tmp_path, monkeypatch):
    legacy = make_db(tmp_path / "clone" / "data" / "timesheet.db")
    monkeypatch.setattr(paths, "legacy_db_path", lambda: legacy)
    assert paths.adopt_legacy_db() == legacy
    assert subject_names(paths.db_path()) == ["Reading"]
    assert legacy.exists()  # copied, not moved
    # Once a database exists, the old one is never copied over it again.
    make_db(legacy, "Newer in old place")
    assert paths.adopt_legacy_db() is None
    assert subject_names(paths.db_path()) == ["Reading"]


def test_adopt_without_legacy(home, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "legacy_db_path", lambda: tmp_path / "nothing.db")
    assert paths.adopt_legacy_db() is None
    assert not paths.db_path().exists()


def test_import_refuses_to_overwrite_without_force(home, tmp_path):
    make_db(paths.db_path(), "Current")
    src = make_db(tmp_path / "other.db", "Other")
    with pytest.raises(FileExistsError):
        paths.import_db(src)
    assert subject_names(paths.db_path()) == ["Current"]


def test_import_force_keeps_backup(home, tmp_path):
    make_db(paths.db_path(), "Current")
    src = make_db(tmp_path / "other.db", "Other")
    backup = paths.import_db(src, force=True)
    assert subject_names(paths.db_path()) == ["Other"]
    assert subject_names(backup) == ["Current"]


def test_import_rejects_other_files(home, tmp_path):
    junk = tmp_path / "junk.db"
    junk.write_text("not a database")
    with pytest.raises(ValueError):
        paths.import_db(junk)
    other = tmp_path / "other.sqlite"
    sqlite3.connect(other).execute("CREATE TABLE x (a)").connection.close()
    with pytest.raises(ValueError, match="time_entries"):
        paths.import_db(other)
