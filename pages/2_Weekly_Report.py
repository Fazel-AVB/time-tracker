"""Page 2: Weekly Report — analytics dashboard with charts and comparisons."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from tracker import default_db_path
from tracker.analytics import (
    aggregate_by_label,
    aggregate_by_subject,
    compare_to_averages,
    entries_to_df,
    fmt_hours,
    label_averages_over_range,
    narrative_summary,
    week_monday,
    weekly_totals_over_range,
)
from tracker.database import TimesheetDB
from tracker.seasonal import seasonal_banner

DB_PATH = default_db_path()

st.set_page_config(page_title="Weekly Report", layout="wide")

st.markdown("""
<style>
    [data-testid="stSidebar"] { background-color: #EDE9FE; }
    [data-testid="stMetricValue"] { color: #7C3AED; font-weight: 700; }
    hr { border-color: #C4B5FD !important; }
    [data-testid="stAlert"] { border-left: 4px solid #7C3AED; }
    thead tr th { background-color: #EDE9FE !important; color: #4C1D95 !important; }
    .stCaption { color: #6D28D9 !important; }
    blockquote { border-left: 4px solid #7C3AED; padding-left: 1em; color: #4C1D95; }
</style>
""", unsafe_allow_html=True)

st.title("Weekly Report")

if "report_week" not in st.session_state:
    st.session_state.report_week = week_monday(date.today())
st.markdown(seasonal_banner(st.session_state.report_week), unsafe_allow_html=True)

# ------------------------------------------------------------------ #
# Week navigation + filters
# ------------------------------------------------------------------ #

col_prev, col_label, col_next = st.columns([1, 5, 1])
with col_prev:
    if st.button("← Prev", use_container_width=True):
        st.session_state.report_week -= timedelta(weeks=1)
        st.rerun()
with col_next:
    if st.button("Next →", use_container_width=True):
        st.session_state.report_week += timedelta(weeks=1)
        st.rerun()
with col_label:
    ws = st.session_state.report_week
    we = ws + timedelta(days=6)
    st.markdown(
        f"<h3 style='text-align:center;margin:4px 0'>"
        f"{ws.strftime('%b %d')} – {we.strftime('%b %d, %Y')}"
        f"</h3>",
        unsafe_allow_html=True,
    )

week_start: date = st.session_state.report_week

with st.sidebar:
    st.header("Filters")
    label_level = st.radio("Label level", ["High", "Low"], index=0)
    history_weeks = st.slider("History for averages (weeks)", min_value=2, max_value=26, value=8)

level_key = "high" if label_level == "High" else "low"

st.divider()

# ------------------------------------------------------------------ #
# Load data
# ------------------------------------------------------------------ #

history_start = week_start - timedelta(weeks=history_weeks)

with TimesheetDB(DB_PATH) as db:
    entries = db.get_entries_for_week(week_start)
    history_entries = db.get_entries_for_range(history_start, week_start)

if not entries:
    st.info("No entries for this week.  Go to the **Weekly Table** page to log some time.")
    st.stop()

# ------------------------------------------------------------------ #
# Aggregations
# ------------------------------------------------------------------ #

current_by_label = aggregate_by_label(entries, level=level_key)
avg_by_label = label_averages_over_range(history_entries, level=level_key)
comparison = compare_to_averages(current_by_label, avg_by_label)

total_hours = sum(e.duration_hours for e in entries)
top_row = current_by_label.iloc[0] if not current_by_label.empty else None
least_row = current_by_label.iloc[-1] if len(current_by_label) > 1 else None

prev_week_start = week_start - timedelta(weeks=1)
with TimesheetDB(DB_PATH) as db:
    prev_entries = db.get_entries_for_week(prev_week_start)
prev_total = sum(e.duration_hours for e in prev_entries)
delta_vs_prev = total_hours - prev_total

# ------------------------------------------------------------------ #
# Metrics row
# ------------------------------------------------------------------ #

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total hours", fmt_hours(total_hours))
m2.metric(
    "vs previous week",
    fmt_hours(abs(delta_vs_prev)),
    delta=f"{'↑' if delta_vs_prev >= 0 else '↓'} {fmt_hours(abs(delta_vs_prev))}",
    delta_color="normal" if delta_vs_prev >= 0 else "inverse",
)
m3.metric("Top activity", top_row["label"] if top_row is not None else "—",
          f"{top_row['total_hours']:.1f}h" if top_row is not None else "")
m4.metric("Least activity", least_row["label"] if least_row is not None else "—",
          f"{least_row['total_hours']:.1f}h" if least_row is not None else "")

st.divider()

# ------------------------------------------------------------------ #
# Narrative summary
# ------------------------------------------------------------------ #

with st.container():
    summary_text = narrative_summary(
        entries,
        avg_df=avg_by_label if not avg_by_label.empty else None,
        level=level_key,
    )
    st.markdown(f"> {summary_text}")

st.divider()

# ------------------------------------------------------------------ #
# Charts
# ------------------------------------------------------------------ #

chart_col1, chart_col2 = st.columns(2)

# Bar chart: current week vs long-term average
with chart_col1:
    st.subheader(f"Hours by {label_level}-Level Label")
    if not comparison.empty:
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(
            name="This week",
            x=comparison["label"],
            y=comparison["total_hours"].round(2),
            marker_color="#7C3AED",
        ))
        if not avg_by_label.empty:
            fig_bar.add_trace(go.Bar(
                name=f"Avg last {history_weeks}w",
                x=comparison["label"],
                y=comparison["avg_hours_per_week"].round(2),
                marker_color="#60A5FA",
                opacity=0.8,
            ))
        fig_bar.update_layout(
            barmode="group",
            xaxis_title=None,
            yaxis_title="Hours",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(t=30, b=10),
            height=320,
            plot_bgcolor="#F5F3FF",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("No data to display.")

# Weekly trend chart
with chart_col2:
    st.subheader("Weekly Trend")
    all_entries = history_entries + entries
    trend_df = weekly_totals_over_range(all_entries)

    if len(trend_df) >= 2:
        trend_df["week_label"] = trend_df["week_start"].map(lambda d: d.strftime("%b %d"))
        fig_trend = px.line(
            trend_df,
            x="week_label",
            y="total_hours",
            markers=True,
            labels={"week_label": "Week of", "total_hours": "Hours"},
        )
        fig_trend.update_traces(
            line_color="#7C3AED",
            marker_size=8,
            marker_color="#A78BFA",
            line_width=2.5,
        )
        fig_trend.update_layout(
            xaxis_title=None,
            yaxis_title="Hours",
            margin=dict(t=30, b=10),
            height=320,
            plot_bgcolor="#F5F3FF",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_trend, use_container_width=True)
    else:
        st.info("Log more weeks of data to see a trend.")

st.divider()

# ------------------------------------------------------------------ #
# Subject-level breakdown (pie / bar)
# ------------------------------------------------------------------ #

st.subheader("Subject Breakdown")
by_subject = aggregate_by_subject(entries)

if not by_subject.empty:
    scol1, scol2 = st.columns(2)
    with scol1:
        fig_pie = px.pie(
            by_subject,
            names="subject_name",
            values="total_hours",
            hole=0.35,
            color_discrete_sequence=[
                "#7C3AED", "#3B82F6", "#06B6D4", "#A78BFA",
                "#60A5FA", "#818CF8", "#2563EB", "#8B5CF6",
            ],
        )
        fig_pie.update_layout(
            margin=dict(t=10, b=10),
            height=300,
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    with scol2:
        display_subj = by_subject.copy()
        display_subj["total_hours"] = display_subj["total_hours"].map(fmt_hours)
        display_subj.columns = ["Subject", "Hours"]
        st.dataframe(display_subj, use_container_width=True, hide_index=True)

st.divider()

# ------------------------------------------------------------------ #
# Comparison table
# ------------------------------------------------------------------ #

st.subheader(f"{label_level}-Level Label — Current vs Long-Term Average")

if not comparison.empty and not avg_by_label.empty:
    tbl = comparison.copy()

    def _fmt_delta(row):
        if pd.isna(row["pct_diff"]):
            return "no history"
        sign = "+" if row["diff_hours"] >= 0 else ""
        return f"{sign}{row['diff_hours']:.1f}h  ({sign}{row['pct_diff']:.0f}%)"

    tbl["This week"] = tbl["total_hours"].map(fmt_hours)
    tbl["Long-term avg"] = tbl["avg_hours_per_week"].map(fmt_hours)
    tbl["Delta"] = tbl.apply(_fmt_delta, axis=1)
    tbl = tbl[["label", "This week", "Long-term avg", "Delta"]].rename(
        columns={"label": label_level + " Label"}
    )
    st.dataframe(tbl, use_container_width=True, hide_index=True)
elif avg_by_label.empty:
    st.info(
        f"No history found in the last {history_weeks} weeks.  "
        "Long-term averages will appear once you have logged more than one week."
    )

# ------------------------------------------------------------------ #
# Export
# ------------------------------------------------------------------ #

with st.expander("Export data"):
    df_export = entries_to_df(entries)
    csv = df_export.to_csv(index=False)
    st.download_button(
        "Download week as CSV",
        data=csv,
        file_name=f"timesheet_{week_start.isoformat()}.csv",
        mime="text/csv",
    )
