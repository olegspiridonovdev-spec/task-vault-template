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


# --- progress -----------------------------------------------------------------

ICONS = {"achieved": "✅", "partial": "🟡", "missed": "❌", "dropped": "➖"}


def children(g: dict, goals: dict) -> list[dict]:
    return [c for c in goals.values() if parent_key(c) == key(g)]


def tree(g: dict, goals: dict) -> list[dict]:
    """The goal and every goal under it, each once (a loop in `parent` can't hang it)."""
    out, todo, seen = [], [g], set()
    while todo:
        x = todo.pop(0)
        if key(x) in seen:
            continue
        seen.add(key(x))
        out.append(x)
        todo += children(x, goals)
    return out


def goal_links(t: dict) -> set[str]:
    return {T.name_of(p).lower() for p in T.as_list(t.get("projects"))}


def linked_tasks(keys: set[str], tasks: dict) -> list[dict]:
    return [t for t in tasks.values() if goal_links(t) & keys]


def span(g: dict) -> tuple[dt.date, dt.date] | None:
    parsed = parse_period(g.get("period"))
    return (parsed[1], parsed[2]) if parsed else None


def occurrences(t: dict, first: dt.date, last: dt.date) -> int:
    """How many times a recurring task falls between first and last."""
    rule = T.parse_rule(str(t.get("recurrence") or ""))
    if rule is None:
        return 0
    anchor = rule.get("DTSTART") or T.day(t.get("scheduled")) or first
    until = re.sub(r"\D", "", rule.get("UNTIL", ""))[:8]
    end = min(last, dt.date(int(until[:4]), int(until[4:6]), int(until[6:8]))) if len(until) == 8 else last
    d = max(first, rule["DTSTART"]) if rule.get("DTSTART") else first
    count = 0
    while d <= end:
        count += T.on_rule(d, rule, anchor)
        d += dt.timedelta(days=1)
    return count


def when(t: dict) -> str:
    for k in ("due", "scheduled"):
        d = T.day(t.get(k))
        if d:
            late = ", missed" if d < dt.date.today() and t.get("status") not in T.CLOSED else ""
            return f" ({k} {str(t[k])[:10]}{late})"
    return ""


def progress(g: dict, goals: dict, tasks: dict) -> dict:
    """Tasks done of all (this goal's and every goal's under it), the number
    target and the child goals' verdicts. Never sets the goal's status."""
    members = {key(x): x for x in tree(g, goals)}
    outer = span(g)
    done = total = 0
    still: list[tuple[dict, str]] = []
    for t in linked_tasks(set(members), tasks):
        status = t.get("status")
        if status == "cancelled":
            continue
        if t.get("recurrence"):
            # Occurrences inside the period of the goal it counts toward (the
            # shortest one if several), within the period of this goal.
            spans = sorted((s for s in (span(members[k]) for k in goal_links(t) if k in members) if s),
                           key=lambda s: s[1] - s[0])
            if not spans or not outer:
                continue
            first, last = max(spans[0][0], outer[0]), min(spans[0][1], outer[1])
            finished = sum(1 for d in T.as_list(t.get("complete_instances"))
                           if T.day(d) and first <= T.day(d) <= last)
            expected = max(occurrences(t, first, last), finished)
            done, total = done + finished, total + expected
            if finished < expected and status not in T.CLOSED:
                still.append((t, f" ({finished}/{expected} this period)"))
        else:
            total += 1
            if status == "done":
                done += 1
            else:
                still.append((t, when(t)))
    kids = children(g, goals)
    kinds = [parse_period(c.get("period")) for c in kids]
    target, value = as_number(g.get("target")), as_number(g.get("progress") or 0)
    return {"done": done, "total": total, "open": sorted(still, key=lambda x: T.title_of(x[0])),
            "children": len(kids), "achieved": sum(1 for c in kids if c.get("status") == "achieved"),
            "child_kind": next((k[0] for k in kinds if k), ""),
            "number": (value or 0.0, target) if target is not None else None}


def summary(g: dict, p: dict) -> str:
    parts = []
    if p["number"]:
        value, target = p["number"]
        pct = int(100 * value / target) if target else 0
        unit = f" {g['unit']}" if g.get("unit") else ""
        parts.append(f"{fmt(value)}/{fmt(target)}{unit} ({pct}%)")
    if p["total"]:
        parts.append(f"tasks {p['done']}/{p['total']}")
    if p["children"]:
        plural = "s" if p["children"] != 1 else ""
        parts.append(f"{p['achieved']} of {p['children']} {p['child_kind']} goal{plural} achieved")
    return " · ".join(parts) or "no tasks linked"


def open_goal_blockers(g: dict, goals: dict) -> list[str]:
    return [b for b in T.blockers(g) if goals.get(b.lower(), {}).get("status") != "achieved"]


def icon(g: dict, p: dict, goals: dict) -> str:
    status = g.get("status") or "active"
    if status in ICONS:
        return ICONS[status]
    if open_goal_blockers(g, goals):
        return "⛔"
    moved = p["done"] or p["achieved"] or (p["number"] and p["number"][0] > 0)
    return "🟡" if moved else "⬜"


def owners(rows: list[dict]) -> list[str]:
    """Owner names, people alphabetically and Household last."""
    return sorted({T.text(g, "owner") or "?" for g in rows},
                  key=lambda n: (n == HOUSEHOLD, n.lower()))


def level(g: dict) -> int:
    parsed = parse_period(g.get("period"))
    return LEVELS[parsed[0]] if parsed else 9


def cmd_goal_progress(args) -> None:
    g = find_goal(args.goal)
    if as_number(g.get("target")) is None:
        sys.exit(f"{title(g)} has no number target; add one with "
                 f"`goal set \"{title(g)}\" target=N unit=...`")
    match = re.match(r"^([+=-]?)\s*(\d+(?:\.\d+)?)$", args.change.strip())
    if not match:
        sys.exit(f"progress change must be +N, -N or =N, got {args.change!r}")
    current, n = as_number(g.get("progress") or 0) or 0.0, float(match.group(2))
    value = {"+": current + n, "-": current - n}.get(match.group(1), n)
    unit = f" {g['unit']}" if g.get("unit") else ""
    message = f"progress {fmt(value)}/{fmt(as_number(g['target']))}{unit}" + (f": {args.m}" if args.m else "")
    save(g["_path"], {"progress": fmt(value)}, message)
    goals = index_goals()
    print(f"{title(g)}: {summary(goals[key(g)], progress(goals[key(g)], goals, T.index_tasks()))}")


def cmd_goals(args) -> None:
    goals, tasks = index_goals(), T.index_tasks()
    today = dt.date.today()
    if args.period:
        periods = {check_period(args.period)}
    elif args.kind:
        periods = {period_of(args.kind, today)}
    elif args.all:
        periods = None
    else:
        periods = set(current_periods(today))
    rows = [g for g in goals.values()
            if (periods is None or str(g.get("period")) in periods)
            and (args.all or (g.get("status") or "active") == "active")
            and (not args.owner or T.squash(T.text(g, "owner")) == T.squash(args.owner))]
    for owner in owners(rows):
        print(f"{owner}:")
        mine = [g for g in rows if (T.text(g, "owner") or "?") == owner]
        for g in sorted(mine, key=lambda g: (level(g), str(g.get("period")), title(g).lower())):
            p = progress(g, goals, tasks)
            print(f"  {icon(g, p, goals)} {g.get('period')} | {title(g)} | {summary(g, p)} | "
                  f"{T.rel(g['_path'])}")
    print(f"({len(rows)} goal{'s' if len(rows) != 1 else ''})", file=sys.stderr)


def cmd_goal_show(args) -> None:
    goals, tasks = index_goals(), T.index_tasks()
    g = find_goal(args.goal, goals)
    me, s = key(g), span(g)
    print(f"{title(g)}  ({T.rel(g['_path'])})")
    dates = f" ({s[0].isoformat()} – {s[1].isoformat()})" if s else ""
    print(f"period: {g.get('period')}{dates} | owner: {T.text(g, 'owner')} | "
          f"status: {g.get('status') or 'active'}")
    if g.get("projects"):
        print(f"projects: {T.text(g, 'projects')}")

    def state(name: str) -> str:
        other = goals.get(name.lower())
        return (f"{title(other)} ({other.get('period')}, {other.get('status') or 'active'})"
                if other else f"{name} (missing)")
    if parent_key(g):
        print(f"parent: {state(T.name_of(g['parent']))}")
    if T.blockers(g):
        print("blocked by: " + ", ".join(state(b) for b in T.blockers(g)))
    blocks = [title(o) for o in goals.values() if me in [b.lower() for b in T.blockers(o)]]
    if blocks:
        print("blocks: " + ", ".join(blocks))
    p = progress(g, goals, tasks)
    print(f"progress: {summary(g, p)}")
    kids = sorted(children(g, goals), key=lambda c: (str(c.get("period")), title(c).lower()))
    if kids:
        print("goals under it:")
        for c in kids:
            print(f"  - {title(c)} ({c.get('period')}, {c.get('status') or 'active'}) · "
                  f"{summary(c, progress(c, goals, tasks))}")
    direct = sorted(linked_tasks({me}, tasks), key=T.title_of)
    if direct:
        print("tasks:")
        for t in direct:
            mark = "x" if t.get("status") in T.CLOSED and not t.get("recurrence") else " "
            print(f"  - [{mark}] {T.title_of(t)} ({t.get('status')}){when(t)}")
    if p["open"]:
        print("open (here and in the goals under it):")
        for t, detail in p["open"]:
            print(f"  - {T.title_of(t)}{detail}")
    body = T.split(g["_path"].read_text(encoding="utf-8"))[1].strip()
    if body:
        print()
        print(body)


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

    a = actions.add_parser("progress", help="move a number goal: +N, -N or =N")
    a.add_argument("goal")
    a.add_argument("change")
    a.add_argument("-m", help="what moved it (logged)")
    a.set_defaults(func=cmd_goal_progress)
    no_sync(a)

    a = actions.add_parser("show", help="one goal: tree, tasks, progress, blockers, log")
    a.add_argument("goal")
    a.set_defaults(func=cmd_goal_show)

    p = sub.add_parser("goals", help="active goals of this week, month and year, with progress")
    which = p.add_mutually_exclusive_group()
    which.add_argument("--week", dest="kind", action="store_const", const="week")
    which.add_argument("--month", dest="kind", action="store_const", const="month")
    which.add_argument("--year", dest="kind", action="store_const", const="year")
    which.add_argument("--period", help="YYYY, YYYY-MM or YYYY-Www")
    p.add_argument("--owner")
    p.add_argument("--all", action="store_true", help="closed goals too; every period unless one is given")
    p.set_defaults(func=cmd_goals)
