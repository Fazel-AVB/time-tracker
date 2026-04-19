"""
Pure aggregation and analytics functions.
No Streamlit imports here — only pandas and standard library.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

import pandas as pd

from tracker.models import Goal, TimeEntry


# ------------------------------------------------------------------ #
# Utilities
# ------------------------------------------------------------------ #

def week_monday(d: date) -> date:
    """Return the Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def fmt_hours(h: float) -> str:
    """Format a float number of hours as 'Xh YYm'."""
    if h == 0:
        return "—"
    total_min = round(h * 60)
    hours, mins = divmod(total_min, 60)
    if hours and mins:
        return f"{hours}h {mins:02d}m"
    elif hours:
        return f"{hours}h"
    else:
        return f"{mins}m"


def entries_to_df(entries: List[TimeEntry]) -> pd.DataFrame:
    """Convert a list of TimeEntry objects to a flat DataFrame."""
    if not entries:
        return pd.DataFrame(columns=[
            "id", "date", "subject_id", "subject_name",
            "low_level_label", "high_level_label",
            "duration_hours", "notes",
        ])
    return pd.DataFrame([{
        "id": e.id,
        "date": e.date,
        "subject_name": e.subject_name or "Unknown",
        "low_level_label": e.low_level_label or "Unknown",
        "high_level_label": e.high_level_label or "Unknown",
        "duration_hours": e.duration_hours,
        "notes": e.notes,
        "subject_id": e.subject_id,
    } for e in entries])


# ------------------------------------------------------------------ #
# Weekly pivot table  (Page 1)
# ------------------------------------------------------------------ #

_DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def week_pivot(entries: List[TimeEntry], week_start: date) -> pd.DataFrame:
    """
    Produce a pivot table with one row per (subject, labels) and columns
    for each weekday.  Used by the weekly activity table page.
    """
    day_map = {week_start + timedelta(days=i): _DAY_ABBR[i] for i in range(7)}

    if not entries:
        return pd.DataFrame(
            columns=["Subject", "Low Label", "High Label"] + _DAY_ABBR + ["Total"]
        )

    df = entries_to_df(entries)
    df["day"] = df["date"].map(day_map)
    df = df[df["day"].notna()]

    pivot = df.pivot_table(
        index=["subject_name", "low_level_label", "high_level_label"],
        columns="day",
        values="duration_hours",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()
    pivot.columns.name = None

    pivot = pivot.rename(columns={
        "subject_name": "Subject",
        "low_level_label": "Low Label",
        "high_level_label": "High Label",
    })

    for day in _DAY_ABBR:
        if day not in pivot.columns:
            pivot[day] = 0.0

    pivot = pivot[["Subject", "Low Label", "High Label"] + _DAY_ABBR]
    pivot["Total"] = pivot[_DAY_ABBR].sum(axis=1)
    return pivot.sort_values("Total", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------------ #
# Aggregation  (Pages 2 + 4)
# ------------------------------------------------------------------ #

def aggregate_by_label(entries: List[TimeEntry], level: str = "high") -> pd.DataFrame:
    """
    Total hours by label for a list of entries.
    level: "high" or "low"
    Returns DataFrame with columns [label, total_hours].
    """
    if not entries:
        return pd.DataFrame(columns=["label", "total_hours"])

    df = entries_to_df(entries)
    col = "high_level_label" if level == "high" else "low_level_label"
    result = df.groupby(col)["duration_hours"].sum().reset_index()
    result.columns = ["label", "total_hours"]
    return result.sort_values("total_hours", ascending=False).reset_index(drop=True)


def aggregate_by_subject(entries: List[TimeEntry]) -> pd.DataFrame:
    """
    Total hours per subject for a list of entries.
    Returns DataFrame with columns [subject_name, total_hours].
    """
    if not entries:
        return pd.DataFrame(columns=["subject_name", "total_hours"])

    df = entries_to_df(entries)
    result = df.groupby("subject_name")["duration_hours"].sum().reset_index()
    result.columns = ["subject_name", "total_hours"]
    return result.sort_values("total_hours", ascending=False).reset_index(drop=True)


def weekly_totals_over_range(entries: List[TimeEntry]) -> pd.DataFrame:
    """
    Total hours per week over a multi-week entry list.
    Returns DataFrame with columns [week_start, total_hours].
    """
    if not entries:
        return pd.DataFrame(columns=["week_start", "total_hours"])

    df = entries_to_df(entries)
    df["week_start"] = df["date"].map(week_monday)
    result = df.groupby("week_start")["duration_hours"].sum().reset_index()
    result.columns = ["week_start", "total_hours"]
    return result.sort_values("week_start")


def label_averages_over_range(entries: List[TimeEntry], level: str = "high") -> pd.DataFrame:
    """
    Average weekly hours per label over all weeks present in entries.
    Weeks with zero hours for a label are counted as 0 in the average.
    Returns DataFrame with columns [label, avg_hours_per_week, n_weeks].
    """
    if not entries:
        return pd.DataFrame(columns=["label", "avg_hours_per_week", "n_weeks"])

    df = entries_to_df(entries)
    col = "high_level_label" if level == "high" else "low_level_label"
    df["week_start"] = df["date"].map(week_monday)

    weekly = df.groupby(["week_start", col])["duration_hours"].sum().reset_index()
    weekly.columns = ["week_start", "label", "hours"]

    n_weeks = weekly["week_start"].nunique()

    totals = weekly.groupby("label")["hours"].sum().reset_index()
    totals.columns = ["label", "total_hours"]
    totals["avg_hours_per_week"] = totals["total_hours"] / n_weeks
    totals["n_weeks"] = n_weeks

    return totals[["label", "avg_hours_per_week", "n_weeks"]].sort_values(
        "avg_hours_per_week", ascending=False
    ).reset_index(drop=True)


def compare_to_averages(current: pd.DataFrame, averages: pd.DataFrame) -> pd.DataFrame:
    """
    Merge current-week totals with long-term averages and compute deltas.
    current:  [label, total_hours]
    averages: [label, avg_hours_per_week, n_weeks]
    Returns:  [label, total_hours, avg_hours_per_week, diff_hours, pct_diff]
    """
    merged = current.merge(averages[["label", "avg_hours_per_week"]], on="label", how="outer").fillna(0)
    merged["diff_hours"] = merged["total_hours"] - merged["avg_hours_per_week"]
    merged["pct_diff"] = merged.apply(
        lambda r: (r["diff_hours"] / r["avg_hours_per_week"] * 100)
        if r["avg_hours_per_week"] > 0 else float("nan"),
        axis=1,
    )
    return merged.sort_values("total_hours", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------------ #
# Goal evaluation  (Page 4)
# ------------------------------------------------------------------ #

def evaluate_goals(goals: list, entries: List[TimeEntry]) -> list[dict]:
    """
    For each goal that is linked to a subject, look up actual hours from entries.
    Returns a list of dicts: {goal, actual_hours (or None if not subject-linked)}.
    """
    subject_hours: dict[int, float] = {}
    for e in entries:
        subject_hours[e.subject_id] = subject_hours.get(e.subject_id, 0.0) + e.duration_hours

    return [
        {
            "goal": g,
            "actual_hours": subject_hours.get(g.subject_id) if g.subject_id else None,
        }
        for g in goals
    ]


# ------------------------------------------------------------------ #
# Narrative summary  (Page 2)
# ------------------------------------------------------------------ #

def narrative_summary(
    entries: List[TimeEntry],
    avg_df: Optional[pd.DataFrame] = None,
    level: str = "high",
) -> str:
    """
    Generate a short plain-text narrative for the weekly report.
    avg_df: output of label_averages_over_range (may be None if no history).
    """
    if not entries:
        return "No time entries recorded for this week."

    df = entries_to_df(entries)
    total = df["duration_hours"].sum()
    col = "high_level_label" if level == "high" else "low_level_label"
    by_label = df.groupby(col)["duration_hours"].sum().sort_values(ascending=False)

    top_label = by_label.index[0]
    top_h = by_label.iloc[0]
    least_label = by_label.index[-1] if len(by_label) > 1 else None
    least_h = by_label.iloc[-1] if len(by_label) > 1 else None

    h = int(total)
    m = round((total - h) * 60)
    total_str = f"{h}h {m:02d}m" if h else f"{m}m"

    lines = [
        f"You logged {total_str} of tracked time this week across {len(by_label)} "
        f"{'category' if len(by_label) == 1 else 'categories'}.",
        f"{top_label} received the most attention ({top_h:.1f}h).",
    ]
    if least_label and least_label != top_label:
        lines.append(f"{least_label} received the least attention ({least_h:.1f}h).")

    if avg_df is not None and not avg_df.empty:
        current_df = pd.DataFrame({"label": by_label.index, "total_hours": by_label.values})
        comp = compare_to_averages(current_df, avg_df)
        above = comp[comp["diff_hours"] > 0.5]["label"].tolist()
        below = comp[comp["diff_hours"] < -0.5]["label"].tolist()
        if above:
            lines.append(f"Above long-term average: {', '.join(above)}.")
        if below:
            lines.append(f"Below long-term average: {', '.join(below)}.")

    return "  ".join(lines)
