"""Goals for a week, a month or a year, linked to tasks, and the review page at
the end of each period. Part of tools/tasks.py (the `goal`, `goals` and
`review` commands); standard library only.

A goal is a file in Goals/ with the same shape as a task (frontmatter, Notes,
Log). Tasks count toward a goal by listing it in `projects`, the way they
list a project. Goals form a tree through `parent`: week -> month -> year.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

import tasks as T

HOUSEHOLD = "Household"
GOAL_STATUSES = ["active", "achieved", "partial", "missed", "dropped"]
VERDICTS = GOAL_STATUSES[1:]
LEVELS = {"year": 0, "month": 1, "week": 2}
PERIOD_RE = re.compile(r"^(\d{4})(?:-(\d{2})|-W(\d{2}))?$")
PERIOD_HELP = "period must be YYYY, YYYY-MM or YYYY-Www (an ISO week, e.g. 2026-W47)"


# --- periods ----------------------------------------------------------------

def parse_period(value) -> tuple[str, dt.date, dt.date] | None:
    """(kind, first day, last day) of `2026`, `2026-11` or `2026-W47`; None if invalid."""
    match = PERIOD_RE.match(str(value or "").strip())
    if not match:
        return None
    year = int(match.group(1))
    if match.group(2):
        month = int(match.group(2))
        if not 1 <= month <= 12:
            return None
        first = dt.date(year, month, 1)
        return "month", first, first.replace(day=T.last_day(first))
    if match.group(3):
        try:
            first = dt.date.fromisocalendar(year, int(match.group(3)), 1)
        except ValueError:  # week 0, or week 53 in a 52-week year
            return None
        return "week", first, first + dt.timedelta(days=6)
    return "year", dt.date(year, 1, 1), dt.date(year, 12, 31)


def period_of(kind: str, d: dt.date) -> str:
    """The year, month or ISO week that contains `d`."""
    if kind == "year":
        return str(d.year)
    if kind == "month":
        return f"{d.year}-{d.month:02d}"
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def contains(outer: str, inner: str) -> bool:
    """Whether a goal for `outer` can be the parent of a goal for `inner`: a
    longer period that holds it. A week belongs to the month and year of its
    Thursday, as ISO weeks do (2026-W49, 30 Nov - 6 Dec, is in December)."""
    a, b = parse_period(outer), parse_period(inner)
    if not a or not b or LEVELS[a[0]] >= LEVELS[b[0]]:
        return False
    anchor = b[1] + dt.timedelta(days=3) if b[0] == "week" else b[1]
    return period_of(a[0], anchor) == str(outer).strip()


def default_period(kind: str, today: dt.date | None = None) -> str:
    """The period to review: the one that just ended, or the current one when
    it ends within two days."""
    today = today or dt.date.today()
    current = period_of(kind, today)
    _, first, last = parse_period(current)
    if (last - today).days <= 2:
        return current
    return period_of(kind, first - dt.timedelta(days=1))


def current_periods(today: dt.date | None = None) -> list[str]:
    today = today or dt.date.today()
    return [period_of(kind, today) for kind in ("week", "month", "year")]
