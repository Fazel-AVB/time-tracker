"""Time Tracker: log hours per activity, see weekly reports, reflect and review goals.

The code lives in this package; your data lives in ~/.time_tracker (see paths.py).
"""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("time-tracker")
except PackageNotFoundError:  # running from a clone without `pip install -e .`
    __version__ = "0+unknown"
