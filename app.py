"""
Personal Time, Progress & Reflection Tracker
=============================================
Landing page.  Navigate using the sidebar.

Run with:
    streamlit run app.py
"""

import streamlit as st

st.set_page_config(
    page_title="Time Tracker",
    page_icon="⏱",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Global purple/blue accent overrides
st.markdown("""
<style>
    /* Sidebar accent */
    [data-testid="stSidebar"] { background-color: #EDE9FE; }
    [data-testid="stSidebar"] .stRadio label { color: #4C1D95; }

    /* Metric value color */
    [data-testid="stMetricValue"] { color: #7C3AED; font-weight: 700; }

    /* Divider color */
    hr { border-color: #C4B5FD !important; }

    /* st.info accent */
    [data-testid="stAlert"] { border-left: 4px solid #7C3AED; }

    /* Table header */
    thead tr th { background-color: #EDE9FE !important; color: #4C1D95 !important; }

    /* Caption */
    .stCaption { color: #6D28D9 !important; }
</style>
""", unsafe_allow_html=True)

st.title("Personal Time, Progress & Reflection Tracker")

st.markdown("""
A lightweight weekly self-tracking tool with four pages:

| Page | Description |
|---|---|
| **1 · Weekly Table** | Live activity table — log time, see daily and weekly totals |
| **2 · Weekly Report** | Analytics dashboard — summaries, comparisons to your long-term average, charts |
| **3 · Reflection** | Strengths, weaknesses, plan for next week, and goal setting |
| **4 · Goal Review** | Evaluate last week's goals — what was met, what was missed |

Navigate using the sidebar on the left.
""")

st.divider()
st.caption("Data is stored locally in `data/timesheet.db` (SQLite).  All state is local — no cloud, no account.")
