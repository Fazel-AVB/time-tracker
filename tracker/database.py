from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

from tracker.models import Goal, GoalOutcome, Reflection, Subject, TimeEntry


class TimesheetDB:
    """SQLite persistence layer. Use as a context manager."""

    def __init__(self, path: str):
        self._path = path
        self._conn: Optional[sqlite3.Connection] = None

    def __enter__(self) -> "TimesheetDB":
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate_subject_constraint()
        self._init_schema()
        return self

    def __exit__(self, *_) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------ #
    # Schema
    # ------------------------------------------------------------------ #

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS subjects (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                name              TEXT NOT NULL,
                low_level_label   TEXT NOT NULL,
                high_level_label  TEXT NOT NULL,
                UNIQUE(name, low_level_label, high_level_label)
            );

            CREATE TABLE IF NOT EXISTS time_entries (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                date           TEXT NOT NULL,
                subject_id     INTEGER NOT NULL
                               REFERENCES subjects(id) ON DELETE RESTRICT,
                duration_hours REAL NOT NULL CHECK(duration_hours > 0),
                notes          TEXT DEFAULT '',
                created_at     TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS reflections (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start     TEXT NOT NULL UNIQUE,
                strengths      TEXT DEFAULT '',
                weaknesses     TEXT DEFAULT '',
                next_week_plan TEXT DEFAULT '',
                updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS goals (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start   TEXT NOT NULL,
                description  TEXT NOT NULL,
                target_hours REAL,
                subject_id   INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
                notes        TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS goal_outcomes (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id      INTEGER NOT NULL UNIQUE
                             REFERENCES goals(id) ON DELETE CASCADE,
                actual_hours REAL,
                met          INTEGER NOT NULL DEFAULT 0,
                notes        TEXT DEFAULT '',
                evaluated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS week_subject_exclusions (
                week_start TEXT    NOT NULL,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                PRIMARY KEY (week_start, subject_id)
            );
        """)
        self._conn.commit()

    def _migrate_subject_constraint(self) -> None:
        """Migrate existing DBs from UNIQUE(name) to UNIQUE(name, low_level_label, high_level_label).

        Uses CREATE+DROP+RENAME instead of RENAME+CREATE to avoid SQLite rewriting
        FK references in child tables (time_entries) to point at the temp table name.
        Also repairs any DB left in the broken state by the old migration strategy.
        """
        # Repair: if a previous migration left time_entries referencing _subjects_old, rebuild it.
        te_row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='time_entries'"
        ).fetchone()
        if te_row and '_subjects_old' in (te_row['sql'] or ''):
            self._conn.executescript("""
                PRAGMA foreign_keys = OFF;
                CREATE TABLE _time_entries_new (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    date           TEXT NOT NULL,
                    subject_id     INTEGER NOT NULL
                                   REFERENCES subjects(id) ON DELETE RESTRICT,
                    duration_hours REAL NOT NULL CHECK(duration_hours > 0),
                    notes          TEXT DEFAULT '',
                    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
                );
                INSERT INTO _time_entries_new SELECT * FROM time_entries;
                DROP TABLE time_entries;
                ALTER TABLE _time_entries_new RENAME TO time_entries;
                PRAGMA foreign_keys = ON;
            """)
            self._conn.commit()

        # Migrate subjects if still on the old name-only UNIQUE constraint.
        indices = self._conn.execute("PRAGMA index_list(subjects)").fetchall()
        for idx in indices:
            if idx["unique"]:
                cols = self._conn.execute(
                    f"PRAGMA index_info('{idx['name']}')"
                ).fetchall()
                if [c["name"] for c in cols] == ["name"]:
                    # Create new table, copy, drop old, rename — so time_entries keeps
                    # its REFERENCES subjects(id) without SQLite rewriting the FK target.
                    self._conn.executescript("""
                        PRAGMA foreign_keys = OFF;
                        CREATE TABLE _subjects_new (
                            id                INTEGER PRIMARY KEY AUTOINCREMENT,
                            name              TEXT NOT NULL,
                            low_level_label   TEXT NOT NULL,
                            high_level_label  TEXT NOT NULL,
                            UNIQUE(name, low_level_label, high_level_label)
                        );
                        INSERT INTO _subjects_new SELECT * FROM subjects;
                        DROP TABLE subjects;
                        ALTER TABLE _subjects_new RENAME TO subjects;
                        PRAGMA foreign_keys = ON;
                    """)
                    self._conn.commit()
                    return

    # ------------------------------------------------------------------ #
    # Subjects
    # ------------------------------------------------------------------ #

    def add_subject(self, subject: Subject) -> Subject:
        cur = self._conn.execute(
            "INSERT INTO subjects (name, low_level_label, high_level_label) VALUES (?, ?, ?)",
            (subject.name, subject.low_level_label, subject.high_level_label),
        )
        self._conn.commit()
        subject.id = cur.lastrowid
        return subject

    def update_subject(self, subject: Subject) -> None:
        self._conn.execute(
            "UPDATE subjects SET name=?, low_level_label=?, high_level_label=? WHERE id=?",
            (subject.name, subject.low_level_label, subject.high_level_label, subject.id),
        )
        self._conn.commit()

    def delete_subject(self, subject_id: int) -> None:
        self._conn.execute("DELETE FROM subjects WHERE id=?", (subject_id,))
        self._conn.commit()

    def get_subject(self, subject_id: int) -> Optional[Subject]:
        row = self._conn.execute(
            "SELECT * FROM subjects WHERE id=?", (subject_id,)
        ).fetchone()
        return _row_to_subject(row) if row else None

    def get_all_subjects(self) -> List[Subject]:
        rows = self._conn.execute(
            "SELECT * FROM subjects ORDER BY name"
        ).fetchall()
        return [_row_to_subject(r) for r in rows]

    def get_subjects_by_name(self, name: str) -> List[Subject]:
        rows = self._conn.execute(
            "SELECT * FROM subjects WHERE name=? ORDER BY low_level_label",
            (name,),
        ).fetchall()
        return [_row_to_subject(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Time Entries
    # ------------------------------------------------------------------ #

    def add_entry(self, entry: TimeEntry) -> TimeEntry:
        cur = self._conn.execute(
            "INSERT INTO time_entries (date, subject_id, duration_hours, notes) VALUES (?, ?, ?, ?)",
            (entry.date.isoformat(), entry.subject_id, entry.duration_hours, entry.notes),
        )
        self._conn.commit()
        entry.id = cur.lastrowid
        return entry

    def update_entry(self, entry: TimeEntry) -> None:
        self._conn.execute(
            "UPDATE time_entries SET date=?, subject_id=?, duration_hours=?, notes=? WHERE id=?",
            (entry.date.isoformat(), entry.subject_id, entry.duration_hours, entry.notes, entry.id),
        )
        self._conn.commit()

    def delete_entry(self, entry_id: int) -> None:
        self._conn.execute("DELETE FROM time_entries WHERE id=?", (entry_id,))
        self._conn.commit()

    def delete_entries_for_subject(self, subject_id: int) -> None:
        self._conn.execute("DELETE FROM time_entries WHERE subject_id=?", (subject_id,))
        self._conn.commit()

    def delete_entries_for_subject_in_week(self, subject_id: int, week_start: date) -> None:
        week_end = week_start + timedelta(days=7)
        self._conn.execute(
            "DELETE FROM time_entries WHERE subject_id=? AND date >= ? AND date < ?",
            (subject_id, week_start.isoformat(), week_end.isoformat()),
        )
        self._conn.commit()

    # ------------------------------------------------------------------ #
    # Week-subject exclusions
    # ------------------------------------------------------------------ #

    def add_week_exclusion(self, week_start: date, subject_id: int) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO week_subject_exclusions (week_start, subject_id) VALUES (?, ?)",
            (week_start.isoformat(), subject_id),
        )
        self._conn.commit()

    def remove_week_exclusion(self, week_start: date, subject_id: int) -> None:
        self._conn.execute(
            "DELETE FROM week_subject_exclusions WHERE week_start=? AND subject_id=?",
            (week_start.isoformat(), subject_id),
        )
        self._conn.commit()

    def get_excluded_subject_ids(self, week_start: date) -> set:
        rows = self._conn.execute(
            "SELECT subject_id FROM week_subject_exclusions WHERE week_start=?",
            (week_start.isoformat(),),
        ).fetchall()
        return {r["subject_id"] for r in rows}

    def get_entries_for_week(self, week_start: date) -> List[TimeEntry]:
        week_end = week_start + timedelta(days=7)
        rows = self._conn.execute(
            """
            SELECT te.*, s.name AS subject_name,
                   s.low_level_label, s.high_level_label
            FROM time_entries te
            JOIN subjects s ON te.subject_id = s.id
            WHERE te.date >= ? AND te.date < ?
            ORDER BY te.date, s.name
            """,
            (week_start.isoformat(), week_end.isoformat()),
        ).fetchall()
        return [_row_to_entry(r) for r in rows]

    def get_entries_for_range(self, start: date, end: date) -> List[TimeEntry]:
        rows = self._conn.execute(
            """
            SELECT te.*, s.name AS subject_name,
                   s.low_level_label, s.high_level_label
            FROM time_entries te
            JOIN subjects s ON te.subject_id = s.id
            WHERE te.date >= ? AND te.date < ?
            ORDER BY te.date
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [_row_to_entry(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Reflections
    # ------------------------------------------------------------------ #

    def upsert_reflection(self, reflection: Reflection) -> None:
        self._conn.execute(
            """
            INSERT INTO reflections (week_start, strengths, weaknesses, next_week_plan, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(week_start) DO UPDATE SET
                strengths      = excluded.strengths,
                weaknesses     = excluded.weaknesses,
                next_week_plan = excluded.next_week_plan,
                updated_at     = excluded.updated_at
            """,
            (
                reflection.week_start.isoformat(),
                reflection.strengths,
                reflection.weaknesses,
                reflection.next_week_plan,
            ),
        )
        self._conn.commit()

    def get_reflection(self, week_start: date) -> Optional[Reflection]:
        row = self._conn.execute(
            "SELECT * FROM reflections WHERE week_start=?", (week_start.isoformat(),)
        ).fetchone()
        return _row_to_reflection(row) if row else None

    # ------------------------------------------------------------------ #
    # Goals
    # ------------------------------------------------------------------ #

    def add_goal(self, goal: Goal) -> Goal:
        cur = self._conn.execute(
            "INSERT INTO goals (week_start, description, target_hours, subject_id, notes) VALUES (?, ?, ?, ?, ?)",
            (goal.week_start.isoformat(), goal.description, goal.target_hours, goal.subject_id, goal.notes),
        )
        self._conn.commit()
        goal.id = cur.lastrowid
        return goal

    def delete_goal(self, goal_id: int) -> None:
        self._conn.execute("DELETE FROM goals WHERE id=?", (goal_id,))
        self._conn.commit()

    def get_goals_for_week(self, week_start: date) -> List[Goal]:
        rows = self._conn.execute(
            """
            SELECT g.*, s.name AS subject_name
            FROM goals g
            LEFT JOIN subjects s ON g.subject_id = s.id
            WHERE g.week_start = ?
            ORDER BY g.id
            """,
            (week_start.isoformat(),),
        ).fetchall()
        return [_row_to_goal(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Goal Outcomes
    # ------------------------------------------------------------------ #

    def upsert_goal_outcome(self, outcome: GoalOutcome) -> None:
        self._conn.execute(
            """
            INSERT INTO goal_outcomes (goal_id, actual_hours, met, notes, evaluated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(goal_id) DO UPDATE SET
                actual_hours = excluded.actual_hours,
                met          = excluded.met,
                notes        = excluded.notes,
                evaluated_at = excluded.evaluated_at
            """,
            (outcome.goal_id, outcome.actual_hours, outcome.met, outcome.notes),
        )
        self._conn.commit()

    def get_outcome_for_goal(self, goal_id: int) -> Optional[GoalOutcome]:
        row = self._conn.execute(
            "SELECT * FROM goal_outcomes WHERE goal_id=?", (goal_id,)
        ).fetchone()
        return _row_to_outcome(row) if row else None


# ------------------------------------------------------------------ #
# Row converters
# ------------------------------------------------------------------ #

def _row_to_subject(row: sqlite3.Row) -> Subject:
    return Subject(
        id=row["id"],
        name=row["name"],
        low_level_label=row["low_level_label"],
        high_level_label=row["high_level_label"],
    )


def _row_to_entry(row: sqlite3.Row) -> TimeEntry:
    keys = row.keys()
    return TimeEntry(
        id=row["id"],
        date=date.fromisoformat(row["date"]),
        subject_id=row["subject_id"],
        duration_hours=row["duration_hours"],
        notes=row["notes"] or "",
        subject_name=row["subject_name"] if "subject_name" in keys else None,
        low_level_label=row["low_level_label"] if "low_level_label" in keys else None,
        high_level_label=row["high_level_label"] if "high_level_label" in keys else None,
    )


def _row_to_reflection(row: sqlite3.Row) -> Reflection:
    return Reflection(
        id=row["id"],
        week_start=date.fromisoformat(row["week_start"]),
        strengths=row["strengths"] or "",
        weaknesses=row["weaknesses"] or "",
        next_week_plan=row["next_week_plan"] or "",
    )


def _row_to_goal(row: sqlite3.Row) -> Goal:
    keys = row.keys()
    return Goal(
        id=row["id"],
        week_start=date.fromisoformat(row["week_start"]),
        description=row["description"],
        target_hours=row["target_hours"],
        subject_id=row["subject_id"],
        notes=row["notes"] or "",
        subject_name=row["subject_name"] if "subject_name" in keys else None,
    )


def _row_to_outcome(row: sqlite3.Row) -> GoalOutcome:
    return GoalOutcome(
        id=row["id"],
        goal_id=row["goal_id"],
        actual_hours=row["actual_hours"],
        met=row["met"],
        notes=row["notes"] or "",
    )
