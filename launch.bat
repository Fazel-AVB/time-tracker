@echo off
rem Double-click to start the time tracker in your browser.
rem The window stays open on exit so you can read any error.
cd /d "%~dp0"

rem Prefer the launcher's Python; fall back to "py" if "python" is not found.
where python >nul 2>&1 && (set PY=python) || (set PY=py)

%PY% -m streamlit run app.py
echo.
echo --- streamlit exited. Press a key to close. ---
pause >nul
