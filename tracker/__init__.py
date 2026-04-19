from pathlib import Path


def default_db_path() -> str:
    """Return the default database path relative to the project root."""
    return str(Path(__file__).parent.parent / "data" / "timesheet.db")
