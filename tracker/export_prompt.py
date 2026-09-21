"""
End-of-week export prompt, shown at the top of every page.

Streamlit only runs while a page is open, so "end of the week" means: the next
time the app is opened after a week has finished. Each finished week that has
entries is asked about once; the answer (exported / skipped) is stored in the
week_exports table so it is not asked again. Pure logic lives in
tracker/week_report.py; this module is only the Streamlit UI and file write.
"""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from tracker.analytics import week_monday
from tracker.database import TimesheetDB
from tracker.week_report import build_week_report_xlsx, pending_export_weeks, report_path

# settings key: the Monday from which finished weeks are eligible for the prompt.
_SINCE_KEY = "export_prompt_since"
# Message shown once after a rerun (the buttons trigger st.rerun, which would
# otherwise wipe an st.success written before it).
_FLASH_KEY = "export_prompt_flash"


def export_week_report(db_path: str, export_dir: str, week_start: date) -> str:
    """Write the week's .xlsx into export_dir, record it, return the file path."""
    with TimesheetDB(db_path) as db:
        entries = db.get_entries_for_week(week_start)
        reflection = db.get_reflection(week_start)
        goals = db.get_goals_for_week(week_start)
        outcomes = {g.id: o for g in goals if (o := db.get_outcome_for_goal(g.id)) is not None}
    data = build_week_report_xlsx(week_start, entries, reflection, goals, outcomes)
    path = report_path(export_dir, week_start)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    with TimesheetDB(db_path) as db:
        # Recorded only after the write succeeded, so a failed write is asked again.
        db.record_week_export(week_start, "exported", str(path))
    return str(path)


def render_week_export_prompt(db_path: str, export_dir: str) -> None:
    """Show the prompt for the oldest unanswered finished week, if any."""
    flash = st.session_state.pop(_FLASH_KEY, None)
    if flash:
        st.success(flash)

    today = date.today()
    current_week = week_monday(today)
    with TimesheetDB(db_path) as db:
        since_raw = db.get_setting(_SINCE_KEY)
        if since_raw is None:
            # First run of this feature: offer last week, not the whole history.
            since = current_week - timedelta(weeks=1)
            db.set_setting(_SINCE_KEY, since.isoformat())
        else:
            since = date.fromisoformat(since_raw)
        entries = db.get_entries_for_range(since, current_week)
        decided = db.get_decided_export_weeks()

    pending = pending_export_weeks(today, since, {week_monday(e.date) for e in entries}, decided)
    if not pending:
        return

    # One week at a time (oldest first) so a long absence doesn't stack prompts.
    week = pending[0]
    week_end = week + timedelta(days=6)
    with st.container(border=True):
        more = f"  ({len(pending) - 1} more after this)" if len(pending) > 1 else ""
        st.markdown(
            f"**The week of {week.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')} has ended.** "
            f"Export its report to Excel?{more}"
        )
        c1, c2, _ = st.columns([1, 1, 4])
        if c1.button("Export", key=f"export_week_{week}", type="primary", use_container_width=True):
            try:
                path = export_week_report(db_path, export_dir, week)
            except OSError as exc:
                # Typical on Windows: the file is open in Excel and locked.
                st.error(f"Could not save the report: {exc}. Close the file if it is open and try again.")
            else:
                st.session_state[_FLASH_KEY] = f"Report saved to `{path}`"
                st.rerun()
        if c2.button("Not this week", key=f"skip_week_{week}", use_container_width=True):
            with TimesheetDB(db_path) as db:
                db.record_week_export(week, "skipped")
            st.rerun()
