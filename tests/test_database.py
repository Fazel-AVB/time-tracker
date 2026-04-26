"""Unit tests for tracker/database.py — TimesheetDB CRUD layer."""

import pytest
from datetime import date, timedelta

from tracker.database import TimesheetDB
from tracker.models import Goal, GoalOutcome, Reflection, Subject, TimeEntry


@pytest.fixture
def db(tmp_path):
    """Fresh in-memory-equivalent DB in a temp directory for each test."""
    path = str(tmp_path / "test.db")
    with TimesheetDB(path) as db:
        yield db


@pytest.fixture
def subject(db):
    return db.add_subject(Subject(name="Reading", low_level_label="leisure", high_level_label="Personal"))


@pytest.fixture
def week():
    return date(2026, 4, 20)  # confirmed Monday


# ------------------------------------------------------------------ #
# Subjects
# ------------------------------------------------------------------ #

class TestSubjects:
    def test_add_and_get(self, db):
        s = db.add_subject(Subject(name="Coding", low_level_label="work", high_level_label="Work"))
        assert s.id is not None
        fetched = db.get_subject(s.id)
        assert fetched.name == "Coding"
        assert fetched.low_level_label == "work"
        assert fetched.high_level_label == "Work"

    def test_get_all_subjects_ordered_by_name(self, db):
        db.add_subject(Subject(name="Yoga", low_level_label="health", high_level_label="Personal"))
        db.add_subject(Subject(name="Coding", low_level_label="work", high_level_label="Work"))
        subjects = db.get_all_subjects()
        names = [s.name for s in subjects]
        assert names == sorted(names)

    def test_update_subject(self, db, subject):
        subject.high_level_label = "Education"
        db.update_subject(subject)
        fetched = db.get_subject(subject.id)
        assert fetched.high_level_label == "Education"

    def test_delete_subject(self, db, subject):
        db.delete_subject(subject.id)
        assert db.get_subject(subject.id) is None

    def test_delete_subject_with_entries_raises(self, db, subject, week):
        db.add_entry(TimeEntry(date=week, subject_id=subject.id, duration_hours=1.0))
        with pytest.raises(Exception):
            db.delete_subject(subject.id)

    def test_composite_unique_allows_same_name_different_labels(self, db):
        db.add_subject(Subject(name="Programming", low_level_label="work-related", high_level_label="Work"))
        db.add_subject(Subject(name="Programming", low_level_label="education", high_level_label="Education"))
        subjects = db.get_subjects_by_name("Programming")
        assert len(subjects) == 2

    def test_composite_unique_rejects_exact_duplicate(self, db):
        db.add_subject(Subject(name="Programming", low_level_label="work", high_level_label="Work"))
        with pytest.raises(Exception):
            db.add_subject(Subject(name="Programming", low_level_label="work", high_level_label="Work"))

    def test_get_subjects_by_name_returns_empty_for_unknown(self, db):
        assert db.get_subjects_by_name("NonExistent") == []

    def test_get_nonexistent_subject_returns_none(self, db):
        assert db.get_subject(9999) is None


# ------------------------------------------------------------------ #
# Time Entries
# ------------------------------------------------------------------ #

class TestTimeEntries:
    def test_add_and_get_for_week(self, db, subject, week):
        entry = db.add_entry(TimeEntry(date=week, subject_id=subject.id, duration_hours=2.5))
        assert entry.id is not None
        entries = db.get_entries_for_week(week)
        assert len(entries) == 1
        assert entries[0].duration_hours == 2.5

    def test_entries_include_subject_name(self, db, subject, week):
        db.add_entry(TimeEntry(date=week, subject_id=subject.id, duration_hours=1.0))
        entries = db.get_entries_for_week(week)
        assert entries[0].subject_name == subject.name

    def test_entries_for_week_excludes_other_weeks(self, db, subject, week):
        db.add_entry(TimeEntry(date=week, subject_id=subject.id, duration_hours=1.0))
        db.add_entry(TimeEntry(date=week + timedelta(weeks=1), subject_id=subject.id, duration_hours=2.0))
        entries = db.get_entries_for_week(week)
        assert len(entries) == 1
        assert entries[0].duration_hours == 1.0

    def test_update_entry(self, db, subject, week):
        entry = db.add_entry(TimeEntry(date=week, subject_id=subject.id, duration_hours=1.0))
        entry.duration_hours = 3.0
        db.update_entry(entry)
        entries = db.get_entries_for_week(week)
        assert entries[0].duration_hours == 3.0

    def test_delete_entry(self, db, subject, week):
        entry = db.add_entry(TimeEntry(date=week, subject_id=subject.id, duration_hours=1.0))
        db.delete_entry(entry.id)
        assert db.get_entries_for_week(week) == []

    def test_get_entries_for_range(self, db, subject, week):
        for i in range(3):
            db.add_entry(TimeEntry(date=week + timedelta(weeks=i), subject_id=subject.id, duration_hours=float(i + 1)))
        entries = db.get_entries_for_range(week, week + timedelta(weeks=2))
        assert len(entries) == 2

    def test_multiple_entries_same_day(self, db, week):
        s1 = db.add_subject(Subject(name="A", low_level_label="a", high_level_label="A"))
        s2 = db.add_subject(Subject(name="B", low_level_label="b", high_level_label="B"))
        db.add_entry(TimeEntry(date=week, subject_id=s1.id, duration_hours=1.0))
        db.add_entry(TimeEntry(date=week, subject_id=s2.id, duration_hours=2.0))
        entries = db.get_entries_for_week(week)
        assert len(entries) == 2


# ------------------------------------------------------------------ #
# Reflections
# ------------------------------------------------------------------ #

class TestReflections:
    def test_upsert_creates_new(self, db, week):
        db.upsert_reflection(Reflection(week_start=week, strengths="Focus", weaknesses="Distracted"))
        r = db.get_reflection(week)
        assert r.strengths == "Focus"
        assert r.weaknesses == "Distracted"

    def test_upsert_updates_existing(self, db, week):
        db.upsert_reflection(Reflection(week_start=week, strengths="Good"))
        db.upsert_reflection(Reflection(week_start=week, strengths="Even better"))
        r = db.get_reflection(week)
        assert r.strengths == "Even better"

    def test_get_nonexistent_reflection_returns_none(self, db, week):
        assert db.get_reflection(week) is None

    def test_reflections_are_per_week(self, db, week):
        db.upsert_reflection(Reflection(week_start=week, strengths="Week 1"))
        db.upsert_reflection(Reflection(week_start=week + timedelta(weeks=1), strengths="Week 2"))
        assert db.get_reflection(week).strengths == "Week 1"
        assert db.get_reflection(week + timedelta(weeks=1)).strengths == "Week 2"


# ------------------------------------------------------------------ #
# Goals
# ------------------------------------------------------------------ #

class TestGoals:
    def test_add_and_get_goals_for_week(self, db, week):
        db.add_goal(Goal(week_start=week, description="Write 2h/day", target_hours=14.0))
        goals = db.get_goals_for_week(week)
        assert len(goals) == 1
        assert goals[0].description == "Write 2h/day"
        assert goals[0].target_hours == 14.0

    def test_goal_with_subject_link(self, db, subject, week):
        db.add_goal(Goal(week_start=week, description="Read daily", subject_id=subject.id))
        goals = db.get_goals_for_week(week)
        assert goals[0].subject_id == subject.id
        assert goals[0].subject_name == subject.name

    def test_delete_goal(self, db, week):
        g = db.add_goal(Goal(week_start=week, description="Exercise"))
        db.delete_goal(g.id)
        assert db.get_goals_for_week(week) == []

    def test_goals_are_per_week(self, db, week):
        db.add_goal(Goal(week_start=week, description="Goal A"))
        db.add_goal(Goal(week_start=week + timedelta(weeks=1), description="Goal B"))
        assert len(db.get_goals_for_week(week)) == 1
        assert db.get_goals_for_week(week)[0].description == "Goal A"

    def test_qualitative_goal_has_no_target_hours(self, db, week):
        db.add_goal(Goal(week_start=week, description="Be mindful"))
        goals = db.get_goals_for_week(week)
        assert goals[0].target_hours is None


# ------------------------------------------------------------------ #
# Goal Outcomes
# ------------------------------------------------------------------ #

class TestGoalOutcomes:
    def test_upsert_creates_outcome(self, db, week):
        g = db.add_goal(Goal(week_start=week, description="Run 5k"))
        db.upsert_goal_outcome(GoalOutcome(goal_id=g.id, met=1, actual_hours=2.0))
        outcome = db.get_outcome_for_goal(g.id)
        assert outcome.met == 1
        assert outcome.actual_hours == 2.0

    def test_upsert_updates_existing_outcome(self, db, week):
        g = db.add_goal(Goal(week_start=week, description="Run 5k"))
        db.upsert_goal_outcome(GoalOutcome(goal_id=g.id, met=0))
        db.upsert_goal_outcome(GoalOutcome(goal_id=g.id, met=1, notes="Done!"))
        outcome = db.get_outcome_for_goal(g.id)
        assert outcome.met == 1
        assert outcome.notes == "Done!"

    def test_get_outcome_for_nonexistent_goal_returns_none(self, db):
        assert db.get_outcome_for_goal(9999) is None

    def test_delete_goal_cascades_to_outcome(self, db, week):
        g = db.add_goal(Goal(week_start=week, description="Sleep 8h"))
        db.upsert_goal_outcome(GoalOutcome(goal_id=g.id, met=2))
        db.delete_goal(g.id)
        assert db.get_outcome_for_goal(g.id) is None


# ------------------------------------------------------------------ #
# Schema migration
# ------------------------------------------------------------------ #

class TestMigration:
    def test_migration_idempotent_on_new_db(self, tmp_path):
        """Opening a brand-new DB twice should not raise."""
        path = str(tmp_path / "fresh.db")
        with TimesheetDB(path) as db:
            db.add_subject(Subject(name="X", low_level_label="a", high_level_label="A"))
        with TimesheetDB(path) as db:
            assert len(db.get_all_subjects()) == 1
