# Task vault — rules for agents

Daily tasks and home management for several people, as plain Markdown files,
plus a journal, notes and lists (films, books …) next to them. Obsidian's
TaskNotes plugin shows the tasks as a Kanban board, a calendar and lists; you
work with the files. The files are the only source of truth.
These rules apply to every agent (Claude Code, Codex, OpenCode, Gemini, Grok, Hermes,
OpenClaw, …).

## Layout

- `Tasks/` — one file per open or recently closed task. The filename is the title.
- `Archive/<year>/` — closed tasks older than 30 days. Searchable, never deleted.
- `Projects/` — one note per project or area (Home, Car, Documents …): goals and context.
- `People/` — one note per person who can be assigned tasks.
- `Journal/<year>/YYYY-MM-DD.md` — one page per day, like a notebook.
- `Notes/` — one note per topic: things to keep that don't belong to a day.
- `Lists/` — one checklist per list: films to watch, books to read, gift ideas …
- `Goals/` — one file per goal for a week, a month or a year; tasks count toward it.
- `Reviews/<period>.md` — the review page at the end of a week, month or year (`review`).
- `Views/` — `.base` files for the board, calendar, lists, notes and the day view. Don't edit unless asked.
- `Templates/` — the shape of a task (`Task.md`), journal page and note.
- `tools/tasks.py` — list, create, update, check, archive and sync. Prefer it to hand edits:
  every command that changes something commits and pushes it right away.
- `tools/autosync.py` — the background job that syncs every 5 minutes and after
  every reboot on each machine (`status`, `run`, `install`, `uninstall`).
- `setup.py` — setup, agent connection and template updates. `.template-files` lists what updates replace.

## Task fields

| Field | Values | Notes |
|---|---|---|
| `title` | text | optional: the file name is the title (TaskNotes does not write this field) |
| `status` | `inbox` `todo` `in-progress` `waiting` `done` `cancelled` | required |
| `priority` | `high` `normal` `low` `none` | default `normal` |
| `assignee` | `"[[Person]]"` | one person; must have a note in `People/` |
| `projects` | list of `"[[Project]]"` | notes in `Projects/`; a task listed here makes this its **subtask** (TaskNotes convention; use `link --parent`) |
| `scheduled` | `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM` | when it is planned |
| `due` | `YYYY-MM-DD` | only a real deadline |
| `completedDate` | `YYYY-MM-DD` | set when closed |
| `recurrence` | RRULE, e.g. `FREQ=WEEKLY;BYDAY=SA` | repeating chores and bills; TaskNotes may prefix `DTSTART:YYYYMMDD;` |
| `complete_instances` | list of dates | finished occurrences of a recurring task |
| `skipped_instances` | list of dates | skipped occurrences (written by TaskNotes) |
| `waiting_on` | text | who or what, for `waiting` |
| `blockedBy` | list of `- uid: "[[Task]]"` + `reltype: FINISHTOSTART` | tasks that must finish first; use `link --blocked-by` |
| `contexts` | list, e.g. `call`, `shop`, `online` | optional |
| `timeEstimate` | minutes | optional; actual time goes in the log (`done --spent`) |
| `attachments` | list of `"[[file]]"` | receipts, scans, PDFs |
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
python3 tools/tasks.py note "Call the plumber" -m "valve is 3/4 inch; shop on Main St"
python3 tools/tasks.py show "Call the plumber"           # fields, relations, notes, log
python3 tools/tasks.py link "Fix the tap" --blocked-by "Buy washer"   # or --unblock
python3 tools/tasks.py link "Buy washer" --parent "Fix the tap"      # subtask
python3 tools/tasks.py link "Fix the tap" --related "Boiler service" -m "same plumber"
python3 tools/tasks.py list --ready                      # not blocked, not waiting
python3 tools/tasks.py new "Paint fence" --estimate 120   # minutes
python3 tools/tasks.py done "Paint fence" --spent 150 -m "two coats"
python3 tools/tasks.py journal -m "Decided to switch the boiler company"   # today's page
python3 tools/tasks.py journal -m "..." --date 2026-11-10 --by Anna
python3 tools/tasks.py journal [--date 2026-11-10]   # print a day: page, tasks, notes, list items
python3 tools/tasks.py memo "Wi-Fi setup" -m "router password is on the box" --project Home
python3 tools/tasks.py memo "Wi-Fi setup"            # print it; -m again adds a dated line
python3 tools/tasks.py add Films "Dune Part Two" -m "Alex recommended" --by Anna
python3 tools/tasks.py check Films "dune" -m "8/10"   # tick it (watched); --undo unticks
python3 tools/tasks.py lists                         # every list with counts
python3 tools/tasks.py lists Films --open            # what is still to watch
python3 tools/tasks.py find boiler                   # tasks, archive, journal, notes, lists, projects
python3 tools/tasks.py lint                          # after any change
python3 tools/tasks.py sync -m "what changed"        # commit, pull, push (also after hand edits)
python3 tools/autosync.py status                     # background sync: running? conflicts?
```

## How to work

- At the start of a session, run `sync` once so you see changes made on other machines.
- **Syncing is automatic.** Each command that changes a file commits, pulls and
  pushes as soon as it finishes ("saved and synced"); you don't need to run `sync`
  after it. Run `sync -m "..."` yourself only after editing files by hand. For a
  batch of many changes, pass `--no-sync` to each and `sync -m "..."` once at the end.
  If a command says "saved on this machine, not shared yet", the change is safe and
  goes with the next sync; mention it only if it keeps happening.
- Every machine runs `tools/autosync.py` (setup turns it on). **Never add another
  sync timer** (cron, launchd, systemd, your own scheduler, Obsidian Git) for the
  vault. If `autosync.py status` says it isn't scheduled on this machine, tell
  the user and offer `python3 tools/autosync.py install`.
- Find things with `list` and `find "word"` (every folder) before reading files.
  Open a file only when you need its notes.
- Before creating a task, search for an existing one with the same intent.
- Before working on or answering about a task, `show` it: it gives the history,
  the notes and what blocks it or depends on it, in one call.

## What goes where in a task

A task file is front matter (fields) and a body in three parts:

```
Description: what and why, links, contacts, prices.   <- free text, any shape

## Notes                                               <- details, findings, comments
- 2026-11-13: valve is 3/4 inch                           (`note`, also after done)

## Log                                                 <- what happened, dated
- 2026-11-13: created                                     (written by every command;
- 2026-11-14: status -> done: fixed; took 40 min           `log` for other events)
```

- **Details that come up** (a quote, a decision, a part number, a follow-up
  idea) go in Notes with `note`, not in new fields. Add a field only if it is
  in the table above.
- **Relations**: a task that must wait for another gets `link --blocked-by`; a
  piece of a bigger task gets `link --parent`; a task that merely relates to
  another (follows from it, same shop, same person) gets `link --related`,
  which writes a `[[link]]` in Notes (Obsidian shows it as a backlink).
- **A follow-up after completion**: create a new task and `link --related` it
  to the finished one; don't reopen the old task for new work.
- `done` says which tasks it unblocked and warns about open subtasks.
- `done` on a recurring task records the scheduled occurrence in
  `complete_instances` (or `--date YYYY-MM-DD` for another one), moves
  `scheduled` to the next occurrence and keeps the series open, as TaskNotes
  does. Never set a recurring task to `done` by hand.
- Tasks may also be edited in Obsidian at the same time. If two machines change
  the same task, `sync` merges it field by field; the newer edit wins a clash and
  the other value is noted in the log. If `sync` stops on a conflict in another
  file (or `autosync.py status` says "failed"), tell the user which files, and
  resolve it keeping both people's changes unless they say otherwise:
  `git pull --rebase`, edit the file, `git add`, `git rebase --continue`, `sync`.
  Never force-push, reset or discard someone else's commits.
- Every change gets a dated line under `## Log` in the task (the tool adds it).
- Ask before assigning a task to someone other than the person you're talking to,
  and before cancelling a task you did not create.
- Resolve "tomorrow", "Friday" etc. to `YYYY-MM-DD` in the user's local time.
- After a set of changes: `lint`. Git is the undo.

## Notes, journal and lists

Not everything is a task. Decide by what the user wants to keep:

| The user wants to … | Goes to | Command |
|---|---|---|
| do something (now or later) | a task | `new` |
| record what happened, a conclusion, a memory, a thought of the day | the journal, that day | `journal -m` |
| keep information that isn't about one day (a how-to, an idea, a decision and why) | a note | `memo` |
| collect things to come back to (films, books, places, gifts) | a list | `add` / `check` |
| record a detail about one task | the task's Notes | `note` |
| reach something this week, month or year | a goal, with tasks toward it | `goal new`, `new --goal` |

- **Journal**: one page per day, `Journal/<year>/YYYY-MM-DD.md`, fields `date`
  and `tags: [journal]`. `journal -m` adds `- HH:MM — text` (no time for other
  days; `--by Person` adds `Person: `). The page embeds `Views/Day.base`, which
  shows in Obsidian the tasks planned, due or finished that day and the notes
  written that day; `journal` without `-m` prints the same. "Yesterday",
  "on Friday" → `--date YYYY-MM-DD`. Obsidian's Daily notes button opens
  today's page in the same place.
- **Notes**: `Notes/<Title>.md`, fields `created`, `tags: [note]` and optionally
  `projects`. `memo` with a title that exists (ignoring case and punctuation)
  adds a dated line `- YYYY-MM-DD: text`; otherwise it creates the note. Before
  creating one, check `find` for a note with the same intent and add to it.
- **Lists**: `Lists/<Name>.md`, field `tags: [list]`, one line per item:
  `- [ ] Name — comment (added YYYY-MM-DD by Person)`. `check` ticks it and adds
  `; done YYYY-MM-DD: comment` (a rating, where, with whom). `add` creates the
  list on first use and won't add an item that is already there. To drop an
  item, tick it with the reason; don't delete lines.
- Link freely with `[[Task title]]`, `[[Note]]`, `[[2026-11-14]]`: `show` on a
  task lists the journal pages and notes that mention it.
- These files merge line by line between machines, so never add fields that
  change later (no `dateModified`); write new information as new lines. If
  `lint` warns that a line or item appears twice, keep one.
- Personal and private things are fine here: the vault's repository must be
  private (`sync` refuses a public one).

## Goals

A goal is what someone wants to reach in a week, a month or a year; tasks are
the steps. One file per goal in `Goals/`, one review page per period in `Reviews/`.

| Field | Values | Notes |
|---|---|---|
| `period` | `YYYY`, `YYYY-MM`, `YYYY-Www` | required; ISO weeks, Monday–Sunday (`2026-W47` = 16–22 Nov) |
| `owner` | `"[[Person]]"` or `"[[Household]]"` | required; Household = shared goals. Tasks still go to a person |
| `status` | `active` `achieved` `partial` `missed` `dropped` | `active` until the review gives a verdict |
| `parent` | `"[[Goal]]"` | the longer goal it serves (week → month → year); its period must contain this one |
| `blockedBy` | as for tasks | goals that must be achieved first |
| `target`, `progress`, `unit` | number, number, text | optional number goal ("12 books"); `goal progress` moves it |
| `projects` | list of `"[[Project]]"` | optional area |
| `completedDate`, `dateCreated`, `dateModified` | | maintained by the tool |
| `tags` | must include `goal` | never `task` |

- A task counts toward a goal by listing it in `projects` (`new --goal`,
  `link --parent "Goal"`). Link it to the lowest goal; progress rolls up
  through `parent`.
- Progress = done tasks of the goal and of the goals under it (cancelled ones
  don't count; a recurring task counts its occurrences in the period), plus the
  number target. It never sets the status: the people decide the verdict.
- The same title in another period gets the period in the file name:
  `Goals/Gym three times (2026-W48).md`.
- Ask before creating a goal for someone other than the person you're talking to.

```sh
python3 tools/tasks.py goal new "Read 12 books" --period 2026 --owner Anna --target 12 --unit books
python3 tools/tasks.py goal new "Finish Dune" --period 2026-11 --owner Anna --parent "Read 12 books"
python3 tools/tasks.py goal new "Repaint the hallway" --period 2026-11 --owner Household --project Home
python3 tools/tasks.py goal new "Buy the car" --period 2026 --owner Household --blocked-by "Save the deposit"
python3 tools/tasks.py new "Buy paint" --assignee Anna --goal "Repaint the hallway"
python3 tools/tasks.py link "Paint walls" --parent "Repaint the hallway"
python3 tools/tasks.py goal progress "Read 12 books" +1 -m "finished Dune"   # or -1, =5
python3 tools/tasks.py goal set "Repaint the hallway" status=dropped -m "moving in spring"
python3 tools/tasks.py goal carry "Repaint the hallway" --to 2026-12
python3 tools/tasks.py goal show "Read 12 books"   # tree, tasks, progress, blockers, log
python3 tools/tasks.py goals                       # active goals of this week, month and year
python3 tools/tasks.py goals --month --owner Anna  # or --week, --year, --period 2026-10, --all
python3 tools/tasks.py review --month              # Reviews/<month that just ended>.md
python3 tools/tasks.py review --month --apply      # verdicts -> goal statuses; offers carry-over
```

A review page has a generated block (between `<!-- generated … -->` and
`<!-- /generated -->`) that every `review` rewrites, and the people's part
below it, which is kept: `## Verdicts` (one `- Goal: verdict` line per goal),
`## What worked / what didn't`, `## Next …`.

## Routines (when asked)

- **Morning summary**: `list --when today` and `list --when overdue`, grouped by
  person; mention `waiting` items untouched for a week; mention this week's
  goals with "no tasks linked" (`goals --week`).
- **What happened on a day / "what did I write about X"**: `journal --date D`,
  `find X`.
- **Weekly review**: triage `inbox` (assign, project, date → `todo`), reschedule
  or cancel overdue tasks, check `waiting`, then `archive`, then `sync`.
- **End of a week, month or year**: `review --week|--month|--year`; show the
  page; ask each person for a verdict per goal (`achieved`, `partial`,
  `missed`, `dropped`) and what worked; write them into the page; then
  `review … --apply`, carry over what they want to keep, and set the next
  period's goals with `goal new`.
- **Archive**: `archive` moves done/cancelled tasks closed more than 30 days ago
  to `Archive/<year>/`. Recurring tasks stay in `Tasks/`.
- **Template update**: when `sync` prints "template update available", tell the
  user once. When they agree, or ask to "update the vault": run
  `python3 setup.py update --check`, show them what's new, then
  `python3 setup.py update` (it commits and pushes). Never edit files listed in
  `.template-files` to add features; those come from the template.
