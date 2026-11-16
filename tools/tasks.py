#!/usr/bin/env python3
"""Helper for this task vault: tasks, plus the journal, notes and lists next to them.

The Markdown files stay the only source of truth, and Obsidian (TaskNotes)
reads the same files. This script exists so that an agent can answer "what is
open for Anna this week" in one command and one short answer, instead of
reading every task file, and so that new and closed tasks always get the same
frontmatter the board views expect. Standard library only.

    python3 tools/tasks.py list [--status S] [--assignee A] [--project P] [--when today|week|overdue] [--all]
    python3 tools/tasks.py new "Title" [--assignee A] [--project P] [--status S] [--priority P]
                              [--scheduled DATE] [--due DATE] [--recurrence RRULE] [--note TEXT]
    python3 tools/tasks.py set  "Tasks/Title.md" key=value [key=value ...] [-m "log line"]
    python3 tools/tasks.py done "Tasks/Title.md" [-m "log line"]
    python3 tools/tasks.py log  "Tasks/Title.md" -m "what happened"
    python3 tools/tasks.py journal [-m "entry"] [--date DATE] [--by PERSON]
    python3 tools/tasks.py memo "Title" [-m "text"]       create, add to or print a note
    python3 tools/tasks.py add Films "Dune" [-m "why"]    / check Films "Dune" -m "8/10" / lists
    python3 tools/tasks.py find word [word ...]
    python3 tools/tasks.py goal new "Title" --period 2026-11 --owner A   / goals / review --month
    python3 tools/tasks.py lint
    python3 tools/tasks.py archive [--days 30] [--dry-run]
    python3 tools/tasks.py sync [-m "what changed"] [--no-wait]   commit; pull and push

Every command that changes files commits, pulls and pushes right away (pass
`--no-sync` to skip once, for a batch). Use `python` instead of `python3` on
Windows. Works from any directory.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "Tasks"
ARCHIVE = ROOT / "Archive"
PEOPLE = ROOT / "People"
PROJECTS = ROOT / "Projects"
JOURNAL = ROOT / "Journal"
NOTES = ROOT / "Notes"
LISTS = ROOT / "Lists"
GOALS = ROOT / "Goals"
REVIEWS = ROOT / "Reviews"

STATUSES = ["inbox", "todo", "in-progress", "waiting", "done", "cancelled"]
CLOSED = {"done", "cancelled"}
PRIORITIES = ["none", "low", "normal", "high"]
LIST_KEYS = {"projects", "contexts", "tags", "blockedBy", "complete_instances",
             "skipped_instances"}
LINK_KEYS = {"assignee", "projects", "parent", "blockedBy"}
DATE_KEYS = ("scheduled", "due", "completedDate")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?Z?)?$")
WIP_LIMIT = 3

if __name__ == "__main__":
    # tools/goals.py does `import tasks`; let it get this running module, not a second copy.
    sys.modules.setdefault("tasks", sys.modules[__name__])


# --- frontmatter ------------------------------------------------------------

def split(text: str) -> tuple[list[str] | None, str]:
    """Frontmatter lines and body; (None, text) when there is no frontmatter."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 3)
    if end < 0:
        if text.rstrip().endswith("\n---"):
            return text[4:text.rstrip().rfind("\n---")].splitlines(), ""
        return None, text
    return text[4:end].splitlines(), text[end + 5:]


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse(lines: list[str]) -> dict:
    """The YAML subset task files use, including lists of small mappings
    (TaskNotes writes `blockedBy` as `- uid: "[[Task]]"` + `reltype: ...`)."""
    meta: dict = {}
    key, item = None, None
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if match:
            key, value, item = match.group(1), match.group(2).strip(), None
            if value.startswith("[") and value.endswith("]") and not value.startswith("[["):
                meta[key] = [unquote(v) for v in value[1:-1].split(",") if v.strip()]
            else:
                meta[key] = unquote(value)
        elif key and line.lstrip().startswith("- "):
            if not isinstance(meta.get(key), list):
                meta[key] = []
            entry = line.lstrip()[2:]
            pair = re.match(r"^([A-Za-z_][\w-]*):\s+(.*)$", entry)
            if pair:
                item = {pair.group(1): unquote(pair.group(2))}
                meta[key].append(item)
            else:
                item = None
                meta[key].append(unquote(entry))
        elif item is not None:
            pair = re.match(r"^\s+([A-Za-z_][\w-]*):\s*(.*)$", line)
            if pair:
                item[pair.group(1)] = unquote(pair.group(2))
    return meta


def quote(value: str) -> str:
    value = str(value)
    if value and (value[0] in "[{\"'*&!|>%@`#" or ": " in value or value.endswith(":")):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def render(key: str, value) -> list[str]:
    if isinstance(value, list):
        if not value:
            return [f"{key}: []"]
        out = [f"{key}:"]
        for v in value:
            if isinstance(v, dict):
                pairs = list(v.items())
                out.append(f"  - {pairs[0][0]}: {quote(pairs[0][1])}")
                out += [f"    {k}: {quote(x)}" for k, x in pairs[1:]]
            else:
                out.append(f"  - {quote(v)}")
        return out
    return [f"{key}: {quote(value)}".rstrip()]


def set_key(lines: list[str], key: str, value) -> list[str]:
    """Replace `key` (and its block-list items) in place, or append it."""
    out, i, placed = [], 0, False
    while i < len(lines):
        if re.match(rf"^{re.escape(key)}:", lines[i]):
            i += 1
            while i < len(lines) and (lines[i].startswith((" ", "\t", "- "))):
                i += 1
            if not placed and value is not None:
                out += render(key, value)
            placed = True
            continue
        out.append(lines[i])
        i += 1
    if not placed and value is not None:
        out += render(key, value)
    return out


# --- values -----------------------------------------------------------------

def as_list(value) -> list[str]:
    if isinstance(value, list):
        return [v for v in value if v]
    return [value] if value else []


def plain(link: str) -> str:
    """`[[Anna|me]]` -> `Anna`."""
    return re.sub(r"^\[\[|\]\]$", "", str(link)).split("|")[0].strip()


def link(name: str) -> str:
    name = name.strip()
    return name if name.startswith("[[") else f"[[{name}]]"


def text(meta: dict, key: str) -> str:
    return ", ".join(plain(v) for v in as_list(meta.get(key)))


def day(value) -> dt.date | None:
    value = str(value or "")[:10]
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()



# --- recurrence -------------------------------------------------------------
# The RRULE subset people use for chores and bills. Like TaskNotes, finishing an
# occurrence moves `scheduled` to the next one, so the task leaves "today".

WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
RULE_KEYS = {"FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY", "BYMONTH", "UNTIL", "COUNT", "WKST"}


def parse_rule(rule: str) -> dict | None:
    parts: dict = {}
    for piece in re.split(r"[;\n]", rule.replace("RRULE:", "")):
        if piece.startswith("DTSTART"):
            digits = re.sub(r"\D", "", piece)[:8]
            parts["DTSTART"] = dt.date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        elif "=" in piece:
            key, value = piece.split("=", 1)
            parts[key.strip().upper()] = value.strip().upper()
    if parts.get("FREQ") not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return None
    if set(parts) - RULE_KEYS - {"DTSTART"}:
        return None  # BYSETPOS and friends: not worth guessing
    return parts


def last_day(d: dt.date) -> int:
    following = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return (following - dt.timedelta(days=1)).day


def on_rule(d: dt.date, rule: dict, anchor: dt.date) -> bool:
    every = int(rule.get("INTERVAL", "1") or 1)
    days = [m for m in (re.match(r"^([+-]?\d*)(MO|TU|WE|TH|FR|SA|SU)$", x)
                        for x in rule.get("BYDAY", "").split(",") if x) if m]
    monthdays = [int(x) for x in rule.get("BYMONTHDAY", "").split(",") if x]
    months = [int(x) for x in rule.get("BYMONTH", "").split(",") if x]

    def day_matches() -> bool:
        if monthdays:
            return any(d.day == (n if n > 0 else last_day(d) + n + 1) for n in monthdays)
        if days:
            for m in days:
                if d.weekday() != WEEKDAYS.index(m.group(2)):
                    continue
                n = int(m.group(1)) if m.group(1) not in ("", "+", "-") else 0
                if n == 0 or (n > 0 and (d.day - 1) // 7 + 1 == n) \
                        or (n < 0 and (last_day(d) - d.day) // 7 + 1 == -n):
                    return True
            return False
        return d.day == anchor.day

    freq = rule["FREQ"]
    if freq == "DAILY":
        return (d - anchor).days % every == 0 and (not days or day_matches())
    if freq == "WEEKLY":
        weekdays = {WEEKDAYS.index(m.group(2)) for m in days} or {anchor.weekday()}
        weeks = ((d - dt.timedelta(days=d.weekday())) - (anchor - dt.timedelta(days=anchor.weekday()))).days // 7
        return d.weekday() in weekdays and weeks % every == 0
    if freq == "MONTHLY":
        return ((d.year - anchor.year) * 12 + d.month - anchor.month) % every == 0 and day_matches()
    return ((d.year - anchor.year) % every == 0 and d.month in (months or [anchor.month])
            and day_matches())


def next_occurrence(recurrence: str, after: dt.date) -> dt.date | None:
    rule = parse_rule(recurrence)
    if rule is None:
        return None
    anchor = rule.get("DTSTART") or after
    until = day(rule.get("UNTIL", "")[:8] and
                f"{rule['UNTIL'][:4]}-{rule['UNTIL'][4:6]}-{rule['UNTIL'][6:8]}")
    for offset in range(1, 366 * 5):
        candidate = after + dt.timedelta(days=offset)
        if until and candidate > until:
            return None
        if on_rule(candidate, rule, anchor):
            return candidate
    return None


# --- tasks ------------------------------------------------------------------

def load(*folders: Path) -> list[dict]:
    tasks = []
    for folder in folders or (TASKS,):
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*.md")):
            lines, _ = split(path.read_text(encoding="utf-8"))
            if lines is None:
                continue
            meta = parse(lines)
            if "task" not in as_list(meta.get("tags")):
                continue
            meta["_path"] = path
            tasks.append(meta)
    return tasks


def resolve(arg: str) -> Path:
    for candidate in (Path(arg), ROOT / arg, TASKS / arg, TASKS / f"{arg}.md"):
        if candidate.is_file():
            return candidate.resolve()
    matches = [t["_path"] for t in load(TASKS) if arg.lower() in t["_path"].stem.lower()]
    if len(matches) == 1:
        return matches[0]
    hint = "; ".join(rel(m) for m in matches[:5]) or "no match"
    sys.exit(f"cannot pick one task for {arg!r}: {hint}")


def name_of(ref) -> str:
    """The task or note a link points to: `[[Tasks/Fix|x]]`, `{uid: ...}` -> `Fix`."""
    if isinstance(ref, dict):
        ref = ref.get("uid", "")
    return plain(ref).rsplit("/", 1)[-1].removesuffix(".md")


def title_of(t: dict) -> str:
    return t.get("title") or t["_path"].stem


def index_tasks() -> dict[str, dict]:
    """Every task in Tasks/ and Archive/, by lower-case file name."""
    return {t["_path"].stem.lower(): t for t in load(TASKS, ARCHIVE)}


def blockers(t: dict) -> list[str]:
    return [name_of(d) for d in as_list(t.get("blockedBy")) if name_of(d)]


def open_blockers(t: dict, tasks: dict[str, dict]) -> list[str]:
    return [b for b in blockers(t)
            if b.lower() in tasks and tasks[b.lower()].get("status") not in CLOSED]


def parents(t: dict, tasks: dict[str, dict]) -> list[str]:
    """Tasks this one is a subtask of: TaskNotes puts the parent task in `projects`."""
    return [name_of(p) for p in as_list(t.get("projects")) if name_of(p).lower() in tasks]


def find_task(name: str, tasks: dict[str, dict]) -> dict:
    key = name_of(name).lower()
    if key in tasks:
        return tasks[key]
    return tasks[resolve(name).stem.lower()]


def add_entry(body: str, section: str, entry: str) -> str:
    """Append a line to `## section`, creating it (Notes goes above Log)."""
    match = re.search(rf"^## {section}\s*$", body, flags=re.M)
    if match:
        nxt = re.search(r"^## ", body[match.end():], flags=re.M)
        end = match.end() + nxt.start() if nxt else len(body)
        head, tail = body[:end].rstrip("\n"), body[end:]
        return head + "\n" + entry + "\n" + ("\n" + tail if tail else "")
    log = re.search(r"^## Log\s*$", body, flags=re.M)
    if log and section != "Log":
        before = body[:log.start()].rstrip("\n")
        return (before + "\n\n" if before else "\n") + f"## {section}\n{entry}\n\n" + body[log.start():]
    return body.rstrip("\n") + f"\n\n## {section}\n{entry}\n"


def write(path: Path, lines: list[str], body: str) -> None:
    path.write_text("---\n" + "\n".join(lines) + "\n---\n" + body, encoding="utf-8")


def add_log(body: str, message: str) -> str:
    entry = f"- {dt.date.today().isoformat()}: {message}"
    if re.search(r"^## Log\s*$", body, flags=re.M):
        return body.rstrip("\n") + "\n" + entry + "\n"
    return body.rstrip("\n") + "\n\n## Log\n" + entry + "\n"


def edit_body(path: Path, change) -> None:
    lines, body = split(path.read_text(encoding="utf-8"))
    if lines is None:
        sys.exit(f"{rel(path)} has no frontmatter")
    write(path, set_key(lines, "dateModified", now()), change(body))


def coerce(key: str, value: str):
    if key in LIST_KEYS:
        items = [v.strip() for v in value.split(",") if v.strip()]
        return [link(v) for v in items] if key in LINK_KEYS else items
    if key in LINK_KEYS and value:
        return link(value)
    return value


def update(path: Path, changes: dict, message: str | None = None) -> list[str]:
    """Apply changes; returns notes on what was done implicitly."""
    lines, body = split(path.read_text(encoding="utf-8"))
    if lines is None:
        sys.exit(f"{rel(path)} has no frontmatter")
    meta = parse(lines)
    notes = []
    status = changes.get("status")
    if status and status not in STATUSES:
        sys.exit(f"unknown status {status!r}; use one of {', '.join(STATUSES)}")
    if status == "done" and meta.get("recurrence"):
        # A recurring task is never closed: TaskNotes records each finished
        # occurrence in complete_instances and keeps the series open.
        changes.pop("status")
        scheduled = str(meta.get("scheduled") or "")
        # The occurrence is the scheduled one (finishing Saturday's chore on
        # Sunday ticks Saturday), unless a date is given.
        instance = str(changes.pop("instance", "") or scheduled[:10] or dt.date.today().isoformat())
        done = as_list(meta.get("complete_instances"))
        if instance not in done:
            done.append(instance)
        changes["complete_instances"] = done
        notes.append(f"recurring: marked the {instance} occurrence complete; series stays open")
        following = day(instance) and next_occurrence(str(meta["recurrence"]), day(instance))
        if scheduled and following:
            changes["scheduled"] = following.isoformat() + scheduled[10:]
            notes.append(f"next occurrence: {changes['scheduled']}")
        elif scheduled:
            notes.append("could not work out the next date from the rule; scheduled unchanged")
        message = message or f"completed the {instance} occurrence"
    elif status in CLOSED and not meta.get("completedDate") and "completedDate" not in changes:
        changes["completedDate"] = dt.date.today().isoformat()
    elif status and status not in CLOSED and meta.get("completedDate"):
        changes["completedDate"] = None  # reopened
    for key, value in changes.items():
        lines = set_key(lines, key, value)
    lines = set_key(lines, "dateModified", now())
    if status:
        message = f"status -> {status}" + (f": {message}" if message else "")
    if message:
        body = add_log(body, message)
    write(path, lines, body)
    return notes



# --- merging ----------------------------------------------------------------
# Git calls `tasks.py merge-driver` (registered by `sync`, see .gitattributes)
# when two machines changed the same task file between syncs. Instead of
# conflict markers it merges field by field: a change made on one side wins;
# when both changed the same field, the newer edit (dateModified) wins and the
# other value is written to the log. Log lines from both sides are kept.

def blocks(lines: list[str]) -> dict[str, list[str]]:
    """Frontmatter as key -> its lines (the key line plus list items)."""
    out: dict[str, list[str]] = {}
    key = ""
    for line in lines:
        match = re.match(r"^([A-Za-z_][\w-]*):", line)
        if match:
            key = match.group(1)
            out[key] = []
        out.setdefault(key, []).append(line)
    return out


def split_log(body: str) -> tuple[str, list[str]]:
    match = re.search(r"^## Log\s*$", body, flags=re.M)
    if not match:
        return body.strip("\n"), []
    log = [line for line in body[match.end():].splitlines() if line.strip()]
    return body[:match.start()].strip("\n"), log


def pick(base, ours, theirs):
    """Three-way choice for one value; None when both sides changed it differently."""
    if ours == theirs or theirs == base:
        return ours, False
    if ours == base:
        return theirs, False
    return None, True


def moment(value) -> dt.datetime:
    """A timestamp in either format (tasks.py writes UTC `Z`, TaskNotes local
    time with an offset), comparable; unreadable or missing counts as oldest."""
    try:
        stamp = dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)


def union_merge(base: str, ours: str, theirs: str) -> str:
    """Line-level three-way merge that keeps both sides' lines on a clash."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for name, content in (("ours", ours), ("base", base), ("theirs", theirs)):
            path = Path(tmp) / name
            path.write_text(content + "\n", encoding="utf-8")
            paths.append(str(path))
        result = subprocess.run(["git", "merge-file", "-p", "--union", *paths],
                                capture_output=True, text=True)
    return result.stdout.strip("\n") if result.stdout else ours


def merge_task(base: str, ours: str, theirs: str) -> str | None:
    (lo, bo), (la, ba), (lb, bb) = split(base), split(ours), split(theirs)
    if la is None or lb is None:
        return None
    ko, ka, kb = blocks(lo or []), blocks(la), blocks(lb)
    ma, mb = parse(la), parse(lb)
    a_newer = moment(ma.get("dateModified")) >= moment(mb.get("dateModified"))
    lines, notes = [], []
    for key in list(ka) + [k for k in kb if k not in ka]:
        value, clash = pick(ko.get(key), ka.get(key), kb.get(key))
        if clash:
            if key == "dateModified":
                value = ka[key] if a_newer else kb[key]
            else:
                value, lost = (ka.get(key), kb.get(key)) if a_newer else (kb.get(key), ka.get(key))
                shown = parse(lost).get(key) if lost else "(removed)"
                shown = ", ".join(shown) if isinstance(shown, list) else shown
                notes.append(f"sync conflict: {key} was {shown} on another machine; "
                             f"kept the newer edit")
        if value:
            lines += value
    (no, logo), (na, loga), (nb, logb) = split_log(bo), split_log(ba), split_log(bb)
    text, clash = pick(no, na, nb)
    if clash:  # both edited the text above the log: keep every line from both
        text = union_merge(no, na, nb)
    log = list(logo)
    for line in loga + logb:
        if line not in log:
            log.append(line)
    log.sort(key=lambda line: line[:12])  # "- YYYY-MM-DD", stable within a day
    log += [f"- {dt.date.today().isoformat()}: {note}" for note in notes]
    body = (text + "\n" if text else "")
    if log:
        body += ("\n" if text else "") + "## Log\n" + "\n".join(log) + "\n"
    return "---\n" + "\n".join(lines) + "\n---\n" + ("\n" + body if body else "")


def cmd_merge_driver(args) -> None:
    read = lambda p: Path(p).read_text(encoding="utf-8") if Path(p).exists() else ""
    merged = merge_task(read(args.base), read(args.ours), read(args.theirs))
    if merged is None:  # not a task file we understand: let git mark the conflict
        sys.exit(subprocess.run(["git", "merge-file", "-L", "this machine", "-L", "base",
                                 "-L", "other machine", args.ours, args.base,
                                 args.theirs]).returncode or 1)
    Path(args.ours).write_text(merged, encoding="utf-8")


def register_merge_driver() -> None:
    tool = f'"{Path(sys.executable).as_posix()}" "{(ROOT / "tools" / "tasks.py").as_posix()}"'
    git("config", "merge.task-vault.name", "task vault: merge task files field by field")
    git("config", "merge.task-vault.driver", f"{tool} merge-driver %O %A %B")


# --- commands ---------------------------------------------------------------

def cmd_list(args) -> None:
    folders = (TASKS, ARCHIVE) if args.archive else (TASKS,)
    today = dt.date.today()
    horizon = {"today": today, "week": today + dt.timedelta(days=7),
               "overdue": today - dt.timedelta(days=1)}.get(args.when)
    statuses = set(args.status.split(",")) if args.status else None
    tasks = index_tasks()
    rows = []
    for t in load(*folders):
        status = t.get("status", "")
        if statuses and status not in statuses:
            continue
        if not statuses and not args.all and status in CLOSED:
            continue
        if args.assignee and args.assignee.lower() not in text(t, "assignee").lower():
            continue
        if args.project and args.project.lower() not in text(t, "projects").lower():
            continue
        t["_blocked"] = open_blockers(t, tasks) if status not in CLOSED else []
        if args.ready and (t["_blocked"] or status == "waiting"):
            continue
        if horizon:
            due, sched = day(t.get("due")), day(t.get("scheduled"))
            if args.when == "overdue":
                hit = due is not None and due <= horizon
            else:
                hit = (status == "in-progress" or (due and due <= horizon)
                       or (sched and sched <= horizon))
            if not hit:
                continue
        rows.append(t)
    order = {s: i for i, s in enumerate(STATUSES)}
    prio = {p: i for i, p in enumerate(reversed(PRIORITIES))}
    rows.sort(key=lambda t: (order.get(t.get("status"), 99),
                             str(t.get("due") or t.get("scheduled") or "9999"),
                             prio.get(t.get("priority"), 9)))
    for t in rows:
        when = t.get("due") and f"due {t['due']}" or t.get("scheduled") and f"on {t['scheduled']}" or "-"
        flags = (" ↻" if t.get("recurrence") else "") + (f" (waiting on {t['waiting_on']})"
                                                        if t.get("waiting_on") else "")
        if t["_blocked"]:
            flags += f" (blocked by {', '.join(t['_blocked'])})"
        print(" | ".join([t.get("status", "?"), when, t.get("priority", "") or "-",
                          text(t, "assignee") or "-", text(t, "projects") or "-",
                          (t.get("title") or t["_path"].stem) + flags, rel(t["_path"])]))
    print(f"({len(rows)} task{'s' if len(rows) != 1 else ''})", file=sys.stderr)


def cmd_new(args) -> None:
    title = args.title.strip()
    name = file_name(title, "Task")
    path, n = TASKS / f"{name}.md", 2
    while path.exists():
        path, n = TASKS / f"{name} {n}.md", n + 1
    if args.status not in STATUSES:
        sys.exit(f"unknown status {args.status!r}; use one of {', '.join(STATUSES)}")
    if args.priority not in PRIORITIES:
        sys.exit(f"unknown priority {args.priority!r}; use one of {', '.join(PRIORITIES)}")
    lines = render("title", title) + render("status", args.status) + render("priority", args.priority)
    if args.assignee:
        lines += render("assignee", link(args.assignee))
    goal_refs = []
    if args.goal:
        import goals as G
        index = G.index_goals()
        goal_refs = [link(G.find_goal(n, index)["_path"].stem) for n in args.goal.split(",") if n.strip()]
    if args.project or goal_refs:
        lines += render("projects", [link(p) for p in (args.project or "").split(",") if p.strip()]
                        + goal_refs)
    if args.estimate:
        lines += render("timeEstimate", str(int(args.estimate)))
    for key in ("scheduled", "due", "recurrence", "waiting_on"):
        value = getattr(args, key)
        if value:
            if key in ("scheduled", "due") and not DATE_RE.match(value):
                sys.exit(f"{key} must be YYYY-MM-DD or YYYY-MM-DDTHH:MM, got {value!r}")
            lines += render(key, value)
    stamp = now()
    lines += render("dateCreated", stamp) + render("dateModified", stamp) + render("tags", ["task"])
    body = "\n" + (args.note.strip() + "\n" if args.note else "")
    body = add_log(body, "created")
    TASKS.mkdir(exist_ok=True)
    write(path, lines, body)
    print(rel(path))


def cmd_set(args) -> None:
    path = resolve(args.task)
    changes = {}
    for pair in args.pairs:
        if "=" not in pair:
            sys.exit(f"expected key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        changes[key.strip()] = coerce(key.strip(), value.strip()) if value.strip() else None
    for note in update(path, changes, args.m):
        print(note)
    print(rel(path))


def cmd_done(args) -> None:
    path = resolve(args.task)
    changes = {"status": "done"}
    if args.date:
        changes["instance"] = args.date
    message = args.m
    if args.spent:
        meta = parse(split(path.read_text(encoding="utf-8"))[0] or [])
        took = f"took {args.spent} min" + (f" (estimate {meta['timeEstimate']})"
                                           if meta.get("timeEstimate") else "")
        message = f"{message}; {took}" if message else took
    for note in update(path, changes, message):
        print(note)
    print(rel(path))
    tasks = index_tasks()
    me = path.stem.lower()
    for t in tasks.values():
        if t.get("status") not in CLOSED and me in [b.lower() for b in blockers(t)] \
                and not open_blockers(t, tasks):
            print(f"unblocked: {title_of(t)}")
    subtasks = [title_of(t) for t in tasks.values() if t.get("status") not in CLOSED
                and me in [p.lower() for p in parents(t, tasks)]]
    if subtasks:
        print(f"{len(subtasks)} subtask{'s' if len(subtasks) != 1 else ''} still open: "
              + ", ".join(subtasks))


def cmd_note(args) -> None:
    """A detail, comment or finding, in `## Notes` (the log is for what happened)."""
    path = resolve(args.task)
    edit_body(path, lambda body: add_entry(body, "Notes", f"- {dt.date.today().isoformat()}: {args.m}"))
    print(rel(path))


def cmd_link(args) -> None:
    path = resolve(args.task)
    tasks = index_tasks()
    lines, body = split(path.read_text(encoding="utf-8"))
    meta = parse(lines)
    logged = []
    if args.blocked_by or args.unblock:
        deps = as_list(meta.get("blockedBy"))
        if args.blocked_by:
            other = find_task(args.blocked_by, tasks)
            if other["_path"] == path:
                sys.exit("a task cannot block itself")
            if name_of(other["_path"].stem).lower() not in [d.lower() for d in blockers(meta)]:
                deps.append({"uid": link(other["_path"].stem), "reltype": "FINISHTOSTART"})
            logged.append(f"blocked by [[{other['_path'].stem}]]")
        if args.unblock:
            gone = name_of(args.unblock).lower()
            deps = [d for d in deps if name_of(d).lower() != gone]
            logged.append(f"no longer blocked by [[{name_of(args.unblock)}]]")
        lines = set_key(lines, "blockedBy", deps or None)
    if args.parent:
        import goals as G
        goal = G.lookup_goal(args.parent)  # a goal by that exact name, else a parent task
        stem = goal["_path"].stem if goal else find_task(args.parent, tasks)["_path"].stem
        projects = as_list(meta.get("projects"))
        if stem.lower() not in [name_of(p).lower() for p in projects]:
            projects.append(link(stem))
        lines = set_key(lines, "projects", projects)
        logged.append(f"counts toward [[{stem}]]" if goal else f"subtask of [[{stem}]]")
    if args.related:
        other = find_task(args.related, tasks)
        why = f" ({args.m})" if args.m else ""
        body = add_entry(body, "Notes",
                         f"- {dt.date.today().isoformat()}: related: [[{other['_path'].stem}]]{why}")
    for message in logged:
        body = add_log(body, message + (f": {args.m}" if args.m and not args.related else ""))
    write(path, set_key(lines, "dateModified", now()), body)
    print(rel(path))


def cmd_show(args) -> None:
    """One task with everything around it: fields, relations both ways, notes, log."""
    path = resolve(args.task)
    tasks = index_tasks()
    t = tasks.get(path.stem.lower())
    if t is None:
        sys.exit(f"{rel(path)} is not a task")
    me = path.stem.lower()
    print(f"{title_of(t)}  ({rel(path)})")
    print(" | ".join(f"{k}: {v}" for k, v in (
        ("status", t.get("status")), ("priority", t.get("priority")),
        ("assignee", text(t, "assignee")),
        ("projects", ", ".join(name_of(p) for p in as_list(t.get("projects"))
                               if name_of(p).lower() not in tasks))) if v))
    for key in ("scheduled", "due", "recurrence", "waiting_on", "timeEstimate", "completedDate",
                "contexts"):
        if t.get(key):
            value = ", ".join(t[key]) if isinstance(t[key], list) else t[key]
            print(f"{key}: {value}")

    def state(name: str) -> str:
        other = tasks.get(name.lower())
        return f"{name} ({other.get('status')})" if other else f"{name} (missing)"
    for label, names in (
            ("parent", parents(t, tasks)),
            ("blocked by", blockers(t)),
            ("blocks", [title_of(o) for o in tasks.values() if me in [b.lower() for b in blockers(o)]]),
            ("subtasks", [title_of(o) for o in tasks.values() if me in [p.lower() for p in parents(o, tasks)]])):
        if names:
            shown = names if label in ("parent", "blocks") else [state(n) for n in names]
            print(f"{label}: {', '.join(shown)}")
    mentions = []
    pages = [o["_path"] for o in tasks.values()] + [
        p for folder in (JOURNAL, NOTES, LISTS) if folder.is_dir() for p in sorted(folder.rglob("*.md"))]
    for page in pages:
        if page == path:
            continue
        other_body = split(page.read_text(encoding="utf-8"))[1]
        if re.search(rf"\[\[(?:[^\]|]*/)?{re.escape(path.stem)}(?:\|[^\]]*)?\]\]", other_body):
            mentions.append(page.stem if page.parent != TASKS and page.parent.parent != ARCHIVE
                            else title_of(tasks[page.stem.lower()]))
    if mentions:
        print(f"mentioned in: {', '.join(mentions)}")
    body = split(path.read_text(encoding="utf-8"))[1].strip()
    if body:
        print()
        print(body)


def cmd_log(args) -> None:
    path = resolve(args.task)
    update(path, {}, args.m)
    print(rel(path))


def cmd_lint(args) -> None:
    people = {p.stem for p in PEOPLE.glob("*.md")}
    projects = {p.stem for p in PROJECTS.glob("*.md")}
    problems, warnings = [], []
    wip: dict[str, int] = {}
    tasks = index_tasks()
    import goals as G
    goal_names = set(G.index_goals())
    for t in load(TASKS, ARCHIVE):
        where = rel(t["_path"])
        status = t.get("status", "")
        if status not in STATUSES:
            problems.append(f"{where}: status {status!r} is not one of {', '.join(STATUSES)}")
        if t.get("priority") and t["priority"] not in PRIORITIES:
            problems.append(f"{where}: priority {t['priority']!r} is not one of {', '.join(PRIORITIES)}")
        for key in DATE_KEYS:
            if t.get(key) and not DATE_RE.match(str(t[key])):
                problems.append(f"{where}: {key} {t[key]!r} is not YYYY-MM-DD")
        who = text(t, "assignee")
        if who and who not in people:
            problems.append(f"{where}: assignee {who!r} has no note in People/")
        if who == G.HOUSEHOLD:
            problems.append(f"{where}: Household is for shared goals; assign the task to a person")
        for project in as_list(t.get("projects")):  # a project note, a parent task or a goal
            n = name_of(project)
            if n not in projects and n.lower() not in tasks and n.lower() not in goal_names:
                problems.append(f"{where}: project {n!r} has no note in "
                                "Projects/ and is not a task or a goal")
        for blocker in blockers(t):
            if blocker.lower() not in tasks:
                problems.append(f"{where}: blockedBy {blocker!r} is not a task")
        if status == "in-progress" and open_blockers(t, tasks):
            warnings.append(f"{where}: in progress but blocked by "
                            + ", ".join(open_blockers(t, tasks)))
        if status in CLOSED and not t.get("recurrence") and not t.get("completedDate"):
            problems.append(f"{where}: {status} but no completedDate")
        if status not in CLOSED and status != "inbox" and not who:
            warnings.append(f"{where}: {status} with nobody assigned")
        if status == "waiting" and not t.get("waiting_on"):
            warnings.append(f"{where}: waiting, but waiting_on does not say on what")
        if status == "in-progress" and who:
            wip[who] = wip.get(who, 0) + 1
    for loop in dependency_loops(tasks):
        problems.append("dependency loop: " + " -> ".join(loop))
    G.lint_goals(problems, warnings, people)
    notes_lint(problems, warnings)
    for who, count in wip.items():
        if count > WIP_LIMIT:
            warnings.append(f"{who} has {count} tasks in progress (limit {WIP_LIMIT})")
    for line in problems:
        print("error:", line)
    for line in warnings:
        print("warning:", line)
    if not problems and not warnings:
        print("ok")
    sys.exit(1 if problems else 0)


def dependency_loops(tasks: dict[str, dict]) -> list[list[str]]:
    """Cycles in blockedBy (A waits for B waits for A): nothing in them can start."""
    loops, done, seen = [], set(), set()

    def visit(key: str, trail: list[str]) -> None:
        if key in trail:
            cycle = trail[trail.index(key):] + [key]
            if frozenset(cycle) not in seen:
                seen.add(frozenset(cycle))
                loops.append([title_of(tasks[k]) for k in cycle])
            return
        if key in done or key not in tasks:
            return
        for blocker in blockers(tasks[key]):
            visit(blocker.lower(), trail + [key])
        done.add(key)

    for key in tasks:
        visit(key, [])
    return loops


def cmd_archive(args) -> None:
    cutoff = dt.date.today() - dt.timedelta(days=args.days)
    moved = 0
    for t in load(TASKS):
        if t.get("status") not in CLOSED or t.get("recurrence"):
            continue
        closed = day(t.get("completedDate"))
        if closed is None or closed > cutoff:
            continue
        source = t["_path"]
        target = ARCHIVE / str(closed.year) / source.name
        if target.exists():
            target = target.with_name(f"{source.stem} ({closed.isoformat()}).md")
        print(f"{rel(source)} -> {rel(target)}")
        moved += 1
        if not args.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
    print(f"({moved} {'would be ' if args.dry_run else ''}archived)", file=sys.stderr)


# --- notes, journal and lists -------------------------------------------------
# Next to tasks: Journal/<year>/<date>.md (one page per day, like a notebook),
# Notes/<title>.md (things to keep that don't belong to a day) and
# Lists/<name>.md (checklists you keep adding to: films, books, ...).
# These files merge line by line (`merge=union` in .gitattributes), so nothing
# in their frontmatter changes after it is written: no dateModified here.

DAY_VIEW = "![[Views/Day.base]]"
ITEM_RE = re.compile(r"^- \[([ xX])\] (.+?)\s*$")


def journal_path(d: dt.date) -> Path:
    return JOURNAL / str(d.year) / f"{d.isoformat()}.md"


def file_name(title: str, fallback: str) -> str:
    return re.sub(r'[\\/:*?"<>|#^\[\]]', "", title).strip()[:90] or fallback


def squash(value: str) -> str:
    """Loose key for matching names: "Wi-Fi setup" ~ "wifi setup" ~ "WIFI-SETUP"."""
    return re.sub(r"[\W_]+", "", value.lower())


def which_day(value: str | None) -> dt.date:
    today = dt.date.today()
    if not value or value == "today":
        return today
    if value == "yesterday":
        return today - dt.timedelta(days=1)
    parsed = day(value)
    if parsed is None or len(value) != 10:
        sys.exit(f"--date must be YYYY-MM-DD, today or yesterday, got {value!r}")
    return parsed


def person(name: str | None) -> str:
    if not name:
        return ""
    for note in PEOPLE.glob("*.md"):
        if squash(note.stem) == squash(name):
            return note.stem
    sys.exit(f"{name!r} has no note in People/")


def one_line(value: str) -> str:
    """A multi-line message as one list entry (continuation lines indented)."""
    return "\n  ".join(line.strip() for line in value.strip().splitlines() if line.strip())


def append_entry(path: Path, entry: str) -> None:
    content = path.read_text(encoding="utf-8").rstrip("\n")
    last = content.splitlines()[-1] if content else ""
    gap = "\n" if last.lstrip().startswith(("- ", "  ")) else "\n\n"
    path.write_text(content + gap + entry + "\n", encoding="utf-8")


def new_page(path: Path, lines: list[str], body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write(path, lines, body)


def cmd_journal(args) -> None:
    d = which_day(args.date)
    path = journal_path(d)
    if not args.m:
        print_day(d)
        return
    if not path.exists():
        new_page(path, render("date", d.isoformat()) + render("tags", ["journal"]),
                 DAY_VIEW + "\n")
    stamp = dt.datetime.now().strftime("%H:%M") + " — " if d == dt.date.today() and not args.no_time else ""
    who = person(args.by)
    append_entry(path, f"- {stamp}{who + ': ' if who else ''}{one_line(args.m)}")
    print(rel(path))


def print_day(d: dt.date) -> None:
    """A day at a glance: its journal page, tasks, notes and list items."""
    key = d.isoformat()
    print(f"{key} ({d.strftime('%A')})")
    path = journal_path(d)
    if path.exists():
        body = split(path.read_text(encoding="utf-8"))[1].replace(DAY_VIEW, "").strip()
        print(body or "(journal page is empty)")
    else:
        print("(no journal page)")
    tasks = []
    for t in load(TASKS, ARCHIVE):
        what = [label for label, field in (("planned", "scheduled"), ("due", "due"),
                                           ("finished", "completedDate"))
                if str(t.get(field) or "").startswith(key)]
        if key in as_list(t.get("complete_instances")):
            what.append("occurrence done")
        if what:
            tasks.append(f"- {title_of(t)} ({t.get('status')}; {', '.join(what)})")
    notes = [f"- {n['_path'].stem}" for n in load_notes(NOTES, "note")
             if str(n.get("created") or "").startswith(key)]
    items = []
    for path in sorted(LISTS.glob("*.md")) if LISTS.is_dir() else []:
        for line in path.read_text(encoding="utf-8").splitlines():
            if ITEM_RE.match(line) and (f"added {key}" in line or f"done {key}" in line):
                items.append(f"- {path.stem}: {line[2:]}")
    for label, rows in (("tasks", tasks), ("notes", notes), ("lists", items)):
        if rows:
            print(f"\n{label}:")
            print("\n".join(rows))


def load_notes(folder: Path, tag: str) -> list[dict]:
    out = []
    for path in sorted(folder.rglob("*.md")) if folder.is_dir() else []:
        lines, _ = split(path.read_text(encoding="utf-8"))
        meta = parse(lines or [])
        if lines is None or tag in as_list(meta.get("tags")):
            meta["_path"] = path
            out.append(meta)
    return out


def find_page(folder: Path, name: str, loose: bool) -> Path | None:
    """The page named `name` (ignoring case and punctuation); with `loose`, also
    the only page whose name contains it. Exits when several match."""
    pages = sorted(folder.glob("*.md")) if folder.is_dir() else []
    exact = [p for p in pages if squash(p.stem) == squash(name)]
    if exact or not loose:
        return exact[0] if exact else None
    near = [p for p in pages if squash(name) and squash(name) in squash(p.stem)]
    if len(near) > 1:
        sys.exit(f"several match {name!r}: " + "; ".join(rel(p) for p in near))
    return near[0] if near else None


def cmd_memo(args) -> None:
    path = find_page(NOTES, args.title, loose=not args.m)
    if not args.m:
        if path is None:
            sys.exit(f"no note {args.title!r} in Notes/; create it with -m")
        print(rel(path))
        print(split(path.read_text(encoding="utf-8"))[1].strip())
        return
    if path is None:
        similar = find_page(NOTES, args.title, loose=True) if len(squash(args.title)) > 2 else None
        path = NOTES / f"{file_name(args.title, 'Note')}.md"
        lines = render("created", dt.date.today().isoformat()) + render("tags", ["note"])
        if args.project:
            lines += render("projects", [link(p) for p in args.project.split(",") if p.strip()])
        new_page(path, lines, "\n" + args.m.strip() + "\n")
        print(rel(path))
        if similar:
            print(f"note: a similar note exists: {rel(similar)}")
        return
    append_entry(path, f"- {dt.date.today().isoformat()}: {one_line(args.m)}")
    print(rel(path))


def list_items(path: Path) -> list[tuple[int, bool, str]]:
    """(line number, done, name) for each checklist line; the name is the text
    before ` — ` (a comment) or ` (` (the dates)."""
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        match = ITEM_RE.match(line)
        if match:
            name = re.split(r" — | \((?:added|done) ", match.group(2), maxsplit=1)[0].strip()
            out.append((i, match.group(1) != " ", name))
    return out


def cmd_add(args) -> None:
    path = find_page(LISTS, args.list, loose=False) or LISTS / f"{file_name(args.list, 'List')}.md"
    if not path.exists():
        new_page(path, render("tags", ["list"]), "\n")
        print(f"new list: {rel(path)}")
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, done, name in list_items(path):
        if squash(name) == squash(args.item):
            print(f"already on the list: {lines[i]}")
            return
    who = person(args.by)
    when = f"added {dt.date.today().isoformat()}" + (f" by {who}" if who else "")
    item = args.item.strip() + (f" — {one_line(args.m)}" if args.m else "") + f" ({when})"
    append_entry(path, f"- [ ] {item}")
    print(rel(path))


def cmd_check(args) -> None:
    path = find_page(LISTS, args.list, loose=True)
    if path is None:
        sys.exit(f"no list {args.list!r} in Lists/")
    items = list_items(path)
    hits = [x for x in items if squash(x[2]) == squash(args.item)] or \
           [x for x in items if squash(args.item) and squash(args.item) in squash(x[2])]
    if not hits:
        sys.exit(f"{args.item!r} is not on {path.stem}; add it with `add`")
    if len(hits) > 1:
        sys.exit(f"several items match {args.item!r}: " + "; ".join(h[2] for h in hits))
    i, done, name = hits[0]
    lines = path.read_text(encoding="utf-8").splitlines()
    line = lines[i]
    if args.undo:
        line = re.sub(r"^- \[[xX]\]", "- [ ]", line)
        # "(added D; done D: 8/10)" -> "(added D)"; "Name (done D)" -> "Name"
        line = re.sub(r"; done \d{4}-\d{2}-\d{2}.*\)$", ")", line)
        line = re.sub(r" \(done \d{4}-\d{2}-\d{2}.*\)$", "", line)
    elif done:
        print(f"already done: {line}")
        return
    else:
        mark = f"done {dt.date.today().isoformat()}" + (f": {one_line(args.m)}" if args.m else "")
        line = re.sub(r"^- \[ \]", "- [x]", line)
        line = line[:-1] + f"; {mark})" if line.endswith(")") and "(added " in line \
            else line + f" ({mark})"
    lines[i] = line
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(line)


def cmd_lists(args) -> None:
    if args.list:
        path = find_page(LISTS, args.list, loose=True)
        if path is None:
            sys.exit(f"no list {args.list!r} in Lists/")
        lines = path.read_text(encoding="utf-8").splitlines()
        shown = [lines[i] for i, done, _ in list_items(path) if not (args.open and done)]
        print("\n".join(shown) if shown else "(nothing on this list)")
        return
    for path in sorted(LISTS.glob("*.md")) if LISTS.is_dir() else []:
        items = list_items(path)
        done = sum(1 for _, d, _ in items if d)
        print(f"{path.stem}: {len(items) - done} open, {done} done  ({rel(path)})")


def cmd_find(args) -> None:
    """Every line (or file name) containing all the words, across the vault."""
    words = [w.lower() for w in args.words]
    hits = []
    for folder in (TASKS, ARCHIVE, JOURNAL, NOTES, LISTS, PROJECTS, PEOPLE):
        for path in sorted(folder.rglob("*.md")) if folder.is_dir() else []:
            name = path.stem.lower()
            if all(w in name for w in words):  # the name says it all: list the file once
                hits.append(rel(path))
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                low = line.lower()  # each word in the line, or in the file name
                if line.strip() and all(w in low or w in name for w in words):
                    hits.append(f"{rel(path)}: {line.strip()}")
    for line in hits[:args.limit]:
        print(line)
    if len(hits) > args.limit:
        print(f"... {len(hits) - args.limit} more; narrow the search or use --limit")
    print(f"({len(hits)} match{'es' if len(hits) != 1 else ''})", file=sys.stderr)


def notes_lint(problems: list[str], warnings: list[str]) -> None:
    for folder in (JOURNAL, NOTES, LISTS):
        for path in sorted(folder.rglob("*.md")) if folder.is_dir() else []:
            where = rel(path)
            content = path.read_text(encoding="utf-8")
            lines, body = split(content)
            if lines is None:
                warnings.append(f"{where}: no frontmatter")
                continue
            keys = [m.group(1) for m in (re.match(r"^([A-Za-z_][\w-]*):", l) for l in lines) if m]
            for key in sorted({k for k in keys if keys.count(k) > 1}):
                problems.append(f"{where}: field {key!r} appears twice (two machines "
                                "changed it; keep one)")
            meta = parse(lines)
            if folder == JOURNAL:
                d = day(path.stem)
                if d is None or len(path.stem) != 10 or path.parent.name != str(d.year):
                    warnings.append(f"{where}: journal pages are Journal/<year>/YYYY-MM-DD.md")
                elif str(meta.get("date") or "") != path.stem:
                    problems.append(f"{where}: date {meta.get('date')!r} differs from the file name")
            if folder == NOTES and meta.get("created") and not DATE_RE.match(str(meta["created"])):
                problems.append(f"{where}: created {meta['created']!r} is not YYYY-MM-DD")
            seen: dict[str, int] = {}
            entries = [l for l in body.splitlines() if l.startswith("- ")]
            for line in entries:
                seen[line] = seen.get(line, 0) + 1
            for line, count in seen.items():
                if count > 1:
                    warnings.append(f"{where}: this line appears {count} times: {line}")
            if folder == LISTS:
                # Identical lines were reported above; this catches the same item
                # written two ways (ticked on one machine, commented on another).
                raw = content.splitlines()
                groups: dict[str, list[str]] = {}
                for i, _, name in list_items(path):
                    groups.setdefault(squash(name), []).append(raw[i])
                for same in groups.values():
                    if len(set(same)) > 1:
                        warnings.append(f"{where}: an item is on the list {len(same)} times "
                                        f"(changed on two machines?); keep one: {same[0]}")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)


def public_github_origin() -> str | None:
    """origin's URL when it is a PUBLIC GitHub repository, else None.

    Asks the GitHub API without signing in: it answers only for public
    repositories, so a private one (or no network) returns None and sync goes on.
    """
    url = git("config", "--get", "remote.origin.url").stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if not match or os.environ.get("TASK_VAULT_ALLOW_PUBLIC") == "1":
        return None
    api = os.environ.get("TASK_VAULT_GITHUB_API", "https://api.github.com")
    try:
        with urllib.request.urlopen(f"{api}/repos/{match.group(1)}/{match.group(2)}",
                                    timeout=5) as response:
            return url if json.load(response).get("private") is False else None
    except Exception:  # 404 (private or missing), rate limit, offline
        return None


def template_version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@contextlib.contextmanager
def sync_lock(wait: bool):
    """One sync at a time per vault: the scheduled job, agents and commands share it."""
    git_dir = Path(git("rev-parse", "--absolute-git-dir").stdout.strip() or ROOT / ".git")
    lock = git_dir / "task-vault-sync.lock"
    deadline = time.monotonic() + (120 if wait else 0)
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 600:  # left by a crashed sync
                    lock.rmdir()
                    continue
            except OSError:
                continue
            if time.monotonic() >= deadline:
                sys.exit("another sync is running; nothing done (try again in a moment)")
            time.sleep(0.5)
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


def cmd_sync(args) -> None:
    """Commit local changes, then exchange them with origin, if there is one."""
    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        sys.exit("this vault is not a git repository; run setup.py first")
    with sync_lock(wait=not getattr(args, "no_wait", False)):
        sync_now(args)


def sync_now(args) -> None:
    message = args.m or "Update tasks"
    git("add", "-A")
    if git("diff", "--cached", "--quiet").returncode != 0:
        result = git("commit", "-m", message)
        if result.returncode != 0:
            sys.exit("commit failed:\n" + (result.stderr or result.stdout).strip())
        print("committed:", message)
    else:
        print("nothing to commit")
    if "origin" not in git("remote").stdout.split():
        print("no remote 'origin'; changes stay on this machine")
        return
    public = public_github_origin()
    if public:
        sys.exit(f"NOT SYNCED: {public} is a PUBLIC repository, so anyone could read these "
                 "tasks. Your changes are committed on this machine only. Make it private "
                 "(GitHub: Settings -> General -> Change visibility, or "
                 "`gh repo edit --visibility private --accept-visibility-change-consequences`), "
                 "then sync again.")
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    version_before = template_version()
    register_merge_driver()
    pull = git("pull", "--rebase", "--autostash", "origin", branch)
    if pull.returncode != 0 and "couldn't find remote ref" not in pull.stderr:
        conflicted = git("diff", "--name-only", "--diff-filter=U").stdout.split()
        git("rebase", "--abort")
        if conflicted:
            sys.exit("sync stopped, nothing pushed: these files were changed here and on "
                     "another machine, and could not be merged automatically:\n  "
                     + "\n  ".join(conflicted)
                     + "\nYour changes are committed on this machine. Run "
                     "`git pull --rebase`, edit each file to keep what is right, then "
                     "`git add <file>`, `git rebase --continue` and sync again.")
        sys.exit("pull failed, nothing pushed:\n" + (pull.stderr or pull.stdout).strip())
    if template_version() != version_before and (ROOT / "setup.py").exists():
        # Another machine ran `setup.py update`; refresh this machine's agent skills.
        print(f"template updated {version_before} -> {template_version()}")
        # Refreshes this machine's agent skills and turns on auto-sync (unless opted out).
        subprocess.run([sys.executable, str(ROOT / "setup.py"), "connect", "--agents", "installed"])
    push = git("push", "-u", "origin", branch)
    if push.returncode != 0:
        sys.exit("push failed:\n" + push.stderr.strip())
    print("synced with origin")
    notice_template_update()


def notice_template_update() -> None:
    """One line when the template has moved past the version this vault took."""
    if "template" not in git("remote").stdout.split():
        return
    try:
        taken = json.loads((ROOT / ".task-vault.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    latest = latest_template_commit()
    if latest and taken.get("template_commit") and latest != taken["template_commit"]:
        print("template update available: `python3 setup.py update --check` shows what's new")


def latest_template_commit() -> str | None:
    """Commit of the template's newest release tag (vX.Y.Z), else of its HEAD."""
    refs = {}
    for line in git("ls-remote", "template", "HEAD", "refs/tags/v*").stdout.splitlines():
        sha, _, name = line.partition("\t")
        refs[name] = sha
    releases = {}
    for name, sha in refs.items():
        match = re.fullmatch(r"refs/tags/(v(\d+)\.(\d+)\.(\d+))", name)
        if match:  # an annotated tag's commit is on its peeled `^{}` line
            key = tuple(int(n) for n in match.groups()[1:])
            releases[key] = refs.get(name + "^{}", sha)
    if releases:
        return releases[max(releases)]
    return refs.get("HEAD")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="open tasks, one line each")
    p.add_argument("--status", help="comma-separated statuses")
    p.add_argument("--assignee")
    p.add_argument("--project")
    p.add_argument("--when", choices=["today", "week", "overdue"])
    p.add_argument("--all", action="store_true", help="include done and cancelled")
    p.add_argument("--archive", action="store_true", help="also search Archive/")
    p.add_argument("--ready", action="store_true", help="only tasks that can be done now: "
                   "not blocked by open tasks, not waiting")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("new", help="create a task file")
    p.add_argument("title")
    p.add_argument("--assignee")
    p.add_argument("--project", help="comma-separated")
    p.add_argument("--goal", help="comma-separated goals this task counts toward")
    p.add_argument("--status", default="inbox")
    p.add_argument("--priority", default="normal")
    p.add_argument("--scheduled")
    p.add_argument("--due")
    p.add_argument("--recurrence", help='RRULE, e.g. "FREQ=WEEKLY;BYDAY=SA"')
    p.add_argument("--waiting-on", dest="waiting_on")
    p.add_argument("--note", help="first paragraph of the body")
    p.add_argument("--estimate", help="minutes (timeEstimate)")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("set", help="change fields: key=value (empty value removes)")
    p.add_argument("task")
    p.add_argument("pairs", nargs="+")
    p.add_argument("-m", help="log line")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("done", help="close a task, or one occurrence of a recurring one")
    p.add_argument("task")
    p.add_argument("--date", help="recurring: the occurrence to tick (default: the scheduled one)")
    p.add_argument("--spent", help="minutes it actually took (logged next to the estimate)")
    p.add_argument("-m", help="log line")
    p.set_defaults(func=cmd_done)

    p = sub.add_parser("note", help="add a dated detail or comment to the task's Notes")
    p.add_argument("task")
    p.add_argument("-m", required=True, help="the note")
    p.set_defaults(func=cmd_note)

    p = sub.add_parser("link", help="relate tasks: blocked by, subtask of, related to")
    p.add_argument("task")
    p.add_argument("--blocked-by", dest="blocked_by", metavar="TASK", help="TASK must finish first")
    p.add_argument("--unblock", metavar="TASK", help="remove TASK from blockedBy")
    p.add_argument("--parent", metavar="TASK", help="make this a subtask of TASK, or count it toward a goal")
    p.add_argument("--related", metavar="TASK", help="note a related task (Obsidian backlink)")
    p.add_argument("-m", help="why (logged)")
    p.set_defaults(func=cmd_link)

    p = sub.add_parser("show", help="one task with relations, notes and log")
    p.add_argument("task")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("log", help="append a dated line to the task's log")
    p.add_argument("task")
    p.add_argument("-m", required=True)
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("journal", help="add to a day's journal page, or print the day")
    p.add_argument("-m", help="the entry; without it, print the day: page, tasks, notes, lists")
    p.add_argument("--date", help="YYYY-MM-DD, today (default) or yesterday")
    p.add_argument("--by", metavar="PERSON", help="who wrote it (a People/ note)")
    p.add_argument("--no-time", dest="no_time", action="store_true", help="no HH:MM stamp")
    p.set_defaults(func=cmd_journal)

    p = sub.add_parser("memo", help="create a note in Notes/, add a dated line, or print it")
    p.add_argument("title")
    p.add_argument("-m", help="the text; without it, print the note")
    p.add_argument("--project", help="comma-separated, for a new note")
    p.set_defaults(func=cmd_memo)

    p = sub.add_parser("add", help="add an item to a list in Lists/ (creates the list)")
    p.add_argument("list")
    p.add_argument("item")
    p.add_argument("-m", help="a comment: why, who recommended it, where")
    p.add_argument("--by", metavar="PERSON", help="who added it (a People/ note)")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("check", help="tick a list item (watched, read, bought), with a comment")
    p.add_argument("list")
    p.add_argument("item")
    p.add_argument("-m", help="comment, e.g. a rating")
    p.add_argument("--undo", action="store_true", help="untick it")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("lists", help="all lists with counts, or one list's items")
    p.add_argument("list", nargs="?")
    p.add_argument("--open", action="store_true", help="only items not ticked")
    p.set_defaults(func=cmd_lists)

    p = sub.add_parser("find", help="search tasks, archive, journal, notes, lists, projects")
    p.add_argument("words", nargs="+")
    p.add_argument("--limit", type=int, default=60)
    p.set_defaults(func=cmd_find)

    p = sub.add_parser("lint", help="check every task, note, journal page and list")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("archive", help="move closed tasks older than --days to Archive/")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_archive)

    p = sub.add_parser("sync", help="commit, then pull --rebase and push to origin")
    p.add_argument("-m", help="commit message")
    p.add_argument("--no-wait", dest="no_wait", action="store_true",
                   help="if another sync is running, do nothing instead of waiting")
    p.set_defaults(func=cmd_sync)

    import goals  # tools/goals.py: goals, their progress and the period reviews
    goals.register(sub)

    for name in WRITERS:
        sub.choices[name].add_argument(
            "--no-sync", dest="no_sync", action="store_true",
            help="don't commit and push this change now (the next sync or auto-sync will)")

    p = sub.add_parser("merge-driver", help=argparse.SUPPRESS)  # called by git, see sync
    p.add_argument("base")
    p.add_argument("ours")
    p.add_argument("theirs")
    p.set_defaults(func=cmd_merge_driver)

    args = parser.parse_args()
    args.func(args)
    message = change_message(args)
    if message:
        sync_after_change(args, message)


# --- sync after each change ---------------------------------------------------
# Every command that writes commits, pulls and pushes as soon as it is done, so a
# change reaches the other machines within seconds. tools/autosync.py catches the
# rest (Obsidian and hand edits, and anything that could not be pushed offline).

WRITERS = ("new", "set", "done", "note", "link", "log", "archive",
           "journal", "memo", "add", "check")


def short(value: str | None, limit: int = 60) -> str:
    value = " ".join((value or "").split())
    return value if len(value) <= limit else value[:limit - 1] + "…"


def change_message(args) -> str | None:
    """The commit message for a command that changed files, else None."""
    c, m = args.command, getattr(args, "m", None)
    why = f": {short(m)}" if m else ""
    name = Path(getattr(args, "task", "") or "").stem or getattr(args, "task", "")
    if c == "new":
        return f'Add task "{short(args.title)}"'
    if c == "set":
        return f'Update "{name}": {short(", ".join(args.pairs))}{why}'
    if c == "done":
        return f'Done: "{name}"{why}'
    if c in ("note", "log", "link"):
        return f'{c.capitalize()} on "{name}"{why}'
    if c == "archive" and not args.dry_run:
        return "Archive closed tasks"
    if c == "journal" and m:
        return f"Journal {args.date or 'today'}{why}"
    if c == "memo" and m:
        return f'Note "{short(args.title)}"{why}'
    if c == "add":
        return f'Add "{short(args.item)}" to {args.list}'
    if c == "check":
        return f'{"Untick" if args.undo else "Tick"} "{short(args.item)}" in {args.list}{why}'
    if c == "goal":
        goal = getattr(args, "goal", "")
        if args.action == "new":
            return f'Add goal "{short(args.title)}" ({args.period})'
        if args.action == "set":
            changed = ", ".join(args.pairs) or "blockedBy"
            return f'Update goal "{goal}": {short(changed)}{why}'
        if args.action == "progress":
            return f'Progress on "{goal}": {args.change}{why}'
        if args.action == "carry":
            return f'Carry goal "{goal}" over to {args.to}'
        return None
    if c == "review":
        return f"Review {args.period}" + (": verdicts applied" if args.apply else "")
    return None


def sync_after_change_enabled(args) -> bool:
    if getattr(args, "no_sync", False) or os.environ.get("TASK_VAULT_AUTOSYNC") == "0":
        return False
    marker = ROOT / ".task-vault.json"  # only in a vault, never in the template repository
    try:
        return json.loads(marker.read_text(encoding="utf-8")).get("sync_after_change", True) \
            is not False
    except (OSError, ValueError):
        return False


def sync_after_change(args, message: str) -> None:
    """Commit and share this change now. Never fails the command: the change is saved
    either way, and what could not be pushed goes with the next sync."""
    if not sync_after_change_enabled(args) or not git("status", "--porcelain").stdout.strip():
        return
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            cmd_sync(argparse.Namespace(m=message, no_wait=False))
        lines = out.getvalue().strip().splitlines()
        shared = "synced with origin" in out.getvalue()
        print("saved and synced" if shared else "saved (committed; no remote to push to)",
              file=sys.stderr)
        for line in lines:  # pass on what sync wants the agent to see
            if line.startswith(("template update", "template updated")):
                print(line, file=sys.stderr)
    except SystemExit as stop:
        reason = str(stop.code or "").strip().splitlines()
        print("saved on this machine, not shared yet: " + (reason[0] if reason else "sync failed")
              + "\n(the next sync or auto-sync shares it; `python3 tools/autosync.py status` "
              "shows conflicts)", file=sys.stderr)


if __name__ == "__main__":
    main()
