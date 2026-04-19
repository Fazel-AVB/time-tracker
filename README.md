# Time Tracker

A lightweight personal time, progress, and reflection tracker that runs entirely on your machine.
No cloud account, no subscription — just a local Streamlit app backed by a SQLite database.

![Architecture](../../figures/ai_generated/time_tracker_architecture.png)

---

## What it does

Time Tracker gives you four focused pages:

| Page | Purpose |
|---|---|
| **Weekly Table** | Log and edit hours per activity, per day. See daily and weekly totals at a glance. Export to Excel. |
| **Weekly Report** | Analytics dashboard — bar charts, a weekly trend line, subject breakdown, and a comparison to your long-term averages. |
| **Reflection** | Write down what went well, what could improve, and your plan for next week. Set quantitative goals for the coming week. |
| **Goal Review** | Evaluate last week's goals against the time you actually logged. Goals linked to a subject are auto-evaluated. |

All data is stored locally in `data/timesheet.db` (SQLite). Nothing leaves your machine.

---

## Requirements

- Python 3.10 or newer
- The packages listed in `requirements.txt`:

```
streamlit>=1.28
pandas>=2.0
plotly>=5.0
openpyxl>=3.1
```

---

## Installation

```bash
# 1. Clone the repository
git clone <repo-url>
cd time_tracker

# 2. (Recommended) Create a virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
streamlit run app.py
```

The app opens automatically in your browser at `http://localhost:8501`.

---

## Quick start

1. Go to **Weekly Table**.
2. Click **Add Subject** (bottom right) to define your activities — e.g. *Programming*, *Reading*, *Exercise* — and assign low-level and high-level category labels.
3. Enter hours in the table cells for each day, or use the **Log Time** form below the table.
4. Navigate to **Weekly Report** to see charts and comparisons to previous weeks.
5. At the end of the week, open **Reflection** to write a self-review and set goals for next week.
6. The following week, open **Goal Review** to evaluate how you did.

---

## Windows desktop shortcut

The repo includes two helper files to launch the app without opening a terminal:

- `launch.bat` — starts the Streamlit server
- `launch.vbs` — runs `launch.bat` silently (no console window)
- `time_tracker.ico` — app icon

To create a desktop shortcut with the custom icon:

1. Right-click `launch.vbs` → **Create shortcut**.
2. Move the shortcut to your Desktop.
3. Right-click the shortcut → **Properties** → **Change Icon**.
4. Browse to `time_tracker.ico` in the project folder and select it.
5. Click **OK** / **Apply**.

Double-clicking the shortcut will start the app and open it in your default browser automatically.

> **Note:** Your Python environment must have the dependencies installed and be on the system PATH (or you can edit `launch.bat` to activate your virtual environment first).

---

## Project structure

```
time_tracker/
├── app.py                  # Landing page — Streamlit entry point
├── requirements.txt
├── launch.bat              # Windows launcher (with console)
├── launch.vbs              # Windows launcher (silent, no console window)
├── time_tracker.ico        # App icon for Windows shortcut
├── data/
│   └── timesheet.db        # SQLite database (auto-created on first run)
├── pages/
│   ├── 1_Weekly_Table.py
│   ├── 2_Weekly_Report.py
│   ├── 3_Reflection.py
│   └── 4_Goal_Review.py
└── tracker/
    ├── models.py           # Dataclasses: Subject, TimeEntry, Reflection, Goal, GoalOutcome
    ├── database.py         # TimesheetDB — SQLite CRUD layer
    ├── analytics.py        # Pure-Python aggregation and analytics functions
    └── seasonal.py         # Seasonal banner HTML utility
```

---

## Data model

| Table | What it stores |
|---|---|
| `subjects` | Activities you track (name + two classification labels) |
| `time_entries` | Hours logged per subject per day |
| `reflections` | Weekly strengths / weaknesses / plan entries |
| `goals` | Goals set for an upcoming week (optional target hours, optional subject link) |
| `goal_outcomes` | Evaluation records for each goal (met / partial / not met + notes) |

---

## Tips

- **Label levels** — assign a *low-level label* (specific) and a *high-level label* (broad category) to each subject. The Weekly Report lets you switch between the two for different granularity.
- **Long-term averages** — the Weekly Report compares the current week to a configurable history window (2–26 weeks). Averages appear once you have logged more than one week.
- **Goal auto-evaluation** — link a goal to a subject when creating it. The Goal Review page will automatically look up how many hours you logged for that subject and suggest a met/partial/not-met status.
- **Backfilling** — you can navigate to any past week using the arrow buttons and log or edit entries retroactively.
