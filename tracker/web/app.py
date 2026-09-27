"""The app's web server: one page (static/index.html) plus a small JSON API.

Each /api route parses the request and calls one function in
tracker/service.py; no rules about the data live here.

It listens on 127.0.0.1 only (see launcher.py), so no other computer can
reach it. Two more checks keep *websites* open in your browser from using it
(any page can send requests to localhost):

- Host header must be 127.0.0.1:<port> or localhost:<port>. This blocks "DNS
  rebinding", where a website points its own domain name at 127.0.0.1.
- Every /api call must carry the X-TT-Token header. The token is random per
  launch and only written into the page this server serves; other websites
  can't read that page, and a custom header can't be sent cross-site without
  the server's permission (which it never gives).

Do not remove either check: without them any website could read or delete
your timesheet while the app is open.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request

from .. import __version__, paths, service
from ..database import TimesheetDB

TOKEN_HEADER = "X-TT-Token"
TOKEN_PLACEHOLDER = "__TT_TOKEN__"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# Upload limit for the Import tab. A week's report is ~10 KB, so this fits
# years of weekly files and still refuses an accidental huge upload.
MAX_UPLOAD_BYTES = 32 * 1024 * 1024


def create_app(
    db_path: Path,
    export_dir: Path,
    token: str,
    allowed_hosts: set[str],
    on_quit: Callable[[], None] | None = None,
    notice: str | None = None,
) -> Flask:
    """notice: a one-time message for the page (e.g. "your data was moved to ...")."""
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    # Read by the launcher's idle watchdog (launcher.py) to exit after the page is closed.
    app.extensions["time_tracker"] = {"last_seen": time.time()}

    @contextmanager
    def db():
        with TimesheetDB(str(db_path)) as d:
            yield d

    def body() -> dict:
        return request.get_json(force=True, silent=True) or {}

    def week_arg(value=None):
        return service.parse_week(value if value is not None else request.args.get("week"))

    @app.before_request
    def guard():
        if request.host not in allowed_hosts:
            abort(403)
        if request.path.startswith("/api/") and request.path != "/api/ping":
            if request.headers.get(TOKEN_HEADER) != token:
                abort(403)
        app.extensions["time_tracker"]["last_seen"] = time.time()

    @app.after_request
    def headers(resp):
        # No other site may show this page in a frame (tricking you into
        # clicking its buttons), and the page loads nothing from the internet.
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )
        return resp

    @app.errorhandler(service.UserError)
    def user_error(e):
        return jsonify(error=str(e)), 400

    # A request missing a field or carrying text where a number belongs.
    # Flask picks the closest class, so UserError (a ValueError) keeps its own handler.
    @app.errorhandler(KeyError)
    @app.errorhandler(TypeError)
    @app.errorhandler(ValueError)
    def bad_request(e):
        return jsonify(error=f"Bad request ({type(e).__name__}: {e})"), 400

    @app.get("/")
    def index():
        html = resources.files("tracker.web").joinpath("static/index.html").read_text(encoding="utf-8")
        resp = Response(html.replace(TOKEN_PLACEHOLDER, token), mimetype="text/html")
        resp.headers["Cache-Control"] = "no-store"  # the token changes every launch
        return resp

    @app.get("/favicon.ico")
    def favicon():
        return app.send_static_file("time_tracker.ico")

    @app.get("/api/ping")
    def ping():
        # No token needed: the launcher uses it to find an already-running app,
        # and the page as a heartbeat (keeps the idle watchdog from stopping it).
        return jsonify(app="time-tracker", version=__version__)

    @app.get("/api/info")
    def info():
        state = app.extensions["time_tracker"]
        msg, state["notice"] = state.get("notice"), None  # shown once
        # Folders where earlier reports may be, shown on the Import tab as hints.
        legacy = paths.legacy_db_path().parent.parent / "history_exports"
        folders = [str(p) for p in (export_dir, legacy) if p.is_dir()]
        return jsonify(version=__version__, db=str(db_path), exports=str(export_dir), notice=msg,
                       can_open_folder=sys.platform == "win32", report_folders=folders)

    app.extensions["time_tracker"]["notice"] = notice

    # --- weekly table -------------------------------------------------------

    @app.get("/api/week")
    def week():
        with db() as d:
            return jsonify(service.week_table(d, week_arg()))

    @app.put("/api/week/cell")
    def week_cell():
        b = body()
        with db() as d:
            service.set_day_hours(d, week_arg(b.get("week")), int(b["subject_id"]), int(b["day"]), b.get("hours"))
            view = service.week_table(d, week_arg(b.get("week")))
        # Only the totals: re-drawing the whole table would move the cursor
        # out of the cell you are typing in.
        row = next((r for r in view["rows"] if r["id"] == int(b["subject_id"])), None)
        return jsonify(row_total=row["total"] if row else 0, day_totals=view["day_totals"],
                       week_total=view["week_total"])

    @app.post("/api/week/rows")
    def week_add_row():
        b = body()
        with db() as d:
            return jsonify(service.add_row(d, week_arg(b.get("week")), b.get("name"), b.get("low"), b.get("high")))

    @app.put("/api/week/rows/<int:subject_id>")
    def week_rename_row(subject_id):
        b = body()
        with db() as d:
            return jsonify(service.rename_row(d, week_arg(b.get("week")), subject_id,
                                              b.get("name"), b.get("low"), b.get("high")))

    @app.delete("/api/week/rows/<int:subject_id>")
    def week_remove_row(subject_id):
        with db() as d:
            service.remove_row(d, week_arg(), subject_id)
        return jsonify(ok=True)

    @app.get("/api/week/xlsx")
    def week_xlsx():
        ws = week_arg()
        with db() as d:
            data = service.week_table_xlsx(d, ws)
        return Response(data, mimetype=XLSX,
                        headers={"Content-Disposition": f'attachment; filename="timesheet_{ws}.xlsx"'})

    @app.post("/api/suggestions/hide")
    def hide_suggestion():
        b = body()
        with db() as d:
            service.hide_suggestion(d, str(b.get("column")), str(b.get("value", "")))
        return jsonify(ok=True)

    @app.delete("/api/subjects/<int:subject_id>")
    def delete_subject(subject_id):
        with db() as d:
            service.delete_subject(d, subject_id)
        return jsonify(ok=True)

    # --- entries ------------------------------------------------------------

    @app.post("/api/entries")
    def add_entry():
        with db() as d:
            return jsonify(service.add_entry(d, body()))

    @app.put("/api/entries/<int:entry_id>")
    def update_entry(entry_id):
        with db() as d:
            service.update_entry(d, entry_id, body())
        return jsonify(ok=True)

    @app.delete("/api/entries/<int:entry_id>")
    def delete_entry(entry_id):
        with db() as d:
            service.delete_entry(d, entry_id)
        return jsonify(ok=True)

    # --- report -------------------------------------------------------------

    @app.get("/api/report")
    def report():
        try:
            history = int(request.args.get("history", 8))
        except ValueError as e:
            raise service.UserError("history must be a number of weeks") from e
        with db() as d:
            return jsonify(service.week_report(d, week_arg(), request.args.get("level", "high"), history))

    @app.get("/api/report/csv")
    def report_csv():
        ws = week_arg()
        with db() as d:
            text = service.week_csv(d, ws)
        return Response(text, mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="timesheet_{ws}.csv"'})

    # --- reflection and goals -----------------------------------------------

    @app.get("/api/reflection")
    def reflection():
        with db() as d:
            return jsonify(service.reflection(d, week_arg()))

    @app.put("/api/reflection")
    def save_reflection():
        b = body()
        with db() as d:
            service.save_reflection(d, week_arg(b.get("week")), b)
        return jsonify(ok=True)

    @app.post("/api/goals")
    def add_goal():
        b = body()
        with db() as d:
            return jsonify(service.add_goal(d, week_arg(b.get("week")), b))

    @app.delete("/api/goals/<int:goal_id>")
    def delete_goal(goal_id):
        with db() as d:
            service.delete_goal(d, goal_id)
        return jsonify(ok=True)

    @app.get("/api/goals/review")
    def goal_review():
        with db() as d:
            return jsonify(service.goal_review(d, week_arg()))

    @app.put("/api/goals/<int:goal_id>/outcome")
    def save_outcome(goal_id):
        with db() as d:
            service.save_outcome(d, goal_id, body())
        return jsonify(ok=True)

    # --- end-of-week export -------------------------------------------------

    @app.get("/api/export")
    def export_pending():
        with db() as d:
            return jsonify(pending=service.pending_export(d))

    @app.post("/api/export")
    def export_answer():
        b = body()
        ws = week_arg(b.get("week"))
        with db() as d:
            if b.get("action") == "export":
                return jsonify(path=service.export_week(d, export_dir, ws))
            if b.get("action") == "skip":
                service.skip_export(d, ws)
                return jsonify(ok=True)
        raise service.UserError("action must be export or skip")

    # --- import Excel files ---------------------------------------------------

    def upload():
        # Only name and bytes are used: nothing uploaded is written to disk.
        files = [(f.filename or "file.xlsx", f.read()) for f in request.files.getlist("files")]
        if not files:
            raise service.UserError("Choose one or more .xlsx files first")
        try:
            weeks = json.loads(request.form.get("weeks") or "{}")
        except ValueError as e:
            raise service.UserError("weeks must be JSON") from e
        return files, request.form.get("mode", "keep"), weeks

    @app.post("/api/import/preview")
    def import_preview():
        files, mode, weeks = upload()
        return jsonify(service.preview_import(db_path, files, mode, weeks))

    @app.post("/api/import")
    def import_apply():
        files, mode, weeks = upload()
        with db() as d:
            return jsonify(service.import_excel(d, files, mode, weeks))

    @app.errorhandler(413)
    def too_large(_e):
        return jsonify(error=f"The files are larger than {MAX_UPLOAD_BYTES // 2**20} MB together; import fewer at a time"), 413

    @app.post("/api/open-exports")
    def open_exports():
        # Windows only (os.startfile): opens the folder in Explorer.
        if sys.platform != "win32":
            raise service.UserError(f"Open this folder yourself: {export_dir}")
        export_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(export_dir)  # noqa: S606 - a fixed local folder, never user input
        return jsonify(ok=True)

    @app.post("/api/quit")
    def quit_():
        if on_quit is not None:
            # After a moment, so this response still reaches the page.
            threading.Timer(0.3, on_quit).start()
        return jsonify(ok=True)

    return app
