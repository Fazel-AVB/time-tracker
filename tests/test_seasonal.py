"""Unit tests for tracker/seasonal.py."""

from datetime import date

from tracker.seasonal import get_season, seasonal_banner


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


class TestSeasonalBanner:
    def test_returns_html_string(self):
        banner = seasonal_banner(date(2026, 4, 20))
        assert isinstance(banner, str)
        assert "<div" in banner

    def test_spring_banner_contains_spring_label(self):
        banner = seasonal_banner(date(2026, 4, 20))
        assert "Spring" in banner

    def test_summer_banner_contains_summer_label(self):
        banner = seasonal_banner(date(2026, 7, 6))
        assert "Summer" in banner

    def test_banner_contains_week_dates(self):
        banner = seasonal_banner(date(2026, 4, 20))
        assert "April 20" in banner
        assert "April 26" in banner
