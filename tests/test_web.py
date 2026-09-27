"""Tests for tracker/web/app.py — the local web API and its security checks (Flask test client)."""

import io

import pytest
from flask.testing import FlaskClient

from tracker.web.app import TOKEN_HEADER, create_app

TOKEN = "test-token"
HOST = "127.0.0.1:8766"
WEEK = "2026-09-14"


class LocalClient(FlaskClient):
    """Sends requests as the browser does, to http://127.0.0.1:8766 (the Host the app accepts)."""

    def open(self, *args, **kwargs):
        kwargs.setdefault("base_url", f"http://{HOST}")
        return super().open(*args, **kwargs)


def make_client(app):
    app.test_client_class = LocalClient
    return app.test_client()


@pytest.fixture
def client(tmp_path):
    return make_client(create_app(tmp_path / "t.db", tmp_path / "exports", TOKEN, {HOST, "localhost:8766"}, notice="moved"))


def call(client, method, path, json=None):
    return client.open(path, method=method, json=json, headers={TOKEN_HEADER: TOKEN})


class TestSecurity:
    def test_api_needs_token(self, client):
        assert client.get(f"/api/week?week={WEEK}").status_code == 403
        assert client.get(f"/api/week?week={WEEK}", headers={TOKEN_HEADER: "wrong"}).status_code == 403

    def test_foreign_host_rejected(self, client):
        # DNS rebinding: a website's own name pointing at 127.0.0.1.
        r = client.get("/api/ping", base_url="http://evil.example:8766")
        assert r.status_code == 403

    def test_ping_without_token(self, client):
        assert client.get("/api/ping").get_json()["app"] == "time-tracker"

    def test_page_carries_token_and_is_not_cached(self, client):
        r = client.get("/")
        assert TOKEN in r.get_data(as_text=True)
        assert r.headers["Cache-Control"] == "no-store"
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]

    def test_static_files_served(self, client):
        for path in ["/static/app.js", "/static/charts.js", "/static/style.css", "/static/logo.svg", "/favicon.ico"]:
            assert client.get(path).status_code == 200, path


def test_info_notice_shown_once(client):
    assert call(client, "GET", "/api/info").get_json()["notice"] == "moved"
    assert call(client, "GET", "/api/info").get_json()["notice"] is None


def test_table_flow(client):
    s = call(client, "POST", "/api/week/rows", {"week": WEEK, "name": "Reading", "low": "leisure", "high": "Personal"}).get_json()
    r = call(client, "PUT", "/api/week/cell", {"week": WEEK, "subject_id": s["id"], "day": 1, "hours": 2.5})
    assert r.get_json() == {"row_total": 2.5, "day_totals": [0, 2.5, 0, 0, 0, 0, 0], "week_total": 2.5}
    view = call(client, "GET", f"/api/week?week={WEEK}").get_json()
    assert view["rows"][0]["days"][1] == 2.5

    renamed = call(client, "PUT", f"/api/week/rows/{s['id']}", {"week": WEEK, "name": "Reading", "low": "study", "high": "Personal"}).get_json()
    assert renamed["id"] != s["id"]

    xlsx = call(client, "GET", f"/api/week/xlsx?week={WEEK}")
    assert xlsx.status_code == 200 and xlsx.data[:2] == b"PK"

    assert call(client, "DELETE", f"/api/week/rows/{renamed['id']}?week={WEEK}").status_code == 200
    assert call(client, "GET", f"/api/week?week={WEEK}").get_json()["rows"] == []


def test_user_error_is_400_with_message(client):
    r = call(client, "POST", "/api/week/rows", {"week": WEEK, "name": "", "low": "x", "high": "y"})
    assert r.status_code == 400
    assert "required" in r.get_json()["error"]


def test_malformed_request_is_400_not_500(client):
    r = call(client, "PUT", "/api/week/cell", {"week": WEEK})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_entries_report_reflection_goals(client):
    s = call(client, "POST", "/api/week/rows", {"week": WEEK, "name": "Reading", "low": "l", "high": "H"}).get_json()
    e = call(client, "POST", "/api/entries", {"subject_id": s["id"], "date": "2026-09-15", "hours": 1, "notes": ""}).get_json()
    assert call(client, "PUT", f"/api/entries/{e['id']}", {"subject_id": s["id"], "date": "2026-09-15", "hours": 2}).status_code == 200

    rep = call(client, "GET", f"/api/report?week={WEEK}&level=low&history=4").get_json()
    assert rep["total"] == 2 and rep["level"] == "low"
    assert call(client, "GET", f"/api/report?week={WEEK}&history=x").status_code == 400
    assert b"Reading" in call(client, "GET", f"/api/report/csv?week={WEEK}").data

    assert call(client, "PUT", "/api/reflection", {"week": WEEK, "strengths": "focus"}).status_code == 200
    assert call(client, "GET", f"/api/reflection?week={WEEK}").get_json()["strengths"] == "focus"

    g = call(client, "POST", "/api/goals", {"week": WEEK, "description": "Read", "target_hours": 2, "subject_id": s["id"]}).get_json()
    review = call(client, "GET", f"/api/goals/review?week={WEEK}").get_json()
    assert review["goals"][0]["suggested"] == 1
    assert call(client, "PUT", f"/api/goals/{g['id']}/outcome", {"met": 1}).status_code == 200
    assert call(client, "GET", f"/api/goals/review?week={WEEK}").get_json()["summary"]["met"] == 1

    assert call(client, "DELETE", f"/api/entries/{e['id']}").status_code == 200


def test_export_answer(client, tmp_path):
    s = call(client, "POST", "/api/week/rows", {"week": WEEK, "name": "R", "low": "l", "high": "H"}).get_json()
    call(client, "PUT", "/api/week/cell", {"week": WEEK, "subject_id": s["id"], "day": 0, "hours": 1})
    res = call(client, "POST", "/api/export", {"week": WEEK, "action": "export"}).get_json()
    assert (tmp_path / "exports" / "time_report_2026-09-14.xlsx").exists()
    assert res["path"].endswith(".xlsx")
    assert call(client, "POST", "/api/export", {"week": WEEK, "action": "maybe"}).status_code == 400


def test_quit_calls_back(tmp_path):
    import threading
    called = threading.Event()
    c = make_client(create_app(tmp_path / "t.db", tmp_path / "e", TOKEN, {HOST}, on_quit=called.set))
    assert c.post("/api/quit", headers={TOKEN_HEADER: TOKEN}).status_code == 200
    assert called.wait(2)


def test_import_upload_preview_then_apply(client, tmp_path):
    from datetime import date

    from tracker.models import Subject, TimeEntry
    from tracker.database import TimesheetDB
    from tracker.week_report import build_week_report_xlsx

    with TimesheetDB(str(tmp_path / "other.db")) as other:
        s = other.add_subject(Subject(name="R", low_level_label="l", high_level_label="H"))
        other.add_entry(TimeEntry(date=date(2026, 9, 15), subject_id=s.id, duration_hours=2))
        data = build_week_report_xlsx(date(2026, 9, 14), other.get_entries_for_week(date(2026, 9, 14)))

    def form():
        return {"files": [(io.BytesIO(data), "time_report_2026-09-14.xlsx"), (io.BytesIO(b"junk"), "junk.xlsx")],
                "mode": "keep", "weeks": "{}"}

    headers = {TOKEN_HEADER: TOKEN}
    prev = client.post("/api/import/preview", data=form(), headers=headers, content_type="multipart/form-data").get_json()
    assert [f["ok"] for f in prev["files"]] == [True, False]
    assert call(client, "GET", f"/api/week?week={WEEK}").get_json()["rows"] == []  # preview wrote nothing

    done = client.post("/api/import", data=form(), headers=headers, content_type="multipart/form-data").get_json()
    assert done["weeks"] == [{"week_start": WEEK, "hours_before": 0, "hours_after": 2}]
    assert call(client, "GET", f"/api/week?week={WEEK}").get_json()["week_total"] == 2


def test_import_needs_files(client):
    r = client.post("/api/import", data={"mode": "keep"}, headers={TOKEN_HEADER: TOKEN}, content_type="multipart/form-data")
    assert r.status_code == 400
