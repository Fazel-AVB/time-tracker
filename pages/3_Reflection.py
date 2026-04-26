"""Page 3: Weekly Reflection — strengths, weaknesses, plan, and goal setting."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date, timedelta

import streamlit as st

from tracker import default_db_path
from tracker.analytics import fmt_hours, week_monday
from tracker.database import TimesheetDB
from tracker.models import Goal, Reflection
from tracker.seasonal import seasonal_banner

DB_PATH = default_db_path()

st.set_page_config(page_title="Reflection", layout="wide")

st.markdown("""
<style>
    [data-testid="stSidebar"] { background-color: #EDE9FE; }
    [data-testid="stMetricValue"] { color: #7C3AED; font-weight: 700; }
    hr { border-color: #C4B5FD !important; }
    [data-testid="stAlert"] { border-left: 4px solid #7C3AED; }
    .stCaption { color: #6D28D9 !important; }
    textarea { border-color: #A78BFA !important; }
</style>
""", unsafe_allow_html=True)

st.title("Weekly Reflection")

if "refl_week" not in st.session_state:
    st.session_state.refl_week = week_monday(date.today())
st.markdown(seasonal_banner(st.session_state.refl_week), unsafe_allow_html=True)

# ------------------------------------------------------------------ #
# Week navigation
# ------------------------------------------------------------------ #

col_prev, col_label, col_next = st.columns([1, 5, 1])
with col_prev:
    if st.button("← Prev", use_container_width=True):
        st.session_state.refl_week -= timedelta(weeks=1)
        st.rerun()
with col_next:
    if st.button("Next →", use_container_width=True):
        st.session_state.refl_week += timedelta(weeks=1)
        st.rerun()
with col_label:
    ws = st.session_state.refl_week
    we = ws + timedelta(days=6)
    st.markdown(
        f"<h3 style='text-align:center;margin:4px 0'>"
        f"{ws.strftime('%b %d')} – {we.strftime('%b %d, %Y')}"
        f"</h3>",
        unsafe_allow_html=True,
    )

week_start: date = st.session_state.refl_week

st.divider()

# ------------------------------------------------------------------ #
# Load existing reflection for this week
# ------------------------------------------------------------------ #

with TimesheetDB(DB_PATH) as db:
    existing = db.get_reflection(week_start)
    subjects = db.get_all_subjects()

prev_strengths = existing.strengths if existing else ""
prev_weaknesses = existing.weaknesses if existing else ""
prev_plan = existing.next_week_plan if existing else ""

# ------------------------------------------------------------------ #
# Reflection form
# ------------------------------------------------------------------ #

st.subheader("Reflect on This Week")
st.caption("These entries are saved per week and become a lasting self-review record.")

with st.form("reflection_form"):
    strengths = st.text_area(
        "Strengths — what went well?",
        value=prev_strengths,
        height=140,
        placeholder="e.g. Stayed focused in the mornings, made good progress on the paper...",
    )
    weaknesses = st.text_area(
        "Weaknesses — what could have gone better?",
        value=prev_weaknesses,
        height=140,
        placeholder="e.g. Too many interruptions, did not start writing early enough...",
    )
    plan = st.text_area(
        "Plan for next week",
        value=prev_plan,
        height=140,
        placeholder="e.g. Block 2h/day for deep work, finish section 3 of the paper...",
    )
    save_refl = st.form_submit_button("Save Reflection", use_container_width=True)

if save_refl:
    with TimesheetDB(DB_PATH) as db:
        db.upsert_reflection(Reflection(
            week_start=week_start,
            strengths=strengths,
            weaknesses=weaknesses,
            next_week_plan=plan,
        ))
    st.success("Reflection saved.")
    st.rerun()

st.divider()

# ------------------------------------------------------------------ #
# Goals for next week
# ------------------------------------------------------------------ #

next_week_start = week_start + timedelta(weeks=1)
next_we = next_week_start + timedelta(days=6)

st.subheader(
    f"Goals for Next Week  "
    f"({next_week_start.strftime('%b %d')} – {next_we.strftime('%b %d')})"
)
st.caption(
    "Define quantitative goals here.  They will appear on the **Goal Review** page "
    "next week for evaluation."
)

with TimesheetDB(DB_PATH) as db:
    next_goals = db.get_goals_for_week(next_week_start)

if next_goals:
    for goal in next_goals:
        gc1, gc2, gc3, gc4 = st.columns([4, 2, 2, 1])
        gc1.write(goal.description)
        gc2.write(
            f"Target: {fmt_hours(goal.target_hours)}" if goal.target_hours else "Qualitative"
        )
        gc3.write(f"Subject: {goal.subject_name or '—'}")
        if gc4.button("Del", key=f"del_goal_{goal.id}"):
            with TimesheetDB(DB_PATH) as db:
                db.delete_goal(goal.id)
            st.rerun()
else:
    st.info("No goals set for next week yet.")

# Add goal form
with st.expander("Add a goal for next week"):
    with st.form("add_goal_form", clear_on_submit=True):
        goal_desc = st.text_input(
            "Goal description",
            placeholder="e.g. Write 2h/day on the manuscript",
        )
        goal_hours = st.number_input(
            "Target hours (leave 0 for qualitative goal)",
            min_value=0.0, max_value=168.0, step=0.5, value=0.0,
        )
        subject_options = ["(none)"] + [f"{s.name} · {s.low_level_label}" for s in subjects]
        goal_subject = st.selectbox(
            "Link to subject (optional — enables auto-evaluation)",
            subject_options,
        )
        goal_notes = st.text_input("Notes (optional)")
        add_goal = st.form_submit_button("Add Goal", use_container_width=True)

    if add_goal:
        if not goal_desc.strip():
            st.error("Goal description is required.")
        else:
            linked_subject = None
            if goal_subject != "(none)":
                linked = next(
                    (s for s in subjects if f"{s.name} · {s.low_level_label}" == goal_subject),
                    None,
                )
                linked_subject = linked.id if linked else None

            with TimesheetDB(DB_PATH) as db:
                db.add_goal(Goal(
                    week_start=next_week_start,
                    description=goal_desc.strip(),
                    target_hours=goal_hours if goal_hours > 0 else None,
                    subject_id=linked_subject,
                    notes=goal_notes,
                ))
            st.success(f"Goal added for {next_week_start.strftime('%b %d')} week.")
            st.rerun()
