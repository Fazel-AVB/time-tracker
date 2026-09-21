from pathlib import Path


def default_db_path() -> str:
    """Return the default database path relative to the project root."""
    return str(Path(__file__).parent.parent / "data" / "timesheet.db")


def default_export_dir() -> str:
    """Folder the end-of-week report prompt saves .xlsx files into (gitignored)."""
    return str(Path(__file__).parent.parent / "history_exports")
