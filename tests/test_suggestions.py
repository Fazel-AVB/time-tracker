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


from tracker.suggestions import hide_value, parse_hidden, unhide_values  # noqa: E402


class TestHiddenSuggestions:
    def test_hidden_values_filtered_ignoring_case(self):
        subjects = [_s("Programming", "ghg", "kjh"), _s("Programming", "education", "Studies")]
        out = build_suggestions(subjects, hidden={"Low Label": ["GHG"]})
        assert out["Low Label"] == ["education"]
        assert out["Subject"] == ["Programming"]  # other columns untouched

    def test_columns_are_independent(self):
        subjects = [_s("Work", "Work", "Work")]
        out = build_suggestions(subjects, hidden={"Subject": ["Work"]})
        assert out == {"Subject": [], "Low Label": ["Work"], "High Label": ["Work"]}

    def test_parse_hidden_tolerates_missing_and_corrupt(self):
        assert parse_hidden(None) == {"Subject": [], "Low Label": [], "High Label": []}
        assert parse_hidden("not json") == {}
        assert parse_hidden('{"Low Label": ["ghg", 3]}')["Low Label"] == ["ghg"]

    def test_hide_is_idempotent_and_copies(self):
        h0 = parse_hidden(None)
        h1 = hide_value(h0, "Low Label", "ghg")
        h2 = hide_value(h1, "Low Label", "GHG")
        assert h2["Low Label"] == ["ghg"]
        assert h0["Low Label"] == []  # input not mutated

    def test_hide_unknown_column_raises(self):
        import pytest
        with pytest.raises(ValueError):
            hide_value({}, "Nope", "x")

    def test_unhide(self):
        h = hide_value(parse_hidden(None), "High Label", "Work")
        assert unhide_values(h, {"High Label": "work"})["High Label"] == []
