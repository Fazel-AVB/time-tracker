"""Page 4: Goal Review — evaluate this week's goals against actual time logged."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date, timedelta

import streamlit as st

from tracker import default_db_path
from tracker.analytics import evaluate_goals, fmt_hours, week_monday
from tracker.database import TimesheetDB
from tracker.models import GoalOutcome
from tracker.seasonal import seasonal_banner

DB_PATH = default_db_path()

MET_LABELS = {0: "Not met", 1: "Met", 2: "Partial"}
MET_COLORS = {0: "#6D28D9", 1: "#2563EB", 2: "#7C3AED"}

st.set_page_config(page_title="Goal Review", layout="wide")

st.markdown("""
<style>
    [data-testid="stSidebar"] { background-color: #EDE9FE; }
    [data-testid="stMetricValue"] { color: #7C3AED; font-weight: 700; }
    hr { border-color: #C4B5FD !important; }
    [data-testid="stAlert"] { border-left: 4px solid #7C3AED; }
    .stCaption { color: #6D28D9 !important; }
</style>
""", unsafe_allow_html=True)

st.title("Goal Review")

if "goal_week" not in st.session_state:
    st.session_state.goal_week = week_monday(date.today())
st.markdown(seasonal_banner(st.session_state.goal_week), unsafe_allow_html=True)

# ------------------------------------------------------------------ #
# Week navigation
# ------------------------------------------------------------------ #

col_prev, col_label, col_next = st.columns([1, 5, 1])
with col_prev:
    if st.button("← Prev", use_container_width=True):
        st.session_state.goal_week -= timedelta(weeks=1)
        st.rerun()
with col_next:
    if st.button("Next →", use_container_width=True):
        st.session_state.goal_week += timedelta(weeks=1)
        st.rerun()
with col_label:
    ws = st.session_state.goal_week
    we = ws + timedelta(days=6)
    st.markdown(
        f"<h3 style='text-align:center;margin:4px 0'>"
        f"{ws.strftime('%b %d')} – {we.strftime('%b %d, %Y')}"
        f"</h3>",
        unsafe_allow_html=True,
    )

week_start: date = st.session_state.goal_week

st.divider()

# ------------------------------------------------------------------ #
# Load goals + entries for this week
# ------------------------------------------------------------------ #

with TimesheetDB(DB_PATH) as db:
    goals = db.get_goals_for_week(week_start)
    entries = db.get_entries_for_week(week_start)
    existing_outcomes = {
        g.id: db.get_outcome_for_goal(g.id)
        for g in goals
        if db.get_outcome_for_goal(g.id) is not None
    }

if not goals:
    st.info(
        "No goals were set for this week.  "
        "Go to the **Reflection** page of the previous week to define goals."
    )
    st.stop()

# ------------------------------------------------------------------ #
# Auto-evaluate subject-linked goals
# ------------------------------------------------------------------ #

auto_eval = evaluate_goals(goals, entries)  # [{goal, actual_hours}, ...]

# ------------------------------------------------------------------ #
# Goal evaluation cards
# ------------------------------------------------------------------ #

st.subheader(f"Goals for this week  ({len(goals)} total)")

for item in auto_eval:
    goal = item["goal"]
    actual_h = item["actual_hours"]
    outcome = existing_outcomes.get(goal.id)

    # Determine display values
    saved_met = outcome.met if outcome else 0
    saved_notes = outcome.notes if outcome else ""

    with st.container(border=True):
        hcol, scol = st.columns([5, 2])

        with hcol:
            st.markdown(f"**{goal.description}**")
            detail_parts = []
            if goal.target_hours:
                detail_parts.append(f"Target: {fmt_hours(goal.target_hours)}")
            if goal.subject_name:
                detail_parts.append(f"Subject: {goal.subject_name}")
                if actual_h is not None:
                    detail_parts.append(f"Actual: {fmt_hours(actual_h)}")
            if goal.notes:
                detail_parts.append(f"Notes: {goal.notes}")
            if detail_parts:
                st.caption("  ·  ".join(detail_parts))

        with scol:
            color = MET_COLORS[saved_met]
            st.markdown(
                f"<span style='background:{color};color:#fff;padding:3px 10px;"
                f"border-radius:4px;font-size:0.85em'>{MET_LABELS[saved_met]}</span>",
                unsafe_allow_html=True,
            )

        # Auto-suggest met status if subject-linked
        auto_suggestion = None
        if goal.target_hours and actual_h is not None:
            if actual_h >= goal.target_hours:
                auto_suggestion = 1
            elif actual_h >= 0.75 * goal.target_hours:
                auto_suggestion = 2
            else:
                auto_suggestion = 0

        with st.form(f"eval_form_{goal.id}", clear_on_submit=False):
            met_choice = st.radio(
                "Outcome",
                options=[0, 1, 2],
                format_func=lambda x: MET_LABELS[x],
                index=saved_met,
                horizontal=True,
                key=f"met_{goal.id}",
            )
            eval_actual = st.number_input(
                "Actual hours (override)",
                min_value=0.0, max_value=168.0, step=0.25,
                value=float(actual_h or (outcome.actual_hours or 0.0)),
                key=f"actual_{goal.id}",
            )
            eval_notes = st.text_input(
                "Evaluation notes",
                value=saved_notes,
                key=f"eval_notes_{goal.id}",
            )
            save_eval = st.form_submit_button("Save Evaluation")

        if save_eval:
            with TimesheetDB(DB_PATH) as db:
                db.upsert_goal_outcome(GoalOutcome(
                    goal_id=goal.id,
                    actual_hours=eval_actual if eval_actual > 0 else None,
                    met=met_choice,
                    notes=eval_notes,
                ))
            st.success("Saved.")
            st.rerun()

st.divider()

# ------------------------------------------------------------------ #
# Summary report
# ------------------------------------------------------------------ #

st.subheader("Summary")

if existing_outcomes:
    n_met = sum(1 for o in existing_outcomes.values() if o.met == 1)
    n_partial = sum(1 for o in existing_outcomes.values() if o.met == 2)
    n_not = sum(1 for o in existing_outcomes.values() if o.met == 0)
    n_total = len(existing_outcomes)

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Goals evaluated", n_total)
    sc2.metric("Met", n_met)
    sc3.metric("Partial", n_partial)
    sc4.metric("Not met", n_not)

    if n_total == len(goals):
        pct = round((n_met + 0.5 * n_partial) / n_total * 100)
        if pct >= 80:
            interpretation = f"Excellent week — {pct}% of goals achieved (fully or partially)."
        elif pct >= 50:
            interpretation = f"Solid week — {pct}% of goals achieved.  Room to push harder next week."
        else:
            interpretation = f"Challenging week — only {pct}% of goals achieved.  Consider adjusting targets."
        st.info(interpretation)
    else:
        st.caption(f"{n_total} of {len(goals)} goals evaluated so far.")
else:
    st.caption("Evaluate goals above to see a summary.")

st.divider()
st.caption("To set goals for next week, go to the **Reflection** page.")
