#!/usr/bin/env python3
"""Helper for this task vault: list, create, update, check and archive tasks.

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
    python3 tools/tasks.py lint
    python3 tools/tasks.py archive [--days 30] [--dry-run]
    python3 tools/tasks.py sync [-m "what changed"]   commit; pull and push if there is a remote

Use `python` instead of `python3` on Windows. Works from any directory.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "Tasks"
ARCHIVE = ROOT / "Archive"
PEOPLE = ROOT / "People"
PROJECTS = ROOT / "Projects"

STATUSES = ["inbox", "todo", "in-progress", "waiting", "done", "cancelled"]
CLOSED = {"done", "cancelled"}
PRIORITIES = ["none", "low", "normal", "high"]
LIST_KEYS = {"projects", "contexts", "tags", "blockedBy", "complete_instances",
             "skipped_instances"}
LINK_KEYS = {"assignee", "projects", "parent", "blockedBy"}
DATE_KEYS = ("scheduled", "due", "completedDate")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?Z?)?$")
WIP_LIMIT = 3


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
    name = re.sub(r'[\\/:*?"<>|#^\[\]]', "", title).strip()[:90] or "Task"
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
    if args.project:
        lines += render("projects", [link(p) for p in args.project.split(",") if p.strip()])
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
        parent = find_task(args.parent, tasks)
        projects = as_list(meta.get("projects"))
        if parent["_path"].stem.lower() not in [name_of(p).lower() for p in projects]:
            projects.append(link(parent["_path"].stem))
        lines = set_key(lines, "projects", projects)
        logged.append(f"subtask of [[{parent['_path'].stem}]]")
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
    for other in tasks.values():
        if other["_path"] == path:
            continue
        other_body = split(other["_path"].read_text(encoding="utf-8"))[1]
        if re.search(rf"\[\[(?:[^\]|]*/)?{re.escape(path.stem)}(?:\|[^\]]*)?\]\]", other_body):
            mentions.append(title_of(other))
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
        for project in as_list(t.get("projects")):  # a project note, or a parent task
            if name_of(project) not in projects and name_of(project).lower() not in tasks:
                problems.append(f"{where}: project {name_of(project)!r} has no note in "
                                "Projects/ and is not a task")
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


def cmd_sync(args) -> None:
    """Commit local changes, then exchange them with origin, if there is one."""
    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        sys.exit("this vault is not a git repository; run setup.py first")
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
    p.add_argument("--parent", metavar="TASK", help="make this a subtask of TASK")
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

    p = sub.add_parser("lint", help="check every task against the rules")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("archive", help="move closed tasks older than --days to Archive/")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_archive)

    p = sub.add_parser("sync", help="commit, then pull --rebase and push to origin")
    p.add_argument("-m", help="commit message")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("merge-driver", help=argparse.SUPPRESS)  # called by git, see sync
    p.add_argument("base")
    p.add_argument("ours")
    p.add_argument("theirs")
    p.set_defaults(func=cmd_merge_driver)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
