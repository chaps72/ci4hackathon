"""US federal holidays (observed) - used to skip scheduled digests.

No external dependencies: computes fixed and nth-weekday holidays and applies
the observed-day shift (Saturday -> Friday, Sunday -> Monday).
"""

from datetime import date, timedelta


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th (1-based) given weekday (Mon=0) of a month."""
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    if d.weekday() == 5:      # Saturday -> Friday
        return d - timedelta(days=1)
    if d.weekday() == 6:      # Sunday -> Monday
        return d + timedelta(days=1)
    return d


def us_federal_holidays(year: int) -> set:
    fixed = [
        date(year, 1, 1),     # New Year's Day
        date(year, 6, 19),    # Juneteenth
        date(year, 7, 4),     # Independence Day
        date(year, 11, 11),   # Veterans Day
        date(year, 12, 25),   # Christmas
    ]
    floating = [
        _nth_weekday(year, 1, 0, 3),    # MLK Day - 3rd Mon Jan
        _nth_weekday(year, 2, 0, 3),    # Washington's Birthday - 3rd Mon Feb
        _last_weekday(year, 5, 0),      # Memorial Day - last Mon May
        _nth_weekday(year, 9, 0, 1),    # Labor Day - 1st Mon Sep
        _nth_weekday(year, 10, 0, 2),   # Columbus Day - 2nd Mon Oct
        _nth_weekday(year, 11, 3, 4),   # Thanksgiving - 4th Thu Nov
    ]
    days = {_observed(d) for d in fixed} | set(floating)
    # New Year's observed from next year can land on Dec 31 of this year.
    if _observed(date(year + 1, 1, 1)).year == year:
        days.add(_observed(date(year + 1, 1, 1)))
    return days


def is_us_federal_holiday(d: date) -> bool:
    return d in us_federal_holidays(d.year)
