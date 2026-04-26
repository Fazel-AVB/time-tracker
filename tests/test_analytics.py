"""Unit tests for tracker/analytics.py — pure aggregation functions."""

import pytest
from datetime import date, timedelta

import pandas as pd

from tracker.analytics import (
    aggregate_by_label,
    aggregate_by_subject,
    compare_to_averages,
    entries_to_df,
    evaluate_goals,
    fmt_hours,
    label_averages_over_range,
    narrative_summary,
    week_monday,
    week_pivot,
    weekly_totals_over_range,
)
from tracker.models import Goal, TimeEntry


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def make_entry(subject_name, hours, day_offset=0, week_start=date(2026, 4, 20),
               subject_id=1, low="low", high="high"):
    return TimeEntry(
        id=None,
        date=week_start + timedelta(days=day_offset),
        subject_id=subject_id,
        duration_hours=hours,
        subject_name=subject_name,
        low_level_label=low,
        high_level_label=high,
    )


MONDAY = date(2026, 4, 20)  # confirmed Monday


# ------------------------------------------------------------------ #
# fmt_hours
# ------------------------------------------------------------------ #

class TestFmtHours:
    def test_zero_returns_dash(self):
        assert fmt_hours(0) == "—"

    def test_whole_hours(self):
        assert fmt_hours(3) == "3h"

    def test_minutes_only(self):
        assert fmt_hours(0.5) == "30m"

    def test_hours_and_minutes(self):
        assert fmt_hours(1.5) == "1h 30m"

    def test_rounds_to_nearest_minute(self):
        result = fmt_hours(1.0 / 60)  # exactly 1 minute
        assert "1m" in result


# ------------------------------------------------------------------ #
# week_monday
# ------------------------------------------------------------------ #

class TestWeekMonday:
    def test_monday_returns_itself(self):
        assert week_monday(date(2026, 4, 20)) == date(2026, 4, 20)

    def test_wednesday_returns_monday(self):
        assert week_monday(date(2026, 4, 22)) == date(2026, 4, 20)

    def test_sunday_returns_monday(self):
        assert week_monday(date(2026, 4, 26)) == date(2026, 4, 20)


# ------------------------------------------------------------------ #
# entries_to_df
# ------------------------------------------------------------------ #

class TestEntriesToDf:
    def test_empty_returns_correct_columns(self):
        df = entries_to_df([])
        assert "subject_name" in df.columns
        assert "duration_hours" in df.columns
        assert len(df) == 0

    def test_converts_entries(self):
        entries = [make_entry("Reading", 2.0), make_entry("Coding", 3.0)]
        df = entries_to_df(entries)
        assert len(df) == 2
        assert set(df["subject_name"]) == {"Reading", "Coding"}


# ------------------------------------------------------------------ #
# week_pivot
# ------------------------------------------------------------------ #

class TestWeekPivot:
    def test_empty_entries_returns_empty_df(self):
        df = week_pivot([], MONDAY)
        assert len(df) == 0
        assert "Mon" in df.columns

    def test_single_entry_appears_in_correct_day(self):
        entries = [make_entry("Reading", 2.0, day_offset=0)]  # Monday
        df = week_pivot(entries, MONDAY)
        assert df.loc[0, "Mon"] == 2.0
        assert df.loc[0, "Tue"] == 0.0

    def test_total_column_is_sum_of_days(self):
        entries = [
            make_entry("Reading", 1.0, day_offset=0),
            make_entry("Reading", 2.0, day_offset=1),
        ]
        df = week_pivot(entries, MONDAY)
        assert df.loc[0, "Total"] == 3.0

    def test_sorted_by_high_label_then_low_label(self):
        entries = [
            make_entry("B", 5.0, subject_id=2, low="b", high="Z"),
            make_entry("A", 1.0, subject_id=1, low="a", high="A"),
        ]
        df = week_pivot(entries, MONDAY)
        assert df.iloc[0]["Subject"] == "A"  # "A" high label comes before "Z"

    def test_missing_days_filled_with_zero(self):
        entries = [make_entry("Reading", 1.0, day_offset=2)]  # Wednesday only
        df = week_pivot(entries, MONDAY)
        assert df.loc[0, "Mon"] == 0.0
        assert df.loc[0, "Wed"] == 1.0
        assert df.loc[0, "Sun"] == 0.0


# ------------------------------------------------------------------ #
# aggregate_by_label
# ------------------------------------------------------------------ #

class TestAggregateByLabel:
    def test_empty_returns_empty(self):
        df = aggregate_by_label([])
        assert len(df) == 0

    def test_high_level_grouping(self):
        entries = [
            make_entry("A", 2.0, high="Work"),
            make_entry("B", 3.0, high="Work"),
            make_entry("C", 1.0, high="Personal"),
        ]
        df = aggregate_by_label(entries, level="high")
        work_row = df[df["label"] == "Work"]
        assert work_row["total_hours"].values[0] == 5.0

    def test_low_level_grouping(self):
        entries = [
            make_entry("A", 1.0, low="coding"),
            make_entry("B", 2.0, low="reading"),
        ]
        df = aggregate_by_label(entries, level="low")
        assert len(df) == 2

    def test_sorted_descending(self):
        entries = [
            make_entry("A", 1.0, high="X"),
            make_entry("B", 5.0, high="Y"),
        ]
        df = aggregate_by_label(entries, level="high")
        assert df.iloc[0]["label"] == "Y"


# ------------------------------------------------------------------ #
# aggregate_by_subject
# ------------------------------------------------------------------ #

class TestAggregateBySubject:
    def test_sums_per_subject(self):
        entries = [
            make_entry("Reading", 1.0),
            make_entry("Reading", 2.0),
            make_entry("Coding", 4.0),
        ]
        df = aggregate_by_subject(entries)
        reading = df[df["subject_name"] == "Reading"]["total_hours"].values[0]
        assert reading == 3.0

    def test_empty_returns_empty(self):
        df = aggregate_by_subject([])
        assert len(df) == 0


# ------------------------------------------------------------------ #
# weekly_totals_over_range
# ------------------------------------------------------------------ #

class TestWeeklyTotalsOverRange:
    def test_totals_per_week(self):
        w1 = MONDAY
        w2 = MONDAY + timedelta(weeks=1)
        entries = [
            make_entry("A", 10.0, week_start=w1),
            make_entry("A", 5.0, week_start=w2),
        ]
        df = weekly_totals_over_range(entries)
        assert len(df) == 2
        assert df[df["week_start"] == w1]["total_hours"].values[0] == 10.0

    def test_empty_returns_empty(self):
        df = weekly_totals_over_range([])
        assert len(df) == 0


# ------------------------------------------------------------------ #
# label_averages_over_range
# ------------------------------------------------------------------ #

class TestLabelAveragesOverRange:
    def test_average_across_two_weeks(self):
        w1 = MONDAY
        w2 = MONDAY + timedelta(weeks=1)
        entries = [
            make_entry("A", 4.0, high="Work", week_start=w1),
            make_entry("A", 6.0, high="Work", week_start=w2),
        ]
        df = label_averages_over_range(entries, level="high")
        avg = df[df["label"] == "Work"]["avg_hours_per_week"].values[0]
        assert avg == pytest.approx(5.0)

    def test_n_weeks_is_correct(self):
        w1, w2, w3 = MONDAY, MONDAY + timedelta(weeks=1), MONDAY + timedelta(weeks=2)
        entries = [
            make_entry("A", 1.0, high="Work", week_start=w1),
            make_entry("A", 1.0, high="Work", week_start=w2),
            make_entry("A", 1.0, high="Work", week_start=w3),
        ]
        df = label_averages_over_range(entries, level="high")
        assert df.iloc[0]["n_weeks"] == 3


# ------------------------------------------------------------------ #
# compare_to_averages
# ------------------------------------------------------------------ #

class TestCompareToAverages:
    def test_diff_hours_computed(self):
        current = pd.DataFrame({"label": ["Work"], "total_hours": [8.0]})
        averages = pd.DataFrame({"label": ["Work"], "avg_hours_per_week": [6.0], "n_weeks": [4]})
        result = compare_to_averages(current, averages)
        assert result[result["label"] == "Work"]["diff_hours"].values[0] == pytest.approx(2.0)

    def test_pct_diff_computed(self):
        current = pd.DataFrame({"label": ["Work"], "total_hours": [10.0]})
        averages = pd.DataFrame({"label": ["Work"], "avg_hours_per_week": [8.0], "n_weeks": [4]})
        result = compare_to_averages(current, averages)
        pct = result[result["label"] == "Work"]["pct_diff"].values[0]
        assert pct == pytest.approx(25.0)

    def test_new_label_not_in_averages_filled_zero(self):
        current = pd.DataFrame({"label": ["NewLabel"], "total_hours": [3.0]})
        averages = pd.DataFrame({"label": ["OtherLabel"], "avg_hours_per_week": [5.0], "n_weeks": [2]})
        result = compare_to_averages(current, averages)
        new_row = result[result["label"] == "NewLabel"]
        assert new_row["avg_hours_per_week"].values[0] == 0.0


# ------------------------------------------------------------------ #
# evaluate_goals
# ------------------------------------------------------------------ #

class TestEvaluateGoals:
    def test_subject_linked_goal_gets_actual_hours(self):
        goal = Goal(id=1, week_start=MONDAY, description="Read", subject_id=1)
        entry = make_entry("Reading", 3.0, subject_id=1)
        result = evaluate_goals([goal], [entry])
        assert result[0]["actual_hours"] == 3.0

    def test_unlinked_goal_has_none_actual_hours(self):
        goal = Goal(id=1, week_start=MONDAY, description="Meditate", subject_id=None)
        entry = make_entry("Reading", 3.0, subject_id=1)
        result = evaluate_goals([goal], [entry])
        assert result[0]["actual_hours"] is None

    def test_linked_goal_with_no_entries_is_zero(self):
        goal = Goal(id=1, week_start=MONDAY, description="Read", subject_id=99)
        result = evaluate_goals([goal], [])
        assert result[0]["actual_hours"] is None

    def test_multiple_entries_summed_for_subject(self):
        goal = Goal(id=1, week_start=MONDAY, description="Code", subject_id=1)
        entries = [
            make_entry("Coding", 2.0, subject_id=1),
            make_entry("Coding", 3.0, subject_id=1),
        ]
        result = evaluate_goals([goal], entries)
        assert result[0]["actual_hours"] == 5.0


# ------------------------------------------------------------------ #
# narrative_summary
# ------------------------------------------------------------------ #

class TestNarrativeSummary:
    def test_empty_entries_returns_message(self):
        result = narrative_summary([])
        assert "No time entries" in result

    def test_contains_total_hours(self):
        entries = [make_entry("Reading", 3.0)]
        result = narrative_summary(entries)
        assert "3h" in result

    def test_mentions_top_activity(self):
        entries = [
            make_entry("Reading", 5.0, high="Personal"),
            make_entry("Coding", 2.0, high="Work"),
        ]
        result = narrative_summary(entries, level="high")
        assert "Personal" in result

    def test_with_averages_mentions_above_below(self):
        entries = [make_entry("Reading", 10.0, high="Personal")]
        avg_df = pd.DataFrame({
            "label": ["Personal"],
            "avg_hours_per_week": [5.0],
            "n_weeks": [4],
        })
        result = narrative_summary(entries, avg_df=avg_df, level="high")
        assert "Above" in result
