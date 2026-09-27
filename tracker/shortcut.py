"""Create a desktop shortcut to the app (time-tracker-gui.exe) with its icon. Windows only.

pip makes .venv\\Scripts\\time-tracker-gui.exe with a generic icon, and an
.exe's own icon can't be changed without rebuilding it. A shortcut can point
at the .exe and carry any icon, so that is what `time-tracker shortcut` makes.

Windows has no Python-standard way to write a .lnk file; its own scripting
object (WScript.Shell, via PowerShell) does, and needs no extra package.
Same approach as tgqa/shortcut.py in the telegram_qa project.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

SHORTCUT_NAME = "Time Tracker.lnk"

# Paths are handed over in environment variables, not pasted into the script
# text, so quotes or spaces in a folder name can't break the PowerShell code.
PS_SCRIPT = r"""
$desktop = [Environment]::GetFolderPath('Desktop')
$path = Join-Path $desktop $env:TT_NAME
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
$s.TargetPath = $env:TT_TARGET
$s.WorkingDirectory = Split-Path $env:TT_TARGET
$s.IconLocation = $env:TT_ICON + ',0'
$s.Description = 'Time Tracker: log hours, weekly report, reflection'
$s.Save()
Write-Output $path
"""


def gui_exe() -> Path:
    # sys.executable is .venv\Scripts\python.exe when the command runs from
    # its venv; pip puts time-tracker-gui.exe next to it.
    exe = Path(sys.executable).with_name("time-tracker-gui.exe")
    if exe.exists():
        return exe
    found = shutil.which("time-tracker-gui")
    if found:
        return Path(found)
    raise RuntimeError("time-tracker-gui.exe not found. Run `python -m pip install -e .` in the time_tracker folder first.")


def icon_path() -> Path:
    # A real file on disk with a normal or editable install, which is what the shortcut needs.
    return Path(str(resources.files("tracker.web").joinpath("static", "time_tracker.ico")))


def create_desktop_shortcut() -> Path:
    """Create (or replace) 'Time Tracker.lnk' on the desktop. Returns its path."""
    if sys.platform != "win32":
        raise RuntimeError("`time-tracker shortcut` works on Windows only. Elsewhere, start the app with `time-tracker`.")
    env = {**os.environ, "TT_NAME": SHORTCUT_NAME, "TT_TARGET": str(gui_exe()), "TT_ICON": str(icon_path())}
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_SCRIPT],
        env=env, capture_output=True, text=True, errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell couldn't create the shortcut: {result.stderr.strip()}")
    return Path(result.stdout.strip())
