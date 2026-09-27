"""Start the app: run the local web server and open it in your browser.

Entry point of `time-tracker-gui` (a gui-script in pyproject.toml: on Windows
pip makes it a .exe that starts without a console window; the desktop
shortcut points at it) and of `time-tracker gui`.

Lifecycle, since there may be no console window to close:
- a second launch while the app already runs just opens the browser on it;
- the page's "Quit" button stops the server;
- the server also stops by itself when no page has contacted it for
  IDLE_EXIT_SECONDS, so closing the browser tab doesn't leave an invisible
  process behind.
"""
from __future__ import annotations

import json
import secrets
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

from .. import paths

# Not Streamlit's 8501 (an old launcher may still be running) and not
# tgqa's 8765, so both apps can be open at once.
DEFAULT_PORT = 8766
# The page pings the server once a minute (app.js, HEARTBEAT_MS). Browsers
# slow timers in background tabs to at most about once a minute, so 10 min
# without any request means no tab is open (or the laptop was asleep).
IDLE_EXIT_SECONDS = 600


def _existing_app(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as r:
            return json.load(r).get("app") == "time-tracker"
    except Exception:  # noqa: BLE001 - anything else on that port, or nothing
        return False


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _redirect_output_if_no_console() -> None:
    # Started as time-tracker-gui.exe (pythonw) there is no console:
    # sys.stdout and sys.stderr are None and any print would crash. Send them
    # to a log file instead, which also keeps error details for troubleshooting.
    if sys.stdout is None or sys.stderr is None:
        paths.home().mkdir(parents=True, exist_ok=True)
        log = open(paths.log_path(), "w", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives as long as the process
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


def main(port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    # Checked before touching gui.log: a second launch must not truncate the
    # log of the instance that is already running.
    if _existing_app(port):
        if open_browser:
            webbrowser.open(f"http://127.0.0.1:{port}/")
        if sys.stdout is not None:
            print(f"Time Tracker is already running at http://127.0.0.1:{port}/")
        return
    _redirect_output_if_no_console()
    if not _port_free(port):
        port = _free_port()  # something else uses the port; any free one works

    import logging

    from werkzeug.serving import make_server

    from .app import create_app

    # Werkzeug logs every request; the page's heartbeat would flood the log.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    notice = None
    adopted = paths.adopt_legacy_db()
    if adopted is not None:
        notice = (f"Your data was copied from {adopted} to {paths.db_path()}, where it lives from now on. "
                  "The old file is kept as a backup; you can delete it once everything looks right.")
        print(notice)

    token = secrets.token_urlsafe(32)
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    server = None

    def stop() -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    app = create_app(paths.db_path(), paths.export_dir(), token, hosts, on_quit=stop, notice=notice)
    # 127.0.0.1, never 0.0.0.0: only programs on this computer can connect.
    server = make_server("127.0.0.1", port, app, threaded=True)
    state = app.extensions["time_tracker"]

    def watchdog() -> None:
        while True:
            time.sleep(30)
            if time.time() - state["last_seen"] > IDLE_EXIT_SECONDS:
                print("No open page for a while; stopping.")
                stop()
                return

    threading.Thread(target=watchdog, name="idle-watchdog", daemon=True).start()

    url = f"http://127.0.0.1:{port}/"
    print(f"Time Tracker running at {url}  (Ctrl+C or the Quit button to stop)")
    print(f"Data: {paths.db_path()}")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
