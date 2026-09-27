"""What each part of the app does, as plain functions on a TimesheetDB.

The web layer (tracker/web/app.py) only parses requests and calls these;
every rule about the data lives here or in analytics.py, so it is
unit-tested without a browser (tests/test_service.py). Functions return
JSON-ready dicts (dates as ISO strings).

Raise UserError for anything the person can fix (empty name, 30 hours in a
day); the web layer shows its message as-is.
"""
from __future__ import annotations

import io
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from tracker.analytics import (
    _DAY_ABBR,
    aggregate_by_label,
    aggregate_by_subject,
    compare_to_averages,
    entries_to_df,
    evaluate_goals,
    label_averages_over_range,
    narrative_summary,
    suggest_goal_status,
    table_subjects,
    week_monday,
    weekly_totals_over_range,
)
from tracker import paths
from tracker.database import TimesheetDB
from tracker.excel_import import ExcelImportError, ImportedEntry, WeekNeeded, parse_workbook
from tracker.models import Goal, GoalOutcome, Reflection, Subject, TimeEntry
from tracker.seasonal import season_theme
from tracker.suggestions import (
    HIDDEN_SETTING_KEY,
    SUGGESTION_FIELDS,
    build_suggestions,
    canonical_value,
    hide_value,
    parse_hidden,
    unhide_values,
)
from tracker.week_report import build_week_report_xlsx, pending_export_weeks, report_path

MAX_DAY_HOURS = 24.0
MAX_GOAL_HOURS = 168.0
MET_LABELS = {0: "Not met", 1: "Met", 2: "Partial"}  # same codes as models.GoalOutcome.met
# settings key: the Monday from which finished weeks are eligible for the export prompt.
EXPORT_SINCE_KEY = "export_prompt_since"


class UserError(ValueError):
    """A problem the person can fix; the message is shown on the page."""


def parse_week(value: Optional[str]) -> date:
    """The Monday of the week containing the given ISO date (today if None)."""
    if not value:
        return week_monday(date.today())
    try:
        return week_monday(date.fromisoformat(value))
    except ValueError as e:
        raise UserError(f"Not a date: {value!r}") from e


def _hours(value, limit: float, what: str = "Hours") -> float:
    try:
        h = float(value)
    except (TypeError, ValueError) as e:
        raise UserError(f"{what} must be a number") from e
    if not 0 <= h <= limit:
        raise UserError(f"{what} must be between 0 and {limit:g}")
    return round(h, 4)


def _subject_json(s: Subject) -> dict:
    return {"id": s.id, "name": s.name, "low": s.low_level_label, "high": s.high_level_label,
            "label": f"{s.name} · {s.low_level_label}"}


def _entry_json(e: TimeEntry) -> dict:
    return {"id": e.id, "subject_id": e.subject_id, "subject": e.subject_name, "low": e.low_level_label,
            "date": e.date.isoformat(), "hours": e.duration_hours, "notes": e.notes}


def _week_json(week_start: date) -> dict:
    return {"week_start": week_start.isoformat(), "week_end": (week_start + timedelta(days=6)).isoformat(),
            "season": season_theme(week_start)}


# ------------------------------------------------------------------ #
# Weekly table
# ------------------------------------------------------------------ #

def week_table(db: TimesheetDB, week_start: date) -> dict:
    """Everything the Weekly Table tab shows for one week."""
    subjects = db.get_all_subjects()
    entries = db.get_entries_for_week(week_start)
    prev_entries = db.get_entries_for_week(week_start - timedelta(weeks=1))
    hidden = parse_hidden(db.get_setting(HIDDEN_SETTING_KEY))

    # Row selection rules live in analytics.table_subjects (unit-tested).
    shown = table_subjects(
        subjects,
        this_week_ids={e.subject_id for e in entries},
        prev_week_ids={e.subject_id for e in prev_entries},
        pinned_ids=db.get_pinned_subject_ids(week_start),
        excluded_ids=db.get_excluded_subject_ids(week_start),
    )
    hours = {}  # (subject_id, weekday) -> hours
    for e in entries:
        k = (e.subject_id, (e.date - week_start).days)
        hours[k] = hours.get(k, 0.0) + e.duration_hours

    rows = []
    for s in shown:
        days = [round(hours.get((s.id, i), 0.0), 2) for i in range(7)]
        rows.append({**_subject_json(s), "days": days, "total": round(sum(days), 2)})
    # Rows with hours sorted by (High, Low) like the Excel report
    # (analytics.week_pivot); rows without hours keep their order at the
    # bottom, so a row just added doesn't jump away.
    with_hours = sorted((r for r in rows if r["total"] > 0), key=lambda r: (r["high"], r["low"]))
    rows = with_hours + [r for r in rows if r["total"] <= 0]

    day_totals = [round(sum(r["days"][i] for r in rows), 2) for i in range(7)]
    usage = db.get_subject_usage()
    return {
        **_week_json(week_start),
        "days": [{"abbr": _DAY_ABBR[i], "date": (week_start + timedelta(days=i)).isoformat()} for i in range(7)],
        "rows": rows,
        "day_totals": day_totals,
        "week_total": round(sum(day_totals), 2),
        "subjects": [
            {**_subject_json(s), "entries": usage.get(s.id, (0, 0.0))[0], "hours": round(usage.get(s.id, (0, 0.0))[1], 2)}
            for s in sorted(subjects, key=lambda s: (s.name.casefold(), s.low_level_label.casefold(),
                                                     s.high_level_label.casefold()))
        ],
        "suggestions": build_suggestions(subjects, hidden),
        "entries": [_entry_json(e) for e in entries],
    }


def set_day_hours(db: TimesheetDB, week_start: date, subject_id: int, day: int, value) -> None:
    """Set the total hours of one table cell (one subject on one day).

    A cell shows the sum of that day's entries. One entry is updated in
    place (keeping its note); several are replaced by one entry that keeps
    their notes joined, so the cell shows exactly the typed value.
    """
    if not 0 <= int(day) <= 6:
        raise UserError("day must be 0 (Monday) to 6 (Sunday)")
    if db.get_subject(subject_id) is None:
        raise UserError("That subject no longer exists. Reload the page.")
    h = _hours(value, MAX_DAY_HOURS)
    d = week_start + timedelta(days=int(day))
    existing = [e for e in db.get_entries_for_week(week_start) if e.subject_id == subject_id and e.date == d]
    if len(existing) == 1 and h > 0:
        e = existing[0]
        db.update_entry(TimeEntry(id=e.id, date=d, subject_id=subject_id, duration_hours=h, notes=e.notes))
    else:
        for e in existing:
            db.delete_entry(e.id)
        if h > 0:
            notes = "; ".join(e.notes for e in existing if e.notes)
            db.add_entry(TimeEntry(date=d, subject_id=subject_id, duration_hours=h, notes=notes))
    # Typing hours into a row brings it back if it had been removed from this week.
    db.remove_week_exclusion(week_start, subject_id)


def _find_or_create_subject(db: TimesheetDB, name, low, high) -> Subject:
    """Snap each typed value onto an existing spelling (ignoring case), then
    reuse the subject with those three values or create it."""
    subjects = db.get_all_subjects()
    # All values, including ones hidden from the suggestions, so retyping a
    # hidden value reuses its spelling instead of starting a near-duplicate.
    all_values = build_suggestions(subjects)
    name = canonical_value(name, all_values["Subject"])
    low = canonical_value(low, all_values["Low Label"])
    high = canonical_value(high, all_values["High Label"])
    if not (name and low and high):
        raise UserError("Subject, Low Label and High Label are all required.")
    for s in subjects:
        if (s.name, s.low_level_label, s.high_level_label) == (name, low, high):
            subj = s
            break
    else:
        subj = db.add_subject(Subject(name=name, low_level_label=low, high_level_label=high))
    # Typing a hidden value again on purpose brings it back into the suggestions.
    hidden = parse_hidden(db.get_setting(HIDDEN_SETTING_KEY))
    db.set_setting(HIDDEN_SETTING_KEY, json.dumps(unhide_values(
        hidden, {"Subject": name, "Low Label": low, "High Label": high})))
    return subj


def add_row(db: TimesheetDB, week_start: date, name, low, high) -> dict:
    """Add a subject (new or existing) as a row of this week's table."""
    subj = _find_or_create_subject(db, name, low, high)
    # Re-adding a subject removed from this week must undo that removal.
    db.remove_week_exclusion(week_start, subj.id)
    # Pinned so the row shows before any hours are logged (see week_subject_pins).
    db.add_week_pin(week_start, subj.id)
    return _subject_json(subj)


def rename_row(db: TimesheetDB, week_start: date, subject_id: int, name, low, high) -> dict:
    """Retype a row's name or labels, for this week only.

    The row's hours this week move to the subject with the new values
    (created if needed); the old subject stays as it is in other weeks and
    leaves this week's table. Same effect as typing over a row in the old
    Streamlit table, but the entries are moved, so their notes survive.
    """
    old = db.get_subject(subject_id)
    if old is None:
        raise UserError("That subject no longer exists. Reload the page.")
    new = _find_or_create_subject(db, name, low, high)
    if new.id == old.id:
        return _subject_json(new)
    db.move_entries_in_week(old.id, new.id, week_start)
    db.remove_week_pin(week_start, old.id)
    db.add_week_exclusion(week_start, old.id)
    db.remove_week_exclusion(week_start, new.id)
    db.add_week_pin(week_start, new.id)
    return _subject_json(new)


def remove_row(db: TimesheetDB, week_start: date, subject_id: int) -> None:
    """Remove a row from this week's table: its hours this week are deleted, other weeks keep theirs."""
    db.delete_entries_for_subject_in_week(subject_id, week_start)
    db.remove_week_pin(week_start, subject_id)
    # Without the exclusion a subject used last week would reappear at once
    # (table_subjects shows last week's subjects too).
    db.add_week_exclusion(week_start, subject_id)


def hide_suggestion(db: TimesheetDB, column: str, value: str) -> None:
    """Remove a value from the New-subject suggestions; subjects using it are untouched."""
    if column not in SUGGESTION_FIELDS:
        raise UserError(f"Unknown column {column!r}")
    hidden = parse_hidden(db.get_setting(HIDDEN_SETTING_KEY))
    db.set_setting(HIDDEN_SETTING_KEY, json.dumps(hide_value(hidden, column, value)))


def delete_subject(db: TimesheetDB, subject_id: int) -> None:
    """Delete a subject in all weeks, with all its hours. Linked goals are kept but unlinked."""
    db.delete_subject_with_entries(subject_id)


def week_table_xlsx(db: TimesheetDB, week_start: date) -> bytes:
    """The table as shown (rows without hours included) as an Excel file."""
    view = week_table(db, week_start)
    df = pd.DataFrame(
        [{"Subject": r["name"], "Low Label": r["low"], "High Label": r["high"],
          **dict(zip(_DAY_ABBR, r["days"])), "Total": r["total"]} for r in view["rows"]],
        columns=["Subject", "Low Label", "High Label", *_DAY_ABBR, "Total"],
    )
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Weekly Table")
    return buf.getvalue()


# ------------------------------------------------------------------ #
# Entries (the Log time form and the entry list)
# ------------------------------------------------------------------ #

def _entry_fields(db: TimesheetDB, data: dict) -> tuple[date, int, float, str]:
    try:
        d = date.fromisoformat(str(data.get("date")))
        subject_id = int(data.get("subject_id"))
    except (TypeError, ValueError) as e:
        raise UserError("Pick a subject and a date") from e
    if db.get_subject(subject_id) is None:
        raise UserError("That subject no longer exists. Reload the page.")
    h = _hours(data.get("hours"), MAX_DAY_HOURS, "Duration")
    if h <= 0:
        raise UserError("Duration must be greater than 0")
    return d, subject_id, h, str(data.get("notes") or "").strip()


def add_entry(db: TimesheetDB, data: dict) -> dict:
    d, subject_id, h, notes = _entry_fields(db, data)
    e = db.add_entry(TimeEntry(date=d, subject_id=subject_id, duration_hours=h, notes=notes))
    # A logged entry brings the row back into a week it was removed from.
    db.remove_week_exclusion(week_monday(d), subject_id)
    return {"id": e.id}


def update_entry(db: TimesheetDB, entry_id: int, data: dict) -> None:
    if db.get_entry(entry_id) is None:
        raise UserError("That entry no longer exists. Reload the page.")
    d, subject_id, h, notes = _entry_fields(db, data)
    db.update_entry(TimeEntry(id=entry_id, date=d, subject_id=subject_id, duration_hours=h, notes=notes))
    db.remove_week_exclusion(week_monday(d), subject_id)


def delete_entry(db: TimesheetDB, entry_id: int) -> None:
    db.delete_entry(entry_id)


# ------------------------------------------------------------------ #
# Weekly report
# ------------------------------------------------------------------ #

def week_report(db: TimesheetDB, week_start: date, level: str = "high", history_weeks: int = 8) -> dict:
    """Numbers and chart data for the Weekly Report tab."""
    if level not in ("high", "low"):
        raise UserError("level must be high or low")
    if not 2 <= history_weeks <= 26:
        raise UserError("history must be 2 to 26 weeks")
    entries = db.get_entries_for_week(week_start)
    history = db.get_entries_for_range(week_start - timedelta(weeks=history_weeks), week_start)
    prev_total = sum(e.duration_hours for e in db.get_entries_for_week(week_start - timedelta(weeks=1)))
    out = {**_week_json(week_start), "level": level, "history_weeks": history_weeks, "has_entries": bool(entries)}
    if not entries:
        return out

    current = aggregate_by_label(entries, level=level)
    averages = label_averages_over_range(history, level=level)
    comparison = compare_to_averages(current, averages)
    total = sum(e.duration_hours for e in entries)
    trend = weekly_totals_over_range(history + entries)
    by_subject = aggregate_by_subject(entries)

    def num(x) -> Optional[float]:
        return None if pd.isna(x) else round(float(x), 2)

    out.update({
        "total": round(total, 2),
        "delta_vs_prev": round(total - prev_total, 2),
        "top": {"label": current.iloc[0]["label"], "hours": num(current.iloc[0]["total_hours"])},
        "least": ({"label": current.iloc[-1]["label"], "hours": num(current.iloc[-1]["total_hours"])}
                  if len(current) > 1 else None),
        "narrative": narrative_summary(entries, avg_df=averages if not averages.empty else None, level=level),
        "has_history": not averages.empty,
        "comparison": [
            {"label": r["label"], "hours": num(r["total_hours"]), "avg": num(r["avg_hours_per_week"]),
             "diff": num(r["diff_hours"]), "pct": num(r["pct_diff"])}
            for _, r in comparison.iterrows()
        ],
        "trend": [{"week_start": r["week_start"].isoformat(), "hours": num(r["total_hours"])}
                  for _, r in trend.iterrows()],
        "by_subject": [{"subject": r["subject_name"], "hours": num(r["total_hours"])}
                       for _, r in by_subject.iterrows()],
    })
    return out


def week_csv(db: TimesheetDB, week_start: date) -> str:
    return entries_to_df(db.get_entries_for_week(week_start)).to_csv(index=False)


# ------------------------------------------------------------------ #
# Reflection + goals for next week
# ------------------------------------------------------------------ #

def _goal_json(g: Goal) -> dict:
    return {"id": g.id, "week_start": g.week_start.isoformat(), "description": g.description,
            "target_hours": g.target_hours, "subject_id": g.subject_id, "subject": g.subject_name,
            "notes": g.notes}


def reflection(db: TimesheetDB, week_start: date) -> dict:
    r = db.get_reflection(week_start)
    next_week = week_start + timedelta(weeks=1)
    return {
        **_week_json(week_start),
        "strengths": r.strengths if r else "",
        "weaknesses": r.weaknesses if r else "",
        "plan": r.next_week_plan if r else "",
        "saved": r is not None,
        "next_week_start": next_week.isoformat(),
        "next_week_end": (next_week + timedelta(days=6)).isoformat(),
        "next_goals": [_goal_json(g) for g in db.get_goals_for_week(next_week)],
        "subjects": [_subject_json(s) for s in db.get_all_subjects()],
    }


def save_reflection(db: TimesheetDB, week_start: date, data: dict) -> None:
    db.upsert_reflection(Reflection(
        week_start=week_start,
        strengths=str(data.get("strengths") or ""),
        weaknesses=str(data.get("weaknesses") or ""),
        next_week_plan=str(data.get("plan") or ""),
    ))


def add_goal(db: TimesheetDB, week_start: date, data: dict) -> dict:
    """Add a goal FOR week_start (the Reflection tab passes the week after the one shown)."""
    desc = str(data.get("description") or "").strip()
    if not desc:
        raise UserError("Goal description is required")
    target = data.get("target_hours")
    target = _hours(target, MAX_GOAL_HOURS, "Target hours") if target not in (None, "") else None
    subject_id = data.get("subject_id")
    subject_id = int(subject_id) if subject_id not in (None, "") else None
    if subject_id is not None and db.get_subject(subject_id) is None:
        raise UserError("That subject no longer exists. Reload the page.")
    g = db.add_goal(Goal(week_start=week_start, description=desc, target_hours=target or None,
                         subject_id=subject_id, notes=str(data.get("notes") or "").strip()))
    return {"id": g.id}


def delete_goal(db: TimesheetDB, goal_id: int) -> None:
    db.delete_goal(goal_id)


# ------------------------------------------------------------------ #
# Goal review
# ------------------------------------------------------------------ #

def goal_review(db: TimesheetDB, week_start: date) -> dict:
    goals = db.get_goals_for_week(week_start)
    entries = db.get_entries_for_week(week_start)
    outcomes = {g.id: o for g in goals if (o := db.get_outcome_for_goal(g.id)) is not None}
    items = []
    for item in evaluate_goals(goals, entries):
        g, actual = item["goal"], item["actual_hours"]
        o = outcomes.get(g.id)
        items.append({
            **_goal_json(g),
            "actual_hours": actual,
            "suggested": suggest_goal_status(g.target_hours, actual),
            "outcome": ({"met": o.met, "actual_hours": o.actual_hours, "notes": o.notes} if o else None),
        })

    summary = None
    if outcomes:
        n_met = sum(o.met == 1 for o in outcomes.values())
        n_partial = sum(o.met == 2 for o in outcomes.values())
        summary = {"evaluated": len(outcomes), "total": len(goals), "met": n_met, "partial": n_partial,
                   "not_met": sum(o.met == 0 for o in outcomes.values()), "verdict": None}
        if len(outcomes) == len(goals):
            # A partial goal counts half; thresholds as in the Streamlit version.
            pct = round((n_met + 0.5 * n_partial) / len(outcomes) * 100)
            if pct >= 80:
                summary["verdict"] = f"Excellent week — {pct}% of goals achieved (fully or partially)."
            elif pct >= 50:
                summary["verdict"] = f"Solid week — {pct}% of goals achieved. Room to push harder next week."
            else:
                summary["verdict"] = f"Challenging week — only {pct}% of goals achieved. Consider adjusting targets."
    return {**_week_json(week_start), "goals": items, "summary": summary, "met_labels": MET_LABELS}


def save_outcome(db: TimesheetDB, goal_id: int, data: dict) -> None:
    try:
        met = int(data.get("met"))
    except (TypeError, ValueError) as e:
        raise UserError("Pick Met, Partial or Not met") from e
    if met not in MET_LABELS:
        raise UserError("Pick Met, Partial or Not met")
    actual = data.get("actual_hours")
    actual = _hours(actual, MAX_GOAL_HOURS, "Actual hours") if actual not in (None, "") else None
    db.upsert_goal_outcome(GoalOutcome(goal_id=goal_id, actual_hours=actual or None, met=met,
                                       notes=str(data.get("notes") or "")))


# ------------------------------------------------------------------ #
# End-of-week export prompt
# ------------------------------------------------------------------ #

def pending_export(db: TimesheetDB, today: Optional[date] = None) -> Optional[dict]:
    """The oldest finished week not yet exported or skipped, or None.

    The app only runs while it is open, so "end of the week" means: the next
    time it is opened after a week has finished. Each finished week with
    entries is asked about once (answers are stored in week_exports).
    """
    today = today or date.today()
    current_week = week_monday(today)
    since_raw = db.get_setting(EXPORT_SINCE_KEY)
    if since_raw is None:
        # First run of this feature: offer last week, not the whole history.
        since = current_week - timedelta(weeks=1)
        db.set_setting(EXPORT_SINCE_KEY, since.isoformat())
    else:
        since = date.fromisoformat(since_raw)
    weeks = {week_monday(e.date) for e in db.get_entries_for_range(since, current_week)}
    pending = pending_export_weeks(today, since, weeks, db.get_decided_export_weeks())
    if not pending:
        return None
    # One week at a time (oldest first) so a long absence doesn't stack prompts.
    week = pending[0]
    return {"week_start": week.isoformat(), "week_end": (week + timedelta(days=6)).isoformat(),
            "more": len(pending) - 1}


def export_week(db: TimesheetDB, export_dir: Path, week_start: date) -> str:
    """Write the week's report .xlsx into export_dir, record it, return the file path."""
    goals = db.get_goals_for_week(week_start)
    outcomes = {g.id: o for g in goals if (o := db.get_outcome_for_goal(g.id)) is not None}
    data = build_week_report_xlsx(week_start, db.get_entries_for_week(week_start),
                                  db.get_reflection(week_start), goals, outcomes)
    path = report_path(str(export_dir), week_start)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(data)
    except OSError as e:
        # Typical on Windows: the file is open in Excel and locked.
        raise UserError(f"Could not save the report ({e}). Close the file if it is open in Excel and try again.") from e
    # Recorded only after the write succeeded, so a failed write is asked again.
    db.record_week_export(week_start, "exported", str(path))
    return str(path)


def skip_export(db: TimesheetDB, week_start: date) -> None:
    db.record_week_export(week_start, "skipped")


# ------------------------------------------------------------------ #
# Import Excel files from earlier runs
# ------------------------------------------------------------------ #

IMPORT_MODES = ("keep", "replace")
_UNKNOWN = "unknown"  # analytics.entries_to_df writes "Unknown" for an empty label; the export inherits it


def _import_subject(db: TimesheetDB, name: str, low: str, high: str) -> Subject:
    """The subject an imported row belongs to, created if needed.

    Matching ignores case, and a label "Unknown" (how the export writes an
    empty label) matches an empty one, so re-importing an export of a subject
    without labels doesn't create a near-duplicate.
    """
    def norm(v: str) -> str:
        v = (v or "").strip()
        return "" if v.casefold() == _UNKNOWN else v

    low, high = norm(low), norm(high)
    same_name = [s for s in db.get_all_subjects() if s.name.casefold() == name.strip().casefold()]
    for s in same_name:
        if norm(s.low_level_label).casefold() == low.casefold() and norm(s.high_level_label).casefold() == high.casefold():
            return s
    if not (low and high) and len(same_name) == 1:
        return same_name[0]
    return _find_or_create_subject(db, name, low or "Unknown", high or "Unknown")


def _import_entries(db: TimesheetDB, entries: list[ImportedEntry], mode: str) -> dict:
    """Add the file's hours, one table cell (subject, day) at a time.

    Compared per cell, not per entry, because the Weekly Table sheet has only
    cell totals. A cell already holding the same total is left alone, which
    makes importing the same file twice harmless. A cell with a different
    total keeps the app's value in "keep" mode and takes the file's in
    "replace" mode.
    """
    counts = {"new": 0, "same": 0, "different": 0}
    cells: dict[tuple, list[ImportedEntry]] = {}
    for e in entries:
        cells.setdefault((e.name, e.low, e.high, e.date), []).append(e)
    for (name, low, high, d), items in cells.items():
        subj = _import_subject(db, name, low, high)
        existing = [e for e in db.get_entries_for_range(d, d + timedelta(days=1)) if e.subject_id == subj.id]
        file_total = sum(i.hours for i in items)
        if existing and abs(sum(e.duration_hours for e in existing) - file_total) < 0.001:
            counts["same"] += 1
            continue
        if existing:
            counts["different"] += 1
            if mode != "replace":
                continue
            for e in existing:
                db.delete_entry(e.id)
        else:
            counts["new"] += 1
        for i in items:
            db.add_entry(TimeEntry(date=d, subject_id=subj.id, duration_hours=i.hours, notes=i.notes))
        # A row removed from that week by hand comes back with its imported hours.
        db.remove_week_exclusion(week_monday(d), subj.id)
    return counts


def _import_reflection(db: TimesheetDB, week: date, refl: Optional[dict], mode: str) -> str:
    if not refl:
        return "none"
    new = Reflection(week_start=week, strengths=refl["strengths"], weaknesses=refl["weaknesses"],
                     next_week_plan=refl["plan"])
    cur = db.get_reflection(week)
    cur_fields = (cur.strengths, cur.weaknesses, cur.next_week_plan) if cur else ("", "", "")
    if cur_fields == (new.strengths, new.weaknesses, new.next_week_plan):
        return "same"
    if any(cur_fields):
        if mode != "replace":
            return "kept"
        db.upsert_reflection(new)
        return "replaced"
    db.upsert_reflection(new)
    return "new"


def _import_goals(db: TimesheetDB, week: date, goals: list[dict], mode: str) -> dict:
    """Goals are matched by description (ignoring case) within the week."""
    counts = {"new": 0, "existing": 0}
    existing = {g.description.strip().casefold(): g for g in db.get_goals_for_week(week)}
    for g in goals:
        goal = existing.get(g["description"].casefold())
        if goal is None:
            # The Goals sheet names the subject but not its labels: prefer a
            # subject with that name that has hours in the week.
            candidates = [s for s in db.get_all_subjects() if s.name.casefold() == g["subject"].casefold()] if g["subject"] else []
            used = {e.subject_id for e in db.get_entries_for_week(week)}
            subj = next((s for s in candidates if s.id in used), candidates[0] if candidates else None)
            goal = db.add_goal(Goal(week_start=week, description=g["description"], target_hours=g["target_hours"],
                                    subject_id=subj.id if subj else None))
            existing[g["description"].casefold()] = goal
            counts["new"] += 1
        else:
            counts["existing"] += 1
        if g["met"] is None:
            continue
        cur = db.get_outcome_for_goal(goal.id)
        if cur is None or (mode == "replace" and (cur.met, cur.notes) != (g["met"], g["notes"])):
            db.upsert_goal_outcome(GoalOutcome(goal_id=goal.id, actual_hours=cur.actual_hours if cur else None,
                                               met=g["met"], notes=g["notes"]))
    return counts


def _week_hours(db: TimesheetDB, weeks) -> dict:
    return {w: round(sum(e.duration_hours for e in db.get_entries_for_week(w)), 2) for w in weeks}


def import_excel(db: TimesheetDB, files: list[tuple[str, bytes]], mode: str = "keep",
                 weeks: Optional[dict] = None) -> dict:
    """Import Excel files written by earlier runs of the app.

    files: (file name, content) pairs, applied in the given order.
    mode:  "keep" leaves a day that already has different hours as it is;
           "replace" puts the file's hours there.
    weeks: {index in files: "YYYY-MM-DD"} for files with no date of their own.

    A file that can't be read is reported and skipped; the others are
    still imported. Returns a per-file summary and hours per affected week
    before and after, for the Import tab's table and chart.
    """
    if mode not in IMPORT_MODES:
        raise UserError("mode must be keep or replace")
    weeks = weeks or {}
    parsed, results = [], []
    for i, (name, data) in enumerate(files):
        chosen = weeks.get(str(i)) or weeks.get(i)
        res = {"index": i, "name": name, "ok": False, "error": None, "needs_week": False, "warnings": []}
        results.append(res)
        try:
            wb = parse_workbook(data, name, parse_week(chosen) if chosen else None)
        except WeekNeeded as e:
            res.update(error=str(e), needs_week=True)
            continue
        except ExcelImportError as e:
            res["error"] = str(e)
            continue
        parsed.append((res, wb))

    affected = set()
    for _, wb in parsed:
        affected |= {week_monday(e.date) for e in wb.entries}
        if wb.week and (wb.reflection or wb.goals):
            affected.add(wb.week)
    before = _week_hours(db, affected)

    for res, wb in parsed:
        entry_weeks = sorted({week_monday(e.date) for e in wb.entries})
        res.update(
            ok=True, kind=wb.kind, warnings=wb.warnings, week_source=wb.week_source,
            week_start=wb.week.isoformat() if wb.week else None,
            weeks=[w.isoformat() for w in entry_weeks] or ([wb.week.isoformat()] if wb.week else []),
            hours=round(sum(e.hours for e in wb.entries), 2),
            entries=_import_entries(db, wb.entries, mode),
            reflection=_import_reflection(db, wb.week, wb.reflection, mode) if wb.week else "none",
            goals=_import_goals(db, wb.week, wb.goals, mode) if wb.week else {"new": 0, "existing": 0},
        )

    after = _week_hours(db, affected)
    return {
        "mode": mode,
        "files": results,
        "weeks": [{"week_start": w.isoformat(), "hours_before": before[w], "hours_after": after[w]}
                  for w in sorted(affected)],
    }


def preview_import(db_path: Path, files: list[tuple[str, bytes]], mode: str = "keep",
                   weeks: Optional[dict] = None) -> dict:
    """What import_excel would do, without changing anything.

    Runs the real import on a temporary copy of the database, so the
    preview can't disagree with the import (two files touching the same
    week, subjects created along the way, ...).
    """
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "preview.db"
        if Path(db_path).exists():
            paths.copy_sqlite(Path(db_path), copy)
        # Closed before the folder is deleted: Windows can't delete an open file.
        with TimesheetDB(str(copy)) as d:
            return import_excel(d, files, mode, weeks)
