"""
Suggestion lists for the Subject / Low Label / High Label pickers.

The Weekly Table's "New subject" boxes offer previously used values. This
module builds those lists from the stored subjects and snaps free-typed input
onto an existing spelling. Pure functions, unit-tested in
tests/test_suggestions.py.
"""
from __future__ import annotations

import json
from typing import Iterable, List, Mapping, Optional

from tracker.models import Subject

# settings-table key holding the values removed from the suggestions with ✕,
# as JSON {grid column name: [value, ...]}. Removal only hides a value from the
# pickers; subjects and hours that use it are untouched.
HIDDEN_SETTING_KEY = "hidden_suggestions"

# Grid column name -> Subject attribute. The column names are the ones built by
# analytics.week_pivot and the "New subject" boxes (tracker/web/static/app.js).
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


def build_suggestions(
    subjects: Iterable[Subject],
    hidden: Optional[Mapping[str, Iterable[str]]] = None,
) -> dict[str, List[str]]:
    """
    Return {grid column name: sorted unique values used so far}, minus the
    values the user removed (`hidden`, compared ignoring case).
    """
    subjects = list(subjects)
    hidden = hidden or {}
    out = {}
    for column, attr in SUGGESTION_FIELDS.items():
        drop = {v.casefold() for v in hidden.get(column, [])}
        out[column] = [v for v in _unique_sorted(getattr(s, attr) for s in subjects)
                       if v.casefold() not in drop]
    return out


def parse_hidden(raw: Optional[str]) -> dict[str, List[str]]:
    """Decode the settings value; missing or corrupt JSON means nothing hidden."""
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {c: [v for v in data.get(c, []) if isinstance(v, str)] for c in SUGGESTION_FIELDS}


def hide_value(hidden: Mapping[str, List[str]], column: str, value: str) -> dict[str, List[str]]:
    """Return a copy of `hidden` with value added to column (no duplicates)."""
    if column not in SUGGESTION_FIELDS:
        raise ValueError(f"Unknown suggestion column: {column!r}")
    out = {c: list(hidden.get(c, [])) for c in SUGGESTION_FIELDS}
    if value.casefold() not in {v.casefold() for v in out[column]}:
        out[column].append(value)
    return out


def unhide_values(hidden: Mapping[str, List[str]], values: Mapping[str, str]) -> dict[str, List[str]]:
    """
    Return a copy of `hidden` without the given {column: value} pairs. Used when
    the user types a removed value again: using it on purpose brings it back.
    """
    out = {c: list(hidden.get(c, [])) for c in SUGGESTION_FIELDS}
    for column, value in values.items():
        out[column] = [v for v in out.get(column, []) if v.casefold() != value.casefold()]
    return out


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
