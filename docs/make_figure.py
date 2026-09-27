"""Generate docs/architecture.svg, the overview figure shown in README.md.

Plain SVG written by hand (standard library only), same approach as
telegram_qa/docs/make_figure.py, so it renders on GitHub and needs no
plotting package. Replaces time_tracker_architecture.png, which showed the
Streamlit app (v0.1). Re-run after changing what it shows (tabs, modules,
port, data folder):

    python docs/make_figure.py

Facts it mirrors, kept in sync by hand: the five tabs (tracker/web/static/
index.html), the port 8766 (tracker/web/launcher.py DEFAULT_PORT), the data
folder ~/.time_tracker (tracker/paths.py) and the module names in tracker/.
"""
from pathlib import Path
from xml.sax.saxutils import escape

W, H = 1280, 720
# The app's palette (tracker/web/static/style.css).
PAGE, PAGE_SOFT = "#7C3AED", "#EDE9FE"
SERVER, SERVER_SOFT = "#2563EB", "#DBEAFE"
DATA, DATA_SOFT = "#6b7785", "#f1f4f8"
INK, MUTED, LINE, EDGE = "#1E1B4B", "#5f6b7a", "#c9d1db", "#8a94a3"
out = []
a = out.append


def text(x, y, s, size=12, weight=400, fill=MUTED, anchor="start", style=""):
    a(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{style}>{escape(s)}</text>')


def box(x, y, w, h, title, lines, color, soft):
    a(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{soft}" stroke="{color}" stroke-width="1.5"/>')
    cx = x + w / 2
    text(cx, y + 26, title, 15, 700, INK, "middle")
    for i, ln in enumerate(lines):
        text(cx, y + 46 + i * 17, ln, 12, 400, MUTED, "middle")


def layer(x, y, name, note, color):
    # One text element with tspans: the note follows the name at whatever
    # width the viewer's font gives it, instead of a guessed x position.
    a(f'<text x="{x}" y="{y}" font-size="13"><tspan font-weight="800" fill="{color}" letter-spacing="1">{name}</tspan>'
      f'<tspan dx="10" fill="{MUTED}">{escape(note)}</tspan></text>')


def arrow(d, label=None, lx=0, ly=0, anchor="start"):
    a(f'<path d="{d}" fill="none" stroke="{MUTED}" stroke-width="2" marker-end="url(#arrow)"/>')
    if label:
        text(lx, ly, label, 11, 600, MUTED, anchor)


a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
  'font-family="system-ui, -apple-system, \'Segoe UI\', Roboto, Helvetica, Arial, sans-serif">')
a('<title>How Time Tracker works</title>')
a('<desc>The desktop icon starts a small web server on this computer and opens its page in the browser. '
  'The page has five tabs: Weekly Table, Weekly Report, Reflection, Goal Review and Import. Every change goes to the '
  'server, which stores it in timesheet.db in the ~/.time_tracker folder and writes end-of-week Excel reports '
  'there; the Import tab reads such reports back in. Code updates come from GitHub with git pull and never touch '
  'that folder.</desc>')
a('<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
  f'<path d="M0,0 L10,5 L0,10 z" fill="{MUTED}"/></marker></defs>')
# Own background, so the figure reads the same on GitHub's light and dark themes.
a(f'<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="16" fill="#ffffff" stroke="#e3e7ec"/>')

text(40, 52, "How Time Tracker works", 26, 800, INK)
text(40, 78, "Log hours per activity, see weekly reports, reflect and review goals. "
     "A small web app that runs in your browser, entirely on your computer.", 14, 400, MUTED)

# GitHub, outside the computer: the only thing that comes in is code.
a('<circle cx="105" cy="222" r="42" fill="#1f2328"/>')
a('<path transform="translate(105,222) scale(1.6) translate(-8,-8)" fill="#fff" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>')
text(105, 288, "GitHub", 15, 700, INK, "middle")
text(105, 306, "the code only", 12, 400, MUTED, "middle")

# Edge of the computer
a(f'<rect x="210" y="112" width="1040" height="538" rx="18" fill="none" stroke="{EDGE}" stroke-width="1.5" stroke-dasharray="7 6"/>')
text(232, 138, "YOUR COMPUTER", 12, 800, EDGE, style=' letter-spacing="1.5"')

# --- left column: code and launcher
box(250, 168, 180, 110, "Code", ["the git clone,", "installed with", "pip install -e ."], DATA, "#ffffff")
arrow("M150,222 H246", "git pull", 178, 212, "middle")
arrow("M340,278 V326")
box(250, 330, 180, 96, "Desktop icon", ["time-tracker-gui", "starts the server,", "opens the browser"], DATA, "#ffffff")
arrow("M430,378 H466")

# --- layer 1: the page
layer(470, 154, "BROWSER PAGE", "http://127.0.0.1:8766 · five tabs", PAGE)
# Five boxes of 142 with gaps of 9.5 fill x = 470…1218, the width of the layers below.
tabs = [("Weekly Table", ["hours per subject", "and day"]),
        ("Weekly Report", ["totals, averages,", "charts, CSV"]),
        ("Reflection", ["the week in words,", "next week's goals"]),
        ("Goal Review", ["met / partial /", "not met"]),
        ("Import", ["Excel reports", "from earlier runs"])]
for i, (title, lines) in enumerate(tabs):
    box(470 + i * 151.5, 168, 142, 86, title, lines, PAGE, PAGE_SOFT)
# Into web/app.py, the part that receives the page's requests.
arrow("M585,256 V326", "every change, sent with a key", 596, 284)
text(596, 299, "that changes at each start", 11, 400, MUTED)

# --- layer 2: the local server
# Starts right of the arrow into web/app.py (x=585) so the arrow doesn't cross it.
# Left-aligned on purpose: text-anchor="end" on a text with tspans overlaps in some renderers.
layer(740, 316, "LOCAL SERVER", "on this computer; stops 10 min after you close the tab", SERVER)
box(470, 330, 230, 96, "web/app.py", ["Flask, on this computer only;", "checks host and key"], SERVER, SERVER_SOFT)
arrow("M700,378 H736")
box(740, 330, 230, 96, "service.py", ["what each button does,", "checks what you typed"], SERVER, SERVER_SOFT)
arrow("M970,378 H1006")
box(1010, 330, 208, 96, "analytics.py", ["weekly totals, averages,", "goal suggestions"], SERVER, SERVER_SOFT)

# --- layer 3: the data
# Below the data, so the arrows into it cross no text.
layer(750, 630, "YOUR DATA", "~/.time_tracker · updates never touch it", DATA)
arrow("M855,426 V498")
# 750…960: centred under service.py (x=855), leaving a 50-wide gap for the import arrow.
x, y, w, h = 750, 500, 210, 104
a(f'<path d="M{x},{y+14} v{h-28} a{w/2},14 0 0 0 {w},0 v-{h-28}" fill="{DATA_SOFT}" stroke="{DATA}" stroke-width="1.5"/>')
a(f'<ellipse cx="{x+w/2}" cy="{y+14}" rx="{w/2}" ry="14" fill="#f8fafc" stroke="{DATA}" stroke-width="1.5"/>')
text(x + w / 2, y + 50, "timesheet.db", 15, 700, INK, "middle")
text(x + w / 2, y + 68, "subjects, hours, reflections,", 12, 400, MUTED, "middle")
text(x + w / 2, y + 84, "goals and their outcomes", 12, 400, MUTED, "middle")
arrow("M1114,426 V496", "week_report.py", 1124, 466)
# folder
x, y, w, h = 1010, 500, 208, 104
a(f'<path d="M{x},{y+10} h70 l10,-10 h{w-80} v{h} h-{w} z" fill="{DATA_SOFT}" stroke="{DATA}" stroke-width="1.5" stroke-linejoin="round"/>')
text(x + w / 2, y + 44, "history_exports/", 15, 700, INK, "middle")
text(x + w / 2, y + 64, "an Excel report per week,", 12, 400, MUTED, "middle")
text(x + w / 2, y + 80, "when you say yes at week's end", 12, 400, MUTED, "middle")
# The round trip: the Import tab reads these reports (or any older ones) back into the database.
arrow("M1008,566 H964", "import", 986, 556, "middle")

# What crosses the edge
x, y, w, h = 250, 500, 450, 104
a(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#ffffff" stroke="{LINE}" stroke-width="1.5"/>')
text(x + 18, y + 24, "WHAT CROSSES THE DASHED LINE", 11, 800, EDGE, style=' letter-spacing="1"')
rows = [("IN", "Code, when you run git pull."),
        ("OUT", "Nothing. The page loads nothing from the internet,"),
        ("", "and other computers can't reach the server.")]
for i, (label, s) in enumerate(rows):
    yy = y + 48 + i * 17
    if label:
        text(x + 18, yy, label, 11.5, 800, PAGE if label == "IN" else "#c0362c")
    text(x + 66, yy, s, 12, 400, INK)

text(40, 690, "Update: git pull in the clone. Your data in ~/.time_tracker stays as it is. "
     "Commands: time-tracker, time-tracker shortcut, time-tracker import-excel.", 12.5, 400, MUTED)
a('</svg>')
Path(__file__).with_name("architecture.svg").write_text("\n".join(out) + "\n", encoding="utf-8")
