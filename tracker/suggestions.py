"""
Suggestion lists for the Subject / Low Label / High Label pickers.

The Weekly Table offers previously used values as dropdown options, both inside
the grid and in the "New subject" form. This module builds those lists from the
stored subjects and snaps free-typed input onto an existing spelling. No
Streamlit imports: pure functions, unit-tested in tests/test_suggestions.py.
"""
from __future__ import annotations

from typing import Iterable, List

from tracker.models import Subject

# Grid column name -> Subject attribute. The column names are the ones built by
# analytics.week_pivot and pages/1_Weekly_Table.py.
SUGGESTION_FIELDS = {
    "Subject": "name",
    "Low Label": "low_level_label",
    "High Label": "high_level_label",
}


def _unique_sorted(values: Iterable[str]) -> List[str]:
    """Strip, drop blanks, dedupe exactly, sort case-insensitively."""
    cleaned = {v.strip() for v in values if v and v.strip()}
    # Case-insensitive sort so "biology" and "Bioinformatics" sit together
    # instead of all capitalised values coming first.
    return sorted(cleaned, key=lambda v: (v.casefold(), v))


def build_suggestions(subjects: Iterable[Subject]) -> dict[str, List[str]]:
    """Return {grid column name: sorted unique values used so far}."""
    subjects = list(subjects)
    return {
        column: _unique_sorted(getattr(s, attr) for s in subjects)
        for column, attr in SUGGESTION_FIELDS.items()
    }


def canonical_value(typed: str, existing: Iterable[str]) -> str:
    """
    Return the existing spelling when `typed` equals one ignoring case, else
    the stripped input. Matching is case-insensitive, so without this, typing
    "work" when "Work" exists would silently start a second label.
    """
    typed = (typed or "").strip()
    for value in existing:
        if value.casefold() == typed.casefold():
            return value
    return typed
