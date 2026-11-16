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


# --- goal files ---------------------------------------------------------------

def load_goals() -> list[dict]:
    goals = []
    for path in sorted(T.GOALS.rglob("*.md")) if T.GOALS.is_dir() else []:
        lines, _ = T.split(path.read_text(encoding="utf-8"))
        if lines is None:
            continue
        meta = T.parse(lines)
        if "goal" not in T.as_list(meta.get("tags")):
            continue
        meta["_path"] = path
        goals.append(meta)
    return goals


def index_goals() -> dict[str, dict]:
    """Every goal by lower-case file name (what `[[links]]` point at)."""
    return {g["_path"].stem.lower(): g for g in load_goals()}


def title(g: dict) -> str:
    return g.get("title") or g["_path"].stem


def key(g: dict) -> str:
    return g["_path"].stem.lower()


def parent_key(g: dict) -> str:
    return T.name_of(g.get("parent") or "").lower()


def lookup_goal(name: str, goals: dict | None = None) -> dict | None:
    """The goal with this file name or title (ignoring case and punctuation), else None."""
    goals = index_goals() if goals is None else goals
    if T.name_of(name).lower() in goals:
        return goals[T.name_of(name).lower()]
    exact = [g for g in goals.values()
             if T.squash(name) in (T.squash(title(g)), T.squash(g["_path"].stem))]
    return exact[0] if len(exact) == 1 else None


def find_goal(name: str, goals: dict | None = None) -> dict:
    """Like lookup_goal, also accepting the only goal whose name contains `name`."""
    goals = index_goals() if goals is None else goals
    found = lookup_goal(name, goals)
    if found:
        return found
    near = [g for g in goals.values()
            if T.squash(name) and T.squash(name) in T.squash(g["_path"].stem)]
    if len(near) == 1:
        return near[0]
    hint = "; ".join(T.rel(g["_path"]) for g in near[:5]) or "no match"
    sys.exit(f"cannot pick one goal for {name!r}: {hint}")


def new_goal_path(name: str, period: str) -> Path:
    """Goals/<title>.md, or Goals/<title> (<period>).md when the title is taken."""
    base = T.file_name(re.sub(r"\s*\(\d{4}(?:-\d{2}|-W\d{2})?\)$", "", name.strip()), "Goal")
    path = T.GOALS / f"{base}.md"
    if path.exists():
        path = T.GOALS / f"{base} ({period}).md"
    n = 2
    while path.exists():
        path, n = T.GOALS / f"{base} ({period}) {n}.md", n + 1
    return path


def as_number(value) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def fmt(n: float) -> str:
    return str(int(n)) if n == int(n) else str(round(n, 2))


def number(value: str) -> str:
    n = as_number(value)
    if n is None:
        sys.exit(f"expected a number, got {value!r}")
    return fmt(n)


def check_period(value: str) -> str:
    if parse_period(value) is None:
        sys.exit(f"{PERIOD_HELP}; got {value!r}")
    return value.strip()


def save(path: Path, changes: dict, message: str | None = None) -> None:
    """Apply field changes to a goal, keep completedDate in step with the
    status, stamp dateModified and log what happened."""
    lines, body = T.split(path.read_text(encoding="utf-8"))
    if lines is None:
        sys.exit(f"{T.rel(path)} has no frontmatter")
    meta = T.parse(lines)
    status = changes.get("status")
    if status and status != "active" and not meta.get("completedDate") \
            and "completedDate" not in changes:
        changes["completedDate"] = dt.date.today().isoformat()
    elif status == "active" and meta.get("completedDate"):
        changes["completedDate"] = None
    for k, value in changes.items():
        lines = T.set_key(lines, k, value)
    lines = T.set_key(lines, "dateModified", T.now())
    if status:
        message = f"status -> {status}" + (f": {message}" if message else "")
    if message:
        body = T.add_log(body, message)
    T.write(path, lines, body)


def blocked_entry(g: dict) -> dict:
    return {"uid": T.link(g["_path"].stem), "reltype": "FINISHTOSTART"}


def checked_parent(name: str, period: str, goals: dict) -> dict:
    parent = find_goal(name, goals)
    if not contains(str(parent.get("period") or ""), period):
        sys.exit(f"{title(parent)} ({parent.get('period')}) cannot be the parent of a "
                 f"{period} goal: the parent must be a longer period that contains {period}")
    return parent


# --- commands -----------------------------------------------------------------

def cmd_goal_new(args) -> None:
    period = check_period(args.period)
    owner = T.person(args.owner)
    goals = index_goals()
    lines = (T.render("title", args.title.strip()) + T.render("type", "goal")
             + T.render("period", period) + T.render("owner", T.link(owner))
             + T.render("status", "active"))
    if args.parent:
        lines += T.render("parent", T.link(checked_parent(args.parent, period, goals)["_path"].stem))
    if args.blocked_by:
        lines += T.render("blockedBy", [blocked_entry(find_goal(args.blocked_by, goals))])
    if args.target is not None:
        lines += T.render("target", number(args.target)) + T.render("progress", "0")
    if args.unit:
        lines += T.render("unit", args.unit.strip())
    if args.project:
        lines += T.render("projects", [T.link(p) for p in args.project.split(",") if p.strip()])
    stamp = T.now()
    lines += (T.render("dateCreated", stamp) + T.render("dateModified", stamp)
              + T.render("tags", ["goal"]))
    body = T.add_log("\n" + (args.m.strip() + "\n" if args.m else ""), f"created for {period}")
    path = new_goal_path(args.title, period)
    T.new_page(path, lines, body)
    print(T.rel(path))


def cmd_goal_set(args) -> None:
    goals = index_goals()
    g = find_goal(args.goal, goals)
    changes: dict = {}
    for pair in args.pairs:
        if "=" not in pair:
            sys.exit(f"expected key=value, got {pair!r}")
        k, value = (s.strip() for s in pair.split("=", 1))
        changes[k] = T.coerce(k, value) if value else None
    status = changes.get("status")
    if status and status not in GOAL_STATUSES:
        sys.exit(f"unknown goal status {status!r}; use one of {', '.join(GOAL_STATUSES)}")
    if changes.get("period"):
        changes["period"] = check_period(changes["period"])
    for k in ("target", "progress"):
        if changes.get(k) is not None:
            changes[k] = number(changes[k])
    if changes.get("owner"):
        changes["owner"] = T.link(T.person(T.plain(changes["owner"])))
    if changes.get("parent"):
        period = changes.get("period") or str(g.get("period") or "")
        changes["parent"] = T.link(checked_parent(T.plain(changes["parent"]), period, goals)["_path"].stem)
    if args.blocked_by or args.unblock:
        deps = T.as_list(g.get("blockedBy"))
        if args.blocked_by:
            other = find_goal(args.blocked_by, goals)
            if key(other) == key(g):
                sys.exit("a goal cannot block itself")
            if key(other) not in [b.lower() for b in T.blockers(g)]:
                deps.append(blocked_entry(other))
        if args.unblock:
            gone = T.name_of(args.unblock).lower()
            deps = [d for d in deps if T.name_of(d).lower() != gone]
        changes["blockedBy"] = deps or None
    if not changes:
        sys.exit("nothing to change: give key=value pairs, --blocked-by or --unblock")
    save(g["_path"], changes, args.m)
    print(T.rel(g["_path"]))


# --- command line -------------------------------------------------------------

def no_sync(parser) -> None:
    parser.add_argument("--no-sync", dest="no_sync", action="store_true",
                        help="don't commit and push this change now (the next sync will)")


def register(sub) -> None:
    """Add `goal`, `goals` and `review` to tasks.py's command line."""
    p = sub.add_parser("goal", help="create, change, carry or show a goal")
    actions = p.add_subparsers(dest="action", required=True)

    a = actions.add_parser("new", help="a goal for a week, a month or a year")
    a.add_argument("title")
    a.add_argument("--period", required=True, help="YYYY, YYYY-MM or YYYY-Www")
    a.add_argument("--owner", required=True, help="a People/ note, or Household for shared goals")
    a.add_argument("--parent", metavar="GOAL", help="the longer goal this one serves")
    a.add_argument("--blocked-by", dest="blocked_by", metavar="GOAL",
                   help="GOAL must be achieved first")
    a.add_argument("--target", help="a number to reach (12 books, 500 km)")
    a.add_argument("--unit", help="what the number counts")
    a.add_argument("--project", help="comma-separated Projects/ notes")
    a.add_argument("-m", help="why it matters and what done means")
    a.set_defaults(func=cmd_goal_new)
    no_sync(a)

    a = actions.add_parser("set", help="change fields: key=value (empty value removes)")
    a.add_argument("goal")
    a.add_argument("pairs", nargs="*")
    a.add_argument("--blocked-by", dest="blocked_by", metavar="GOAL")
    a.add_argument("--unblock", metavar="GOAL")
    a.add_argument("-m", help="why (logged)")
    a.set_defaults(func=cmd_goal_set)
    no_sync(a)
