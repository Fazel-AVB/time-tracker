"""Unit tests for tracker/seasonal.py."""

from datetime import date

from tracker.seasonal import get_season, season_theme


class TestGetSeason:
    def test_march_is_spring(self):
        assert get_season(date(2026, 3, 1)) == "spring"

    def test_may_is_spring(self):
        assert get_season(date(2026, 5, 31)) == "spring"

    def test_june_is_summer(self):
        assert get_season(date(2026, 6, 1)) == "summer"

    def test_august_is_summer(self):
        assert get_season(date(2026, 8, 31)) == "summer"

    def test_september_is_autumn(self):
        assert get_season(date(2026, 9, 1)) == "autumn"

    def test_november_is_autumn(self):
        assert get_season(date(2026, 11, 30)) == "autumn"

    def test_december_is_winter(self):
        assert get_season(date(2026, 12, 1)) == "winter"

    def test_february_is_winter(self):
        assert get_season(date(2026, 2, 28)) == "winter"

    def test_january_is_winter(self):
        assert get_season(date(2026, 1, 15)) == "winter"


class TestSeasonTheme:
    def test_spring_theme(self):
        theme = season_theme(date(2026, 4, 20))
        assert theme["key"] == "spring"
        assert theme["name"] == "Spring"

    def test_summer_theme(self):
        assert season_theme(date(2026, 7, 6))["name"] == "Summer"

    def test_week_label_spans_monday_to_sunday(self):
        label = season_theme(date(2026, 4, 20))["week_label"]
        assert "April 20" in label
        assert "April 26, 2026" in label

    def test_has_colours_for_the_page(self):
        theme = season_theme(date(2026, 12, 7))
        assert {"gradient", "text_color", "border", "tag_bg", "tag_color", "emoji", "decorations"} <= set(theme)
