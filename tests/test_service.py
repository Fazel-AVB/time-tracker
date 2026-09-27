"""Unit tests for tracker/service.py — what the app's buttons do, without a browser."""

from datetime import date, timedelta

import openpyxl
import io
import pytest

from tracker import service
from tracker.database import TimesheetDB
from tracker.models import Goal, Subject, TimeEntry
from tracker.service import UserError

MON = date(2026, 9, 14)  # a Monday


@pytest.fixture
def db(tmp_path):
    with TimesheetDB(str(tmp_path / "t.db")) as d:
        yield d


@pytest.fixture
def subj(db):
    return db.add_subject(Subject(name="Reading", low_level_label="leisure", high_level_label="Personal"))


def row_of(view, subject_id):
    return next((r for r in view["rows"] if r["id"] == subject_id), None)


class TestParseWeek:
    def test_snaps_to_monday(self):
        assert service.parse_week("2026-09-17") == MON

    def test_bad_date(self):
        with pytest.raises(UserError):
            service.parse_week("yesterday")


class TestWeekTable:
    def test_hours_summed_per_day(self, db, subj):
        db.add_entry(TimeEntry(date=MON, subject_id=subj.id, duration_hours=1.0))
        db.add_entry(TimeEntry(date=MON, subject_id=subj.id, duration_hours=0.5))
        db.add_entry(TimeEntry(date=MON + timedelta(days=6), subject_id=subj.id, duration_hours=2.0))
        view = service.week_table(db, MON)
        r = row_of(view, subj.id)
        assert r["days"] == [1.5, 0, 0, 0, 0, 0, 2.0]
        assert r["total"] == 3.5
        assert view["day_totals"][0] == 1.5
        assert view["week_total"] == 3.5

    def test_rows_with_hours_sorted_by_labels_empty_rows_last(self, db):
        a = db.add_subject(Subject(name="A", low_level_label="z", high_level_label="Work"))
        b = db.add_subject(Subject(name="B", low_level_label="a", high_level_label="Home"))
        c = db.add_subject(Subject(name="C", low_level_label="a", high_level_label="Alpha"))
        db.add_entry(TimeEntry(date=MON, subject_id=a.id, duration_hours=1))
        db.add_entry(TimeEntry(date=MON, subject_id=b.id, duration_hours=1))
        service.add_row(db, MON, "C", "a", "Alpha")  # pinned, no hours
        ids = [r["id"] for r in service.week_table(db, MON)["rows"]]
        assert ids == [b.id, a.id, c.id]

    def test_season_and_dates(self, db):
        view = service.week_table(db, MON)
        assert view["week_start"] == "2026-09-14"
        assert view["week_end"] == "2026-09-20"
        assert view["season"]["key"] == "autumn"


class TestSetDayHours:
    def test_creates_entry(self, db, subj):
        service.set_day_hours(db, MON, subj.id, 2, 1.25)
        [e] = db.get_entries_for_week(MON)
        assert (e.date, e.duration_hours) == (MON + timedelta(days=2), 1.25)

    def test_updates_single_entry_keeping_note(self, db, subj):
        db.add_entry(TimeEntry(date=MON, subject_id=subj.id, duration_hours=1, notes="chapter 3"))
        service.set_day_hours(db, MON, subj.id, 0, 3)
        [e] = db.get_entries_for_week(MON)
        assert (e.duration_hours, e.notes) == (3, "chapter 3")

    def test_several_entries_become_one_with_joined_notes(self, db, subj):
        db.add_entry(TimeEntry(date=MON, subject_id=subj.id, duration_hours=1, notes="a"))
        db.add_entry(TimeEntry(date=MON, subject_id=subj.id, duration_hours=1, notes="b"))
        service.set_day_hours(db, MON, subj.id, 0, 5)
        [e] = db.get_entries_for_week(MON)
        assert (e.duration_hours, e.notes) == (5, "a; b")

    def test_zero_deletes(self, db, subj):
        db.add_entry(TimeEntry(date=MON, subject_id=subj.id, duration_hours=1))
        service.set_day_hours(db, MON, subj.id, 0, 0)
        assert db.get_entries_for_week(MON) == []

    def test_other_days_and_subjects_untouched(self, db, subj):
        other = db.add_subject(Subject(name="O", low_level_label="o", high_level_label="O"))
        db.add_entry(TimeEntry(date=MON, subject_id=other.id, duration_hours=1))
        db.add_entry(TimeEntry(date=MON + timedelta(days=1), subject_id=subj.id, duration_hours=1))
        service.set_day_hours(db, MON, subj.id, 0, 2)
        assert sorted((e.subject_id, e.date, e.duration_hours) for e in db.get_entries_for_week(MON)) == sorted([
            (other.id, MON, 1), (subj.id, MON + timedelta(days=1), 1), (subj.id, MON, 2)])

    @pytest.mark.parametrize("bad", [-1, 24.5, "abc", None])
    def test_rejects_bad_hours(self, db, subj, bad):
        with pytest.raises(UserError):
            service.set_day_hours(db, MON, subj.id, 0, bad)

    def test_rejects_bad_day(self, db, subj):
        with pytest.raises(UserError):
            service.set_day_hours(db, MON, subj.id, 7, 1)

    def test_typing_hours_undoes_row_removal(self, db, subj):
        service.remove_row(db, MON, subj.id)
        service.set_day_hours(db, MON, subj.id, 0, 1)
        assert subj.id not in db.get_excluded_subject_ids(MON)


class TestRows:
    def test_add_row_pins_new_subject(self, db):
        s = service.add_row(db, MON, "Coding", "python", "Work")
        assert row_of(service.week_table(db, MON), s["id"]) is not None
        # A pin is per week.
        assert row_of(service.week_table(db, MON + timedelta(weeks=5)), s["id"]) is None

    def test_add_row_snaps_to_existing_spelling(self, db, subj):
        s = service.add_row(db, MON, "reading", "LEISURE", "personal")
        assert s["id"] == subj.id

    def test_add_row_requires_all_fields(self, db):
        with pytest.raises(UserError):
            service.add_row(db, MON, "Coding", "", "Work")

    def test_add_row_undoes_removal(self, db, subj):
        service.remove_row(db, MON, subj.id)
        service.add_row(db, MON, "Reading", "leisure", "Personal")
        assert row_of(service.week_table(db, MON), subj.id) is not None

    def test_add_row_unhides_retyped_values(self, db, subj):
        service.hide_suggestion(db, "Low Label", "leisure")
        assert "leisure" not in service.week_table(db, MON)["suggestions"]["Low Label"]
        service.add_row(db, MON, "Reading", "Leisure", "Personal")
        assert "leisure" in service.week_table(db, MON)["suggestions"]["Low Label"]

    def test_remove_row_is_week_scoped(self, db, subj):
        db.add_entry(TimeEntry(date=MON, subject_id=subj.id, duration_hours=1))
        db.add_entry(TimeEntry(date=MON + timedelta(weeks=1), subject_id=subj.id, duration_hours=2))
        service.remove_row(db, MON, subj.id)
        assert row_of(service.week_table(db, MON), subj.id) is None
        assert db.get_entries_for_week(MON) == []
        assert len(db.get_entries_for_week(MON + timedelta(weeks=1))) == 1

    def test_rename_moves_this_weeks_hours_only(self, db, subj):
        db.add_entry(TimeEntry(date=MON, subject_id=subj.id, duration_hours=1, notes="kept"))
        db.add_entry(TimeEntry(date=MON - timedelta(weeks=1), subject_id=subj.id, duration_hours=2))
        new = service.rename_row(db, MON, subj.id, "Reading", "study", "Personal")
        assert new["id"] != subj.id
        view = service.week_table(db, MON)
        assert row_of(view, subj.id) is None
        assert row_of(view, new["id"])["total"] == 1
        [e] = db.get_entries_for_week(MON)
        assert e.notes == "kept"
        # The earlier week still belongs to the old subject.
        assert db.get_entries_for_week(MON - timedelta(weeks=1))[0].subject_id == subj.id

    def test_rename_to_same_values_is_noop(self, db, subj):
        assert service.rename_row(db, MON, subj.id, "Reading", "leisure", "Personal")["id"] == subj.id
        assert subj.id not in db.get_excluded_subject_ids(MON)

    def test_rename_requires_all_fields(self, db, subj):
        with pytest.raises(UserError):
            service.rename_row(db, MON, subj.id, "", "leisure", "Personal")

    def test_delete_subject_everywhere(self, db, subj):
        db.add_entry(TimeEntry(date=MON, subject_id=subj.id, duration_hours=1))
        service.delete_subject(db, subj.id)
        assert db.get_all_subjects() == []
        assert db.get_entries_for_week(MON) == []

    def test_hide_unknown_column(self, db):
        with pytest.raises(UserError):
            service.hide_suggestion(db, "Nope", "x")

    def test_xlsx_includes_rows_without_hours(self, db, subj):
        service.add_row(db, MON, "Empty", "e", "E")
        db.add_entry(TimeEntry(date=MON, subject_id=subj.id, duration_hours=2))
        wb = openpyxl.load_workbook(io.BytesIO(service.week_table_xlsx(db, MON)))
        rows = list(wb["Weekly Table"].values)
        assert rows[0][:3] == ("Subject", "Low Label", "High Label")
        assert {r[0] for r in rows[1:]} == {"Reading", "Empty"}


class TestEntries:
    def test_add_update_delete(self, db, subj):
        eid = service.add_entry(db, {"subject_id": subj.id, "date": "2026-09-15", "hours": 1.5, "notes": " n "})["id"]
        e = db.get_entry(eid)
        assert (e.duration_hours, e.notes) == (1.5, "n")
        service.update_entry(db, eid, {"subject_id": subj.id, "date": "2026-09-16", "hours": 2, "notes": ""})
        assert db.get_entry(eid).date == date(2026, 9, 16)
        service.delete_entry(db, eid)
        assert db.get_entry(eid) is None

    @pytest.mark.parametrize("hours", [0, -1, 25])
    def test_rejects_bad_duration(self, db, subj, hours):
        with pytest.raises(UserError):
            service.add_entry(db, {"subject_id": subj.id, "date": "2026-09-15", "hours": hours})

    def test_rejects_missing_subject(self, db):
        with pytest.raises(UserError):
            service.add_entry(db, {"subject_id": 999, "date": "2026-09-15", "hours": 1})

    def test_update_missing_entry(self, db, subj):
        with pytest.raises(UserError):
            service.update_entry(db, 42, {"subject_id": subj.id, "date": "2026-09-15", "hours": 1})


class TestReport:
    def test_empty_week(self, db):
        r = service.week_report(db, MON)
        assert r["has_entries"] is False

    def test_numbers(self, db, subj):
        other = db.add_subject(Subject(name="Coding", low_level_label="py", high_level_label="Work"))
        db.add_entry(TimeEntry(date=MON, subject_id=subj.id, duration_hours=1))
        db.add_entry(TimeEntry(date=MON, subject_id=other.id, duration_hours=3))
        db.add_entry(TimeEntry(date=MON - timedelta(weeks=1), subject_id=other.id, duration_hours=2))
        r = service.week_report(db, MON, "high", 8)
        assert r["total"] == 4
        assert r["delta_vs_prev"] == 2
        assert r["top"] == {"label": "Work", "hours": 3}
        assert r["least"] == {"label": "Personal", "hours": 1}
        assert r["has_history"] is True
        assert [t["hours"] for t in r["trend"]] == [2, 4]
        work = next(c for c in r["comparison"] if c["label"] == "Work")
        assert work["avg"] == 2 and work["diff"] == 1 and work["pct"] == 50
        personal = next(c for c in r["comparison"] if c["label"] == "Personal")
        assert personal["pct"] is None  # no history for it: NaN becomes null, not a JSON error

    @pytest.mark.parametrize("level,history", [("mid", 8), ("high", 1), ("low", 27)])
    def test_bad_options(self, db, level, history):
        with pytest.raises(UserError):
            service.week_report(db, MON, level, history)

    def test_csv(self, db, subj):
        db.add_entry(TimeEntry(date=MON, subject_id=subj.id, duration_hours=1))
        assert "Reading" in service.week_csv(db, MON)


class TestReflectionAndGoals:
    def test_reflection_roundtrip(self, db):
        assert service.reflection(db, MON)["saved"] is False
        service.save_reflection(db, MON, {"strengths": "s", "weaknesses": "w", "plan": "p"})
        r = service.reflection(db, MON)
        assert (r["strengths"], r["weaknesses"], r["plan"], r["saved"]) == ("s", "w", "p", True)

    def test_goals_for_next_week_listed(self, db, subj):
        service.add_goal(db, MON + timedelta(weeks=1), {"description": "Read", "target_hours": 5, "subject_id": subj.id})
        r = service.reflection(db, MON)
        assert r["next_week_start"] == "2026-09-21"
        assert [g["description"] for g in r["next_goals"]] == ["Read"]

    def test_goal_zero_target_is_qualitative(self, db):
        gid = service.add_goal(db, MON, {"description": "Be kind", "target_hours": 0})["id"]
        assert db.get_goals_for_week(MON)[0].target_hours is None
        service.delete_goal(db, gid)
        assert db.get_goals_for_week(MON) == []

    def test_goal_needs_description(self, db):
        with pytest.raises(UserError):
            service.add_goal(db, MON, {"description": "  "})

    def test_review_suggests_and_summarises(self, db, subj):
        g1 = db.add_goal(Goal(week_start=MON, description="Read", target_hours=4, subject_id=subj.id))
        g2 = db.add_goal(Goal(week_start=MON, description="Rest"))
        db.add_entry(TimeEntry(date=MON, subject_id=subj.id, duration_hours=3))
        r = service.goal_review(db, MON)
        by_id = {g["id"]: g for g in r["goals"]}
        assert by_id[g1.id]["actual_hours"] == 3
        assert by_id[g1.id]["suggested"] == 2  # partial: 3 >= 0.75 * 4
        assert by_id[g2.id]["suggested"] is None
        assert r["summary"] is None

        service.save_outcome(db, g1.id, {"met": 1, "actual_hours": 3, "notes": "ok"})
        s = service.goal_review(db, MON)["summary"]
        assert (s["evaluated"], s["total"], s["verdict"]) == (1, 2, None)
        service.save_outcome(db, g2.id, {"met": 0})
        assert "50%" in service.goal_review(db, MON)["summary"]["verdict"]

    def test_outcome_validation(self, db):
        g = db.add_goal(Goal(week_start=MON, description="x"))
        with pytest.raises(UserError):
            service.save_outcome(db, g.id, {"met": 5})


class TestExportPrompt:
    def test_first_run_offers_last_week_only(self, db, subj):
        db.add_entry(TimeEntry(date=MON - timedelta(weeks=3), subject_id=subj.id, duration_hours=1))
        db.add_entry(TimeEntry(date=MON, subject_id=subj.id, duration_hours=1))
        p = service.pending_export(db, today=MON + timedelta(weeks=1, days=2))
        assert p == {"week_start": "2026-09-14", "week_end": "2026-09-20", "more": 0}

    def test_export_writes_file_and_is_not_asked_again(self, db, subj, tmp_path):
        db.add_entry(TimeEntry(date=MON, subject_id=subj.id, duration_hours=1))
        today = MON + timedelta(weeks=1)
        assert service.pending_export(db, today) is not None
        path = service.export_week(db, tmp_path / "exports", MON)
        assert path.endswith("time_report_2026-09-14.xlsx")
        assert service.pending_export(db, today) is None

    def test_skip(self, db, subj):
        db.add_entry(TimeEntry(date=MON, subject_id=subj.id, duration_hours=1))
        today = MON + timedelta(weeks=1)
        service.pending_export(db, today)
        service.skip_export(db, MON)
        assert service.pending_export(db, today) is None
