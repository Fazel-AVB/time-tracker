"""
End-of-week Excel report: which finished weeks still need the export prompt,
and the .xlsx content for one week.

No Streamlit imports (the prompt UI is tracker/export_prompt.py), so both
functions are unit-tested in tests/test_week_report.py. The workbook is what
history_exports/time_report_<monday>.xlsx contains.
"""
from __future__ import annotations

import io
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd

from tracker.analytics import (
    _DAY_ABBR,
    aggregate_by_label,
    aggregate_by_subject,
    entries_to_df,
    evaluate_goals,
    week_monday,
    week_pivot,
)
from tracker.models import Goal, GoalOutcome, Reflection, TimeEntry

_MET_LABELS = {0: "Not met", 1: "Met", 2: "Partial"}  # same codes as models.GoalOutcome.met


def pending_export_weeks(
    today: date,
    since: date,
    weeks_with_entries: Iterable[date],
    decided: Iterable[date],
) -> List[date]:
    """
    Mondays of weeks that have ended (Sunday is over), start on/after `since`,
    have at least one entry, and have not been exported or skipped yet.
    Oldest first. `since` stops the prompt from asking about the whole history
    the first time the feature runs.
    """
    current_week = week_monday(today)
    decided = set(decided)
    return sorted(
        w for w in set(weeks_with_entries)
        if since <= w < current_week and w not in decided
    )


def report_filename(week_start: date) -> str:
    return f"time_report_{week_start.isoformat()}.xlsx"


def report_path(export_dir: str, week_start: date) -> Path:
    return Path(export_dir) / report_filename(week_start)


def _hours_table(df: pd.DataFrame, first_col: str) -> pd.DataFrame:
    out = df.copy()
    out.columns = [first_col, "Hours"]
    out["Hours"] = out["Hours"].astype(float).round(2)
    return out


def build_week_report_xlsx(
    week_start: date,
    entries: List[TimeEntry],
    reflection: Optional[Reflection] = None,
    goals: Optional[List[Goal]] = None,
    outcomes: Optional[dict] = None,
) -> bytes:
    """
    Build the week's report workbook and return it as bytes.
    entries:  that week's entries (TimesheetDB.get_entries_for_week).
    goals:    goals whose week_start is this week (set the week before).
    outcomes: {goal_id: GoalOutcome} for those goals, where evaluated.
    Sheets: Weekly Table, By High Label, By Low Label, By Subject, Entries,
    and Reflection / Goals when there is something to put in them.
    """
    goals = goals or []
    outcomes = outcomes or {}

    table = week_pivot(entries, week_start)
    if not table.empty:
        totals = {c: table[c].sum() for c in _DAY_ABBR + ["Total"]}
        table = pd.concat(
            [table, pd.DataFrame([{"Subject": "DAILY TOTAL", "Low Label": "", "High Label": "", **totals}])],
            ignore_index=True,
        )
        table[_DAY_ABBR + ["Total"]] = table[_DAY_ABBR + ["Total"]].astype(float).round(2)

    raw = entries_to_df(entries)
    entries_sheet = pd.DataFrame({
        "Date": raw["date"],
        "Subject": raw["subject_name"],
        "Low Label": raw["low_level_label"],
        "High Label": raw["high_level_label"],
        "Hours": raw["duration_hours"].astype(float).round(2),
        "Notes": raw["notes"],
    }).sort_values(["Date", "Subject"]) if not raw.empty else pd.DataFrame(
        columns=["Date", "Subject", "Low Label", "High Label", "Hours", "Notes"])

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        table.to_excel(writer, index=False, sheet_name="Weekly Table")
        _hours_table(aggregate_by_label(entries, "high"), "High Label").to_excel(
            writer, index=False, sheet_name="By High Label")
        _hours_table(aggregate_by_label(entries, "low"), "Low Label").to_excel(
            writer, index=False, sheet_name="By Low Label")
        _hours_table(aggregate_by_subject(entries), "Subject").to_excel(
            writer, index=False, sheet_name="By Subject")
        entries_sheet.to_excel(writer, index=False, sheet_name="Entries")

        if reflection is not None:
            pd.DataFrame({
                "Field": ["Strengths", "Weaknesses", "Plan for next week"],
                "Text": [reflection.strengths, reflection.weaknesses, reflection.next_week_plan],
            }).to_excel(writer, index=False, sheet_name="Reflection")

        if goals:
            rows = []
            for item in evaluate_goals(goals, entries):
                g = item["goal"]
                o: Optional[GoalOutcome] = outcomes.get(g.id)
                rows.append({
                    "Goal": g.description,
                    "Target hours": g.target_hours,
                    "Subject": g.subject_name or "",
                    "Logged hours": item["actual_hours"],
                    "Outcome": _MET_LABELS.get(o.met, "") if o else "Not evaluated",
                    "Evaluation notes": o.notes if o else "",
                })
            pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="Goals")

    return buf.getvalue()
