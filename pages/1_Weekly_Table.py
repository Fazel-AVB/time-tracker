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

subject_by_key = {(s.name, s.low_level_label, s.high_level_label): s for s in subjects}
subject_by_id = {s.id: s for s in subjects}
subject_display_labels = sorted(f"{s.name} · {s.low_level_label}" for s in subjects)
subject_by_display = {f"{s.name} · {s.low_level_label}": s for s in subjects}

# ------------------------------------------------------------------ #
# Pivot table (editable)
# ------------------------------------------------------------------ #

pivot_df = week_pivot(entries, week_start)
_EDIT_COLS = ["Subject", "Low Label", "High Label"] + _DAY_ABBR

if not subjects:
    st.info("No subjects defined yet.  Add a subject below to get started.")
else:
    # Subjects that have at least one entry this week come first;
    # subjects with no entries stay at the bottom so newly-saved subjects
    # don't jump to an alphabetical middle position before hours are logged.
    _subjects_with_entries = {e.subject_id for e in entries}
    _ordered_subjects = (
        [s for s in subjects if s.id in _subjects_with_entries] +
        [s for s in subjects if s.id not in _subjects_with_entries]
    )
    all_subjects_df = pd.DataFrame([{
        "Subject": s.name,
        "Low Label": s.low_level_label,
        "High Label": s.high_level_label,
        **{d: 0.0 for d in _DAY_ABBR},
    } for s in _ordered_subjects])

    if pivot_df.empty:
        edit_df = all_subjects_df
    else:
        pivot_subset = pivot_df[_EDIT_COLS].copy()
        edit_df = all_subjects_df.merge(
            pivot_subset,
            on=["Subject", "Low Label", "High Label"],
            how="left",
            suffixes=("_base", ""),
        )
        for d in _DAY_ABBR:
            col_base = f"{d}_base"
            if col_base in edit_df.columns:
                edit_df[d] = edit_df[d].fillna(edit_df[col_base])
                edit_df.drop(columns=[col_base], inplace=True)
            edit_df[d] = edit_df[d].fillna(0.0)

    orig_rows_by_key = {
        (row["Subject"], row["Low Label"], row["High Label"]): dict(row)
        for _, row in edit_df.iterrows()
    }

    for d in _DAY_ABBR:
        if d in edit_df.columns:
            edit_df[d] = edit_df[d].fillna(0.0)

    # Add per-row Total column (computed, read-only)
    edit_df["Total"] = edit_df[_DAY_ABBR].sum(axis=1)

    # Sort only rows that are fully complete: Subject + Low Label + High Label + at least one hour.
    # Everything else keeps its original order at the bottom, so partial rows never jump.
    _is_complete = (
        edit_df["Subject"].notna() & (edit_df["Subject"].str.strip() != "") &
        edit_df["Low Label"].notna() & (edit_df["Low Label"].str.strip() != "") &
        edit_df["High Label"].notna() & (edit_df["High Label"].str.strip() != "") &
        (edit_df["Total"] > 0)
    )
    edit_df = pd.concat([
        edit_df[_is_complete].sort_values(["High Label", "Low Label"]),
        edit_df[~_is_complete],
    ]).reset_index(drop=True)

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
        "Total": st.column_config.NumberColumn("Total", format="%.2f"),
    }

    edited = st.data_editor(
        edit_df,
        column_config=_col_cfg,
        disabled=["Total"],
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        key=f"pivot_editor_{week_start}",
    )

    # DAILY TOTAL row — rendered as HTML so "DAILY TOTAL" can span the first
    # three columns (Subject, Low Label, High Label) with a proper merged cell.
    # Kept outside the editor so new rows always land above it.
    if edited is not None and len(edited) > 0:
        subject_rows = edited[edited["Subject"].notna() & (edited["Subject"] != "")]
        day_totals = {d: round(float(subject_rows[d].fillna(0).sum()), 2) for d in _DAY_ABBR if d in subject_rows.columns}
        week_total = round(sum(day_totals.values()), 2)

        header_cells = "".join(
            f'<th style="text-align:right;padding:4px 10px;font-weight:600;color:#4C1D95;background:#EDE9FE;">{d}</th>'
            for d in _DAY_ABBR
        )
        day_cells = "".join(
            f'<td style="text-align:right;padding:5px 10px;">{day_totals.get(d, 0.0):.2f}</td>'
            for d in _DAY_ABBR
        )
        col_widths = (
            '<col style="width:20%"><col style="width:12%"><col style="width:12%">'
            + '<col style="width:7%">' * len(_DAY_ABBR)
            + '<col style="width:7%">'
        )
        html_row = f"""
<div style="margin-top:-12px;overflow-x:auto;">
<table style="width:100%;border-collapse:collapse;font-family:sans-serif;font-size:14px;">
  <colgroup>{col_widths}</colgroup>
  <thead>
    <tr>
      <th colspan="3" style="background:#EDE9FE;padding:4px 10px;"></th>
      {header_cells}
      <th style="text-align:right;padding:4px 10px;font-weight:600;color:#4C1D95;background:#EDE9FE;">Total</th>
    </tr>
  </thead>
  <tbody>
    <tr style="background-color:#7C3AED;color:#fff;font-weight:700;">
      <td colspan="3" style="text-align:center;padding:5px 10px;letter-spacing:0.05em;">DAILY TOTAL</td>
      {day_cells}
      <td style="text-align:right;padding:5px 10px;">{week_total:.2f}</td>
    </tr>
  </tbody>
</table>
</div>"""
        st.markdown(html_row, unsafe_allow_html=True)
        st.caption(
            f"Week total: **{fmt_hours(week_total)}**  ·  "
            "Click **+** to add a row, hover a row and click 🗑 to delete"
        )

    # Excel download
    if edited is not None and len(edited) > 0:
        dl_df = edited[edited["Subject"] != "DAILY TOTAL"].copy()
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
        edit_rows_clean = edit_rows_clean[edit_rows_clean["Subject"] != "DAILY TOTAL"]

        orig_keys = set(orig_rows_by_key.keys())
        edit_keys = set(zip(
            edit_rows_clean["Subject"],
            edit_rows_clean["Low Label"].fillna(""),
            edit_rows_clean["High Label"].fillna(""),
        ))

        removed_keys = orig_keys - edit_keys
        raw_added_keys = edit_keys - orig_keys
        kept_keys = orig_keys & edit_keys

        # If an "added" key already exists in the DB, treat it as kept
        truly_added = set()
        for key in raw_added_keys:
            if subject_by_key.get(key):
                kept_keys.add(key)
            else:
                truly_added.add(key)

        needs_rerun = False

        with TimesheetDB(DB_PATH) as db:
            for key in removed_keys:
                subj = subject_by_key.get(key)
                if subj:
                    try:
                        db.delete_subject(subj.id)
                        needs_rerun = True
                    except Exception:
                        st.warning(
                            f"Cannot delete **{key[0]}** — it has existing time entries. "
                            "Delete those entries first from the section below."
                        )

            for key in truly_added:
                name, low, high = key
                # Wait until all three fields are filled before saving to DB,
                # so partial rows don't trigger premature reruns and sorting jumps.
                if not name.strip() or not low.strip() or not high.strip():
                    continue
                try:
                    db.add_subject(Subject(
                        name=name.strip(),
                        low_level_label=low,
                        high_level_label=high,
                    ))
                    needs_rerun = True
                except Exception as exc:
                    st.error(f"Could not add subject '{name}': {exc}")

            for key in kept_keys:
                subj = subject_by_key.get(key)
                if not subj:
                    continue
                name, low, high = key
                mask = (
                    (edit_rows_clean["Subject"] == name) &
                    (edit_rows_clean["Low Label"].fillna("") == low) &
                    (edit_rows_clean["High Label"].fillna("") == high)
                )
                row_matches = edit_rows_clean[mask]
                if row_matches.empty:
                    continue
                row = row_matches.iloc[0]
                orig = orig_rows_by_key[key]

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
            subj_choice = st.selectbox("Subject", subject_display_labels)
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
                subj = subject_by_display[subj_choice]
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
            n, l, h = new_name.strip(), new_low.strip(), new_high.strip()
            same_name_different_labels = [
                s for s in subjects
                if s.name.lower() == n.lower()
                and not (s.low_level_label == l and s.high_level_label == h)
            ]
            if same_name_different_labels:
                st.session_state.pending_subject = {"name": n, "low": l, "high": h}
            else:
                try:
                    with TimesheetDB(DB_PATH) as db:
                        db.add_subject(Subject(name=n, low_level_label=l, high_level_label=h))
                    st.success(f"Subject '{n}' added.")
                    st.session_state.pop("pending_subject", None)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not add subject: {exc}")

    pending = st.session_state.get("pending_subject")
    if pending:
        same_name = [s for s in subjects if s.name.lower() == pending["name"].lower()]
        st.warning(f"**'{pending['name']}'** already exists under the following label combination(s):")
        for s in same_name:
            st.caption(f"• Low: **{s.low_level_label}**  ·  High: **{s.high_level_label}**")
        st.caption(
            "Check if one of these covers your current task — if so, select it in the Log Time form. "
            "Otherwise, confirm below to add it with the new labels."
        )
        pc1, pc2 = st.columns(2)
        if pc1.button("Add anyway", use_container_width=True):
            try:
                with TimesheetDB(DB_PATH) as db:
                    db.add_subject(Subject(
                        name=pending["name"],
                        low_level_label=pending["low"],
                        high_level_label=pending["high"],
                    ))
                st.success(f"Subject '{pending['name']}' added.")
            except Exception as exc:
                st.error(f"Could not add subject: {exc}")
            st.session_state.pop("pending_subject", None)
            st.rerun()
        if pc2.button("Cancel", use_container_width=True):
            st.session_state.pop("pending_subject", None)
            st.rerun()

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

    sel_subj = subject_by_id.get(sel.subject_id)
    sel_display = (
        f"{sel_subj.name} · {sel_subj.low_level_label}"
        if sel_subj and f"{sel_subj.name} · {sel_subj.low_level_label}" in subject_by_display
        else (subject_display_labels[0] if subject_display_labels else "")
    )

    with st.form("edit_entry_form"):
        edit_subj = st.selectbox(
            "Subject", subject_display_labels,
            index=subject_display_labels.index(sel_display)
            if sel_display in subject_display_labels else 0,
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
            subj = subject_by_display[edit_subj]
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
