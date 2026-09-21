"""Unit tests for tracker/suggestions.py."""

from tracker.models import Subject
from tracker.suggestions import build_suggestions, canonical_value


def _s(name, low, high):
    return Subject(name=name, low_level_label=low, high_level_label=high)


class TestBuildSuggestions:
    def test_one_list_per_grid_column(self):
        out = build_suggestions([_s("Reading", "leisure", "Personal")])
        assert out == {"Subject": ["Reading"], "Low Label": ["leisure"], "High Label": ["Personal"]}

    def test_deduplicates_and_sorts_case_insensitively(self):
        subjects = [
            _s("biology", "a", "Work"),
            _s("Bioinformatics", "b", "Work"),
            _s("Art", "c", "Personal"),
        ]
        out = build_suggestions(subjects)
        assert out["Subject"] == ["Art", "Bioinformatics", "biology"]
        assert out["High Label"] == ["Personal", "Work"]

    def test_drops_blank_and_strips(self):
        out = build_suggestions([_s(" Coding ", "", "Work")])
        assert out["Subject"] == ["Coding"]
        assert out["Low Label"] == []

    def test_empty(self):
        assert build_suggestions([]) == {"Subject": [], "Low Label": [], "High Label": []}


class TestCanonicalValue:
    def test_snaps_to_existing_spelling(self):
        assert canonical_value("work", ["Personal", "Work"]) == "Work"

    def test_new_value_is_stripped(self):
        assert canonical_value("  Chess ", ["Work"]) == "Chess"

    def test_none_becomes_empty(self):
        assert canonical_value(None, ["Work"]) == ""
