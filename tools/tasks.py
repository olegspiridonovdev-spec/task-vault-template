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
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "Tasks"
ARCHIVE = ROOT / "Archive"
PEOPLE = ROOT / "People"
PROJECTS = ROOT / "Projects"

STATUSES = ["inbox", "todo", "in-progress", "waiting", "done", "cancelled"]
CLOSED = {"done", "cancelled"}
PRIORITIES = ["none", "low", "normal", "high"]
LIST_KEYS = {"projects", "contexts", "tags", "blockedBy", "complete_instances"}
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
    meta: dict = {}
    key = None
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if match:
            key, value = match.group(1), match.group(2).strip()
            if value.startswith("[") and value.endswith("]") and not value.startswith("[["):
                meta[key] = [unquote(v) for v in value[1:-1].split(",") if v.strip()]
            else:
                meta[key] = unquote(value)
        elif key and line.lstrip().startswith("- "):
            if not isinstance(meta.get(key), list):
                meta[key] = []
            meta[key].append(unquote(line.lstrip()[2:]))
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
        return [f"{key}:"] + [f"  - {quote(v)}" for v in value]
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


def write(path: Path, lines: list[str], body: str) -> None:
    path.write_text("---\n" + "\n".join(lines) + "\n---\n" + body, encoding="utf-8")


def add_log(body: str, message: str) -> str:
    entry = f"- {dt.date.today().isoformat()}: {message}"
    if re.search(r"^## Log\s*$", body, flags=re.M):
        return body.rstrip("\n") + "\n" + entry + "\n"
    return body.rstrip("\n") + "\n\n## Log\n" + entry + "\n"


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
        instance = str(changes.pop("instance", "") or dt.date.today().isoformat())
        done = as_list(meta.get("complete_instances"))
        if instance not in done:
            done.append(instance)
        changes["complete_instances"] = done
        notes.append(f"recurring: marked the {instance} occurrence complete; series stays open")
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


# --- commands ---------------------------------------------------------------

def cmd_list(args) -> None:
    folders = (TASKS, ARCHIVE) if args.archive else (TASKS,)
    today = dt.date.today()
    horizon = {"today": today, "week": today + dt.timedelta(days=7),
               "overdue": today - dt.timedelta(days=1)}.get(args.when)
    statuses = set(args.status.split(",")) if args.status else None
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
    for note in update(path, {"status": "done"}, args.m):
        print(note)
    print(rel(path))


def cmd_log(args) -> None:
    path = resolve(args.task)
    update(path, {}, args.m)
    print(rel(path))


def cmd_lint(args) -> None:
    people = {p.stem for p in PEOPLE.glob("*.md")}
    projects = {p.stem for p in PROJECTS.glob("*.md")}
    problems, warnings = [], []
    wip: dict[str, int] = {}
    for t in load(TASKS, ARCHIVE):
        where = rel(t["_path"])
        status = t.get("status", "")
        if not t.get("title"):
            problems.append(f"{where}: no title")
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
        for project in as_list(t.get("projects")):
            if plain(project) not in projects:
                problems.append(f"{where}: project {plain(project)!r} has no note in Projects/")
        if status in CLOSED and not t.get("recurrence") and not t.get("completedDate"):
            problems.append(f"{where}: {status} but no completedDate")
        if status not in CLOSED and status != "inbox" and not who:
            warnings.append(f"{where}: {status} with nobody assigned")
        if status == "waiting" and not t.get("waiting_on"):
            warnings.append(f"{where}: waiting, but waiting_on does not say on what")
        if status == "in-progress" and who:
            wip[who] = wip.get(who, 0) + 1
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
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    pull = git("pull", "--rebase", "--autostash", "origin", branch)
    if pull.returncode != 0 and "couldn't find remote ref" not in pull.stderr:
        git("rebase", "--abort")
        sys.exit("pull failed, nothing pushed; resolve by hand (git status):\n"
                 + (pull.stderr or pull.stdout).strip())
    push = git("push", "-u", "origin", branch)
    if push.returncode != 0:
        sys.exit("push failed:\n" + push.stderr.strip())
    print("synced with origin")


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
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("set", help="change fields: key=value (empty value removes)")
    p.add_argument("task")
    p.add_argument("pairs", nargs="+")
    p.add_argument("-m", help="log line")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("done", help="close a task, or one occurrence of a recurring one")
    p.add_argument("task")
    p.add_argument("-m", help="log line")
    p.set_defaults(func=cmd_done)

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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
