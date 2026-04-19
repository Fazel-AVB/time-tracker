"""Page 1: Weekly Activity Table — log entries, view daily/weekly totals."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from tracker import default_db_path
from tracker.analytics import fmt_hours, week_monday, week_pivot, _DAY_ABBR
from tracker.database import TimesheetDB
from tracker.models import Subject, TimeEntry
from tracker.seasonal import seasonal_banner

DB_PATH = default_db_path()

st.set_page_config(page_title="Weekly Table", layout="wide")

st.markdown("""
<style>
    [data-testid="stSidebar"] { background-color: #EDE9FE; }
    [data-testid="stMetricValue"] { color: #7C3AED; font-weight: 700; }
    hr { border-color: #C4B5FD !important; }
    [data-testid="stAlert"] { border-left: 4px solid #7C3AED; }
    thead tr th { background-color: #EDE9FE !important; color: #4C1D95 !important; }
    .stCaption { color: #6D28D9 !important; }
</style>
""", unsafe_allow_html=True)

st.title("Weekly Activity Table")

if "table_week" not in st.session_state:
    st.session_state.table_week = week_monday(date.today())
st.markdown(seasonal_banner(st.session_state.table_week), unsafe_allow_html=True)

# ------------------------------------------------------------------ #
# Week navigation
# ------------------------------------------------------------------ #

col_prev, col_label, col_next = st.columns([1, 5, 1])
with col_prev:
    if st.button("← Prev", use_container_width=True):
        st.session_state.table_week -= timedelta(weeks=1)
        st.rerun()
with col_next:
    if st.button("Next →", use_container_width=True):
        st.session_state.table_week += timedelta(weeks=1)
        st.rerun()
with col_label:
    ws = st.session_state.table_week
    we = ws + timedelta(days=6)
    st.markdown(
        f"<h3 style='text-align:center;margin:4px 0'>"
        f"{ws.strftime('%b %d')} – {we.strftime('%b %d, %Y')}"
        f"</h3>",
        unsafe_allow_html=True,
    )

st.divider()

# ------------------------------------------------------------------ #
# Load data for this week
# ------------------------------------------------------------------ #

week_start: date = st.session_state.table_week
week_end: date = week_start + timedelta(days=6)

with TimesheetDB(DB_PATH) as db:
    subjects = db.get_all_subjects()
    entries = db.get_entries_for_week(week_start)

subject_by_name = {s.name: s for s in subjects}

# ------------------------------------------------------------------ #
# Pivot table (editable)
# ------------------------------------------------------------------ #

pivot_df = week_pivot(entries, week_start)
_EDIT_COLS = ["Subject", "Low Label", "High Label"] + _DAY_ABBR

if not subjects:
    st.info("No subjects defined yet.  Add a subject below to get started.")
else:
    if pivot_df.empty:
        edit_df = pd.DataFrame([{
            "Subject": s.name,
            "Low Label": s.low_level_label,
            "High Label": s.high_level_label,
            **{d: 0.0 for d in _DAY_ABBR},
        } for s in subjects])
    else:
        edit_df = pivot_df[_EDIT_COLS].copy()

    orig_rows_by_name = {row["Subject"]: dict(row) for _, row in edit_df.iterrows()}

    _col_cfg = {
        "Subject": st.column_config.TextColumn("Subject", required=True),
        "Low Label": st.column_config.TextColumn("Low Label"),
        "High Label": st.column_config.TextColumn("High Label"),
        **{
            day: st.column_config.NumberColumn(
                day, min_value=0.0, max_value=24.0, step=0.25, format="%.2f"
            )
            for day in _DAY_ABBR
        },
    }

    edited = st.data_editor(
        edit_df,
        column_config=_col_cfg,
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        key=f"pivot_editor_{week_start}",
    )

    # Daily totals row — computed live from edited table
    if edited is not None and len(edited) > 0:
        day_totals = {d: float(edited[d].fillna(0).sum()) for d in _DAY_ABBR if d in edited.columns}
        week_total = sum(day_totals.values())
        totals_df = pd.DataFrame([{
            "Subject": "DAILY TOTAL", "Low Label": "", "High Label": "",
            **day_totals, "Week Total": week_total,
        }])

        def _style_totals(row):
            return ["background-color:#7C3AED;color:#fff;font-weight:700;"] * len(row)

        st.dataframe(
            totals_df.style.apply(_style_totals, axis=1),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            f"Week total: **{fmt_hours(week_total)}**  ·  "
            "Edit any cell directly — click **+** to add a row, 🗑 to delete"
        )

    # Excel download
    if edited is not None and len(edited) > 0:
        dl_df = edited.copy()
        dl_df["Total"] = dl_df[[d for d in _DAY_ABBR if d in dl_df.columns]].fillna(0).sum(axis=1)
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            dl_df.to_excel(writer, index=False, sheet_name="Weekly Table")
        st.download_button(
            label="⬇ Download as Excel",
            data=buf.getvalue(),
            file_name=f"timesheet_{week_start}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # ------------------------------------------------------------------ #
    # Persist changes to DB
    # ------------------------------------------------------------------ #

    if edited is not None:
        edit_rows_clean = edited.dropna(subset=["Subject"])
        edit_rows_clean = edit_rows_clean[edit_rows_clean["Subject"].str.strip() != ""]

        orig_names = set(orig_rows_by_name.keys())
        edit_names = set(edit_rows_clean["Subject"].tolist())

        added_names = edit_names - orig_names
        removed_names = orig_names - edit_names
        kept_names = orig_names & edit_names

        needs_rerun = False

        with TimesheetDB(DB_PATH) as db:
            for name in removed_names:
                subj = subject_by_name.get(name)
                if subj:
                    try:
                        db.delete_subject(subj.id)
                        needs_rerun = True
                    except Exception:
                        st.warning(
                            f"Cannot delete **{name}** — it has existing time entries. "
                            "Delete those entries first from the section below."
                        )

            for name in added_names:
                row = edit_rows_clean[edit_rows_clean["Subject"] == name].iloc[0]
                low = str(row.get("Low Label") or "")
                high = str(row.get("High Label") or "")
                try:
                    db.add_subject(Subject(
                        name=name.strip(),
                        low_level_label=low,
                        high_level_label=high,
                    ))
                    needs_rerun = True
                except Exception as exc:
                    st.error(f"Could not add subject '{name}': {exc}")

            for name in kept_names:
                subj = subject_by_name[name]
                row = edit_rows_clean[edit_rows_clean["Subject"] == name].iloc[0]
                orig = orig_rows_by_name[name]

                new_low = str(row.get("Low Label") or subj.low_level_label)
                new_high = str(row.get("High Label") or subj.high_level_label)
                if new_low != subj.low_level_label or new_high != subj.high_level_label:
                    db.update_subject(Subject(
                        id=subj.id, name=name,
                        low_level_label=new_low,
                        high_level_label=new_high,
                    ))
                    needs_rerun = True

                for day_idx, day in enumerate(_DAY_ABBR):
                    new_val = float(row.get(day) or 0)
                    old_val = float(orig.get(day) or 0)
                    if abs(new_val - old_val) > 0.001:
                        entry_date = week_start + timedelta(days=day_idx)
                        for e in [e for e in entries if e.subject_id == subj.id and e.date == entry_date]:
                            db.delete_entry(e.id)
                        if new_val > 0:
                            db.add_entry(TimeEntry(
                                date=entry_date,
                                subject_id=subj.id,
                                duration_hours=new_val,
                            ))
                        needs_rerun = True

        if needs_rerun:
            st.rerun()

st.divider()

# ------------------------------------------------------------------ #
# Log time  |  Manage subjects
# ------------------------------------------------------------------ #

col_log, col_subj = st.columns(2)

with col_log:
    st.subheader("Log Time")
    if not subjects:
        st.warning("Add at least one subject (right panel) before logging time.")
    else:
        with st.form("add_entry_form", clear_on_submit=True):
            subject_names = sorted(subject_by_name.keys())
            subj_choice = st.selectbox("Subject", subject_names)
            entry_date = st.date_input(
                "Date", value=date.today(),
                min_value=week_start, max_value=week_end,
            )
            duration = st.number_input(
                "Duration (hours)", min_value=0.0, max_value=24.0, step=0.25, value=1.0
            )
            notes = st.text_input("Notes (optional)")
            submitted = st.form_submit_button("Add Entry", use_container_width=True)

        if submitted:
            if duration <= 0:
                st.error("Duration must be greater than 0.")
            else:
                subj = subject_by_name[subj_choice]
                with TimesheetDB(DB_PATH) as db:
                    db.add_entry(TimeEntry(
                        date=entry_date,
                        subject_id=subj.id,
                        duration_hours=duration,
                        notes=notes,
                    ))
                st.success(f"Logged {fmt_hours(duration)} for **{subj_choice}** on {entry_date}.")
                st.rerun()

with col_subj:
    st.subheader("Manage Subjects")
    with st.form("add_subject_form", clear_on_submit=True):
        new_name = st.text_input("Subject name", placeholder="e.g. Programming")
        new_low = st.text_input("Low-level label", placeholder="e.g. work-related")
        new_high = st.text_input("High-level label", placeholder="e.g. Work")
        add_subj = st.form_submit_button("Add Subject", use_container_width=True)

    if add_subj:
        if not new_name or not new_low or not new_high:
            st.error("All three fields are required.")
        else:
            try:
                with TimesheetDB(DB_PATH) as db:
                    db.add_subject(Subject(name=new_name, low_level_label=new_low, high_level_label=new_high))
                st.success(f"Subject '{new_name}' added.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not add subject: {exc}")

    if subjects:
        with st.expander("Existing subjects"):
            st.dataframe(
                pd.DataFrame([{
                    "Name": s.name,
                    "Low Label": s.low_level_label,
                    "High Label": s.high_level_label,
                } for s in subjects]),
                use_container_width=True,
                hide_index=True,
            )

st.divider()

# ------------------------------------------------------------------ #
# Entries this week
# ------------------------------------------------------------------ #

st.subheader("Entries This Week")

if not entries:
    st.info("No entries for this week.")
else:
    hc = st.columns([3, 2, 1.5, 3, 1])
    for h_text, col in zip(["Subject", "Date", "Hours", "Notes", ""], hc):
        col.markdown(f"**{h_text}**")

    for entry in entries:
        c1, c2, c3, c4, c5 = st.columns([3, 2, 1.5, 3, 1])
        c1.write(entry.subject_name)
        c2.write(entry.date.strftime("%a %b %d"))
        c3.write(fmt_hours(entry.duration_hours))
        c4.write(entry.notes or "—")
        if c5.button("Del", key=f"del_{entry.id}", help=f"Delete entry #{entry.id}"):
            with TimesheetDB(DB_PATH) as db:
                db.delete_entry(entry.id)
            st.rerun()

    st.divider()
    st.subheader("Edit Entry")

    entry_options = {
        f"#{e.id} — {e.subject_name}  {e.date.strftime('%a %b %d')}  {fmt_hours(e.duration_hours)}": e
        for e in entries
    }
    selected_label = st.selectbox("Select entry to edit", list(entry_options.keys()))
    sel = entry_options[selected_label]
    subject_names = sorted(subject_by_name.keys())

    with st.form("edit_entry_form"):
        edit_subj = st.selectbox(
            "Subject", subject_names,
            index=subject_names.index(sel.subject_name)
            if sel.subject_name in subject_names else 0,
        )
        edit_date = st.date_input("Date", value=sel.date)
        edit_dur = st.number_input(
            "Duration (hours)", min_value=0.0, max_value=24.0,
            step=0.25, value=float(sel.duration_hours),
        )
        edit_notes = st.text_input("Notes", value=sel.notes or "")
        save_edit = st.form_submit_button("Save Changes", use_container_width=True)

    if save_edit:
        if edit_dur <= 0:
            st.error("Duration must be greater than 0.")
        else:
            subj = subject_by_name[edit_subj]
            with TimesheetDB(DB_PATH) as db:
                db.update_entry(TimeEntry(
                    id=sel.id,
                    date=edit_date,
                    subject_id=subj.id,
                    duration_hours=edit_dur,
                    notes=edit_notes,
                ))
            st.success("Entry updated.")
            st.rerun()
