"""Tests for the US federal holiday calendar used by the scheduling guard."""

from datetime import date

from fedwatch.holidays import is_us_federal_holiday


def test_fixed_holiday():
    assert is_us_federal_holiday(date(2026, 12, 25))   # Christmas (Friday)


def test_observed_shift_saturday_to_friday():
    # July 4, 2026 is a Saturday -> observed Friday July 3.
    assert is_us_federal_holiday(date(2026, 7, 3))


def test_floating_holiday_thanksgiving():
    assert is_us_federal_holiday(date(2026, 11, 26))   # 4th Thursday of November


def test_regular_weekday_is_not_holiday():
    assert not is_us_federal_holiday(date(2026, 7, 8))
