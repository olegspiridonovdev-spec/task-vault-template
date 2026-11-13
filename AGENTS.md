# Task vault — rules for agents

Daily tasks and home management for several people, as plain Markdown files.
Obsidian's TaskNotes plugin shows the same files as a Kanban board, a calendar
and lists; you work with the files. The files are the only source of truth.
These rules apply to every agent (Claude Code, Codex, OpenCode, Gemini, Grok, Hermes,
OpenClaw, …).

## Layout

- `Tasks/` — one file per open or recently closed task. The filename is the title.
- `Archive/<year>/` — closed tasks older than 30 days. Searchable, never deleted.
- `Projects/` — one note per project or area (Home, Car, Documents …): goals and context.
- `People/` — one note per person who can be assigned tasks.
- `Views/` — `.base` files for the board, calendar and lists. Don't edit unless asked.
- `Templates/Task.md` — the shape of a task file.
- `tools/tasks.py` — list, create, update, check, archive and sync. Prefer it to hand edits.

## Task fields

| Field | Values | Notes |
|---|---|---|
| `title` | text | required |
| `status` | `inbox` `todo` `in-progress` `waiting` `done` `cancelled` | required |
| `priority` | `high` `normal` `low` `none` | default `normal` |
| `assignee` | `"[[Person]]"` | one person; must have a note in `People/` |
| `projects` | list of `"[[Project]]"` | must have notes in `Projects/` |
| `scheduled` | `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM` | when it is planned |
| `due` | `YYYY-MM-DD` | only a real deadline |
| `completedDate` | `YYYY-MM-DD` | set when closed |
| `recurrence` | RRULE, e.g. `FREQ=WEEKLY;BYDAY=SA` | repeating chores and bills |
| `complete_instances` | list of dates | finished occurrences of a recurring task |
| `waiting_on` | text | who or what, for `waiting` |
| `blockedBy` | list of `"[[Task title]]"` | optional |
| `parent` | `"[[Task title]]"` | optional, for subtasks |
| `contexts` | list, e.g. `call`, `shop`, `online` | optional |
| `timeEstimate` | minutes | optional |
| `dateCreated`, `dateModified` | ISO timestamps | maintained by the tool |
| `tags` | must include `task` | this is how TaskNotes finds tasks |

The names are TaskNotes' defaults on purpose. Don't invent new fields; add one
to this table first if it is really needed.

## Statuses

- `inbox` — captured, not triaged. Anything the user dictates lands here.
- `todo` — triaged: has an assignee, a project and, if timed, `scheduled` or `due`.
- `in-progress` — being done. At most 3 per person.
- `waiting` — blocked on someone or something; fill `waiting_on`.
- `done` — finished; `completedDate` set.
- `cancelled` — won't be done. Never delete a task; cancel it and say why in the log.

## Commands

Run from the vault root (`python` instead of `python3` on Windows). From another
directory, use the full path to `tools/tasks.py`; it finds the vault itself.

```sh
python3 tools/tasks.py list                          # open tasks, one line each
python3 tools/tasks.py list --when today             # in progress, or scheduled/due by today
python3 tools/tasks.py list --when week --assignee Anna
python3 tools/tasks.py list --when overdue
python3 tools/tasks.py list --status waiting
python3 tools/tasks.py list --all --archive --project Car    # history too
python3 tools/tasks.py new "Call the plumber" --assignee Anna --project Home --scheduled 2026-11-20
python3 tools/tasks.py set "Call the plumber" status=waiting waiting_on="plumber's reply" -m "left a message"
python3 tools/tasks.py done "Call the plumber" -m "fixed the tap"
python3 tools/tasks.py log "Call the plumber" -m "price agreed: 120"
python3 tools/tasks.py lint                          # after any change
python3 tools/tasks.py sync -m "what changed"        # commit, pull, push
```

## How to work

- At the start of a session, run `sync` once so you see changes made on other machines.
- Find tasks with `list` and `grep -ril "word" Tasks Archive` before reading files.
  Open a file only when you need its notes.
- Before creating a task, search for an existing one with the same intent.
- `done` on a recurring task records today's occurrence in `complete_instances`
  and keeps the series open. Never set a recurring task to `done` by hand.
- Every change gets a dated line under `## Log` in the task (the tool adds it).
- Ask before assigning a task to someone other than the person you're talking to,
  and before cancelling a task you did not create.
- Resolve "tomorrow", "Friday" etc. to `YYYY-MM-DD` in the user's local time.
- After a set of changes: `lint`, then `sync -m "<what changed>"`. Git is the undo.

## Routines (when asked)

- **Morning summary**: `list --when today` and `list --when overdue`, grouped by
  person; mention `waiting` items untouched for a week.
- **Weekly review**: triage `inbox` (assign, project, date → `todo`), reschedule
  or cancel overdue tasks, check `waiting`, then `archive`, then `sync`.
- **Archive**: `archive` moves done/cancelled tasks closed more than 30 days ago
  to `Archive/<year>/`. Recurring tasks stay in `Tasks/`.
