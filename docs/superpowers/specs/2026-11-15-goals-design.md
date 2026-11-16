# Goals: weekly, monthly and yearly goals linked to tasks — design

Date: 2026-11-15 · Target version: 1.5.0 · Status: implemented (see Refinements)

## Problem

The vault holds tasks, projects, a journal, notes and lists, but nothing for
goals. People want to set goals for a week, a month and a year, tie tasks to
them (including tasks that depend on each other), see progress, and at the end
of each period get a formatted review: what was achieved, what slipped, why.

## Decisions

- Goals are **their own notes in `Goals/`** (not tasks with a tag, not a
  checklist per period). Rejected: goals-as-tasks (clutters the board, a
  verdict is not a workflow status); one checklist page per period (tasks
  can't link to a line, so no computed progress).
- Goals are **personal or shared**: `owner` is a person or `Household`.
- Progress is **mixed**: computed from linked tasks by default, plus an
  optional numeric target updated by command. Numbers never set the verdict.
- Goal commands live under a **`goal` subcommand**; `new`/`set`/`done` stay
  task-only.
- This repo is the public template: it gets the feature and example files only
  (Anna, Household). Real goals live in users' vaults and arrive via
  `setup.py update`.

## 1. Files and fields

### Folders

- `Goals/<Title>.md` — one file per goal; the file name is the title.
- `Reviews/<period>.md` — one page per reviewed period: `2026-W47.md`,
  `2026-11.md`, `2026.md`.
- Both are user content (not in `.template-files`). `setup.py update` and
  `setup.py` create them if missing, never overwrite them.
- `People/Household.md` — created if missing; a valid `owner` for shared goals
  and links, but **not** a valid task `assignee` (lint rejects it there).

### Goal fields

| Field | Values | Notes |
|---|---|---|
| `type` | `goal` | |
| `period` | `YYYY`, `YYYY-MM`, `YYYY-Www` | required; ISO weeks |
| `owner` | `"[[Person]]"` or `"[[Household]]"` | required; must have a note in `People/` |
| `status` | `active` `achieved` `partial` `missed` `dropped` | `active` while the period runs; the rest are verdicts |
| `parent` | `"[[Goal]]"` | one level up (week → month → year); optional |
| `blockedBy` | list of `- uid: "[[Goal]]"` + `reltype: FINISHTOSTART` | goals that must be achieved first; same shape as tasks |
| `target` | number | optional numeric target |
| `progress` | number | current value for `target`; default 0 |
| `unit` | text | e.g. `books`, `km`, `EUR` |
| `projects` | list of `"[[Project]]"` | optional area |
| `dateCreated`, `dateModified` | ISO timestamps | maintained by the tool; the merge driver uses `dateModified` |
| `completedDate` | `YYYY-MM-DD` | set when status leaves `active` |
| `tags` | must include `goal` | never `task`, so TaskNotes ignores goals |

Body, same shape as a task: free description (why it matters, what "done"
means), `## Notes`, `## Log` (every command writes a dated log line).

### Period semantics

- `YYYY` = 1 Jan – 31 Dec; `YYYY-MM` = that calendar month; `YYYY-Www` = ISO
  week, Monday–Sunday (`2026-W47` = 2026-11-16 … 2026-11-22). `W53` is valid
  only in ISO years that have 53 weeks.
- "Current" week/month/year are resolved in the user's local time.
- A `parent`'s period must contain the child's period (a week goal's parent is
  a month or year goal whose range contains the whole week — or, for a week
  spanning two months, the month containing its Thursday, per ISO; lint
  enforces this rule, `goal new` refuses violations).

### Linking tasks to goals

- A task links to a goal by listing it in `projects:` (existing TaskNotes
  mechanism; `link --parent "Goal"` writes it). A task may list projects and
  goals together, and several goals.
- Linking to the lowest goal is enough: progress rolls up through `parent`.

### Sync / merge

- `.gitattributes`: `Goals/**/*.md merge=task-vault` (field-by-field merge
  driver, as for tasks — goals change over time); `Reviews/**/*.md merge=union`.
- The merge driver must accept goal files (same front-matter + log format).

## 2. Commands

All changing commands commit and sync on their own; `--no-sync` for batches.

```sh
tasks.py goal new "Title" --period P --owner NAME [--parent G] [--target N --unit U]
                          [--project PR] [--blocked-by G] [-m "description"]
tasks.py goal set "Title" key=value ... [-m "why"]        # status=dropped, period=..., etc.
tasks.py goal progress "Title" +N | -N | =N [-m "..."]
tasks.py goal carry "Title" --to P                        # copy to period P, old -> partial
tasks.py goal show "Title"                                # tree, tasks, progress, blockers, log
tasks.py goals [--period P | --week | --month | --year] [--owner NAME] [--all]
tasks.py new "Task" --goal "Title"                        # shortcut: adds goal to projects
tasks.py link "Task" --parent "Goal"                      # existing; now accepts goals
tasks.py review (--week | --month | --year | --period P) [--apply]
```

- `goals` default: active goals of the current week, month and year, grouped
  by owner, each with its progress summary.
- `goal carry` creates a new goal in period P with the same fields (parent is
  re-resolved: kept if it still contains P, otherwise dropped with a warning),
  links the two with a Notes line both ways, sets the old goal to `partial`.
  Open tasks linked to the old goal are re-linked to the new one.
- `goal set status=<verdict>` sets `completedDate`; `status=active` clears it.
- Name matching for goals works like `find_task` (case-insensitive, unique
  prefix), searching `Goals/` only.

### Progress calculation

Used by `goals`, `goal show` and `review`:

- **Tasks:** over the goal and all its descendant goals, done ÷ (done + open)
  linked tasks. Cancelled tasks are excluded. A recurring task counts its
  occurrences inside the goal's period: completed = `complete_instances` in the
  period, total = occurrences scheduled in the period (shown e.g. "Gym 3/4").
- **Number:** a goal with `target` shows `progress/target unit (pct%)`. Numbers
  are not summed from child goals.
- **Child goals:** "3 of 4 month goals achieved".
- No number ever changes `status`.

### Additions to existing commands

- `list --when today|week` appends `→ Goal` to tasks linked to an active goal.
- `find` searches `Goals/` and `Reviews/`.
- Morning summary routine (AGENTS.md) mentions this week's active goals that
  have no open linked tasks.
- `lint` accepts goals in task `projects:` and checks goal files (below).

## 3. The review page

`review --month` for 2026-11 writes `Reviews/2026-11.md`:

```markdown
---
period: 2026-11
type: review
created: 2026-12-01
tags: [review]
---

# November 2026 — review

<!-- generated: refreshed by `tasks.py review`; write below the line, not here -->
## Goals
### <Owner>            (one block per owner; people first, Household last)
- ✅|🟡|❌|⬜|⛔ **Goal** → Parent · N/T unit (pct%) · tasks d/n
  - open: Task (scheduled YYYY-MM-DD, missed)
## Year so far (2026)          (month review only; parent year goals)
## Done this month (N tasks)   (by person, then project; one line each with date)
## Slipped                     (open linked tasks scheduled/due inside the period)
## From the journal            (journal lines in the period mentioning a goal or its tasks, linking [[YYYY-MM-DD]])
<!-- /generated -->

## Verdicts
- Goal title: achieved|partial|missed|dropped
## What worked / what didn't
## Next month
```

Icons: ✅ achieved · 🟡 partial or active with some progress · ❌ missed ·
⬜ active with no progress or no tasks · ⛔ blocked by an unachieved goal ·
dropped goals are listed struck through.

Rules:

- Re-running `review` replaces only the text between the `generated` markers;
  everything else is kept. New goals of the period get a blank `Verdicts` line
  appended; existing lines are never rewritten.
- `Verdicts` is pre-filled: closed goals with their status, active ones blank.
- `review --apply` reads `Verdicts`, sets each named goal's `status` (with a
  log line "verdict from Reviews/<period>"), leaves blank or unchanged ones
  alone, reports unknown goal names and invalid verdicts without failing the
  rest. It then lists still-active goals and offers to `carry` each to the next
  period (interactive y/n; non-interactive: prints the `goal carry` commands
  instead of running them).
- **Week page:** goals of the week + done/slipped tasks; no journal section.
  **Year page:** year goals with their month goals as a tree, plus a
  month-by-month line (`Jan 4/5 · Feb 3/5 · …`) of achieved month goals.
- A period with no goals still gets the "Done" section.
- Default period for `--week/--month/--year`: the one that just ended; if the
  current period ends within 2 days, the current one.

## 4. Views, templates, docs

- `Views/Goals.base`: tables "Active goals" (grouped by owner, newest period
  first), "All goals" (by period) and "Reviews". Bases cannot reliably compare
  a text period with today's ISO week, so `tasks.py goals` gives the exact
  current periods.
- `Templates/Goal.md`, `Templates/Review.md` for manual creation in Obsidian.
- `.gitattributes` lines (section 1). `.template-files` unchanged except new
  files are under already-listed `Views`/`Templates`.
- `setup.py` (setup and update) creates `Goals/`, `Reviews/`,
  `People/Household.md` if missing.
- `AGENTS.md`: "Goals" section with the field table, commands, and routines
  for end of week / month / year (`review`, fill verdicts, `review --apply`,
  carry); a row in "what goes where": "something to achieve this
  week/month/year → a goal (`goal new`)". Same in `README.md`, `skill/`,
  `CHANGELOG.md`; `VERSION` → 1.5.0.
- Examples in the template: two goals (an Anna year goal with one month goal,
  a Household month goal) and one linked example task.

## 5. Lint rules for goals

Problems: missing/invalid `period`; `owner` without a `People/` note; invalid
`status`; `parent` not a goal; parent's period does not contain the child's;
`blockedBy` entry not a goal; `target` or `progress` not a number; closed
status without `completedDate`; `Household` used as a task `assignee`.
Warnings: active goal whose period has ended; active goal blocked by a goal
that is `missed` or `dropped`; a parent chain with a cycle.

## 6. Tests (`tests/test_vault.py`, existing temp-vault fixtures)

- Period parsing and ranges: year, month, week; W53 valid/invalid; week
  spanning a year change (2026-W53 / 2027-W01); parent containment.
- `goal new` with every flag; refusal on bad period/owner/parent; Household owner.
- Progress roll-up through a 3-level tree; cancelled tasks excluded; recurring
  task occurrences counted inside the period; task linked to two goals.
- `goal progress` +N/-N/=N; `goal carry` (new goal, old → partial, open tasks
  re-linked).
- `review`: creates page; re-run keeps user text and verdicts; `--apply` sets
  statuses and reports bad lines; week and year page shapes.
- `lint` goal rules; `list` shows `→ Goal`; `find` hits Goals/ and Reviews/.
- Merge driver: two machines change different fields of one goal → both kept.

## Refinements (decided while planning)

1. Goals also get `dateModified` (maintained by the tool) — the merge driver needs it to pick the newer edit.
2. `Goals/` and `Reviews/` are created on first write by the tool, not by setup (git does not track empty folders). Setup/update only ensure `People/Household.md`.
3. A goal whose title already has a file gets the period in its file name: `Goals/Gym three times (2026-W48).md` (also used by `goal carry`). The `title` field keeps the plain title.
4. A recurring task counts the occurrences inside the period of the goal it is linked to (the shortest one if several), clipped to the goal being measured.
5. Summary wording: `"0 of 1 month goal achieved"` / `"2 of 3 week goals achieved"`; percentages are floored.
6. Dropped goals show the icon `➖` in `goals` output and are struck through on review pages.

## Out of scope

Goal reminders/notifications, charts, numeric progress inferred from lists
(e.g. counting ticked books automatically), goals longer than a year.
