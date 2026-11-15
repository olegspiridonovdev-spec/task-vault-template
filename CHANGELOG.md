# Changelog

`python3 setup.py update --check` shows the entries newer than your vault.

## 1.4.2

- `update --check` no longer reports an update when there is none: template files
  you edited and kept used to show as "update available" forever. It now lists
  only what the template changed since the version your vault took.

## 1.4.1

- `update` no longer overwrites template files you edited in your vault (a view
  in `Views/`, `AGENTS.md`, a tool). A file only you changed stays as it is; a
  file you and the template both changed is merged; if the same lines changed
  on both sides, yours stays and `update` names the file and how to compare it
  with the template's version. Files you never touched take the new version as before.

## 1.4.0

- **Every change is saved and shared at once.** Each command that changes a file
  (`new`, `set`, `done`, `note`, `link`, `log`, `archive`, `journal -m`, `memo -m`,
  `add`, `check`) commits, pulls and pushes as soon as it finishes, with a commit
  message that names the change, e.g. `Done: "Fix the tap": new washer`. Offline,
  the change is committed and goes with the next sync; the command never fails
  because of it. `--no-sync` skips it once (for a batch); `"sync_after_change": false`
  in `.task-vault.json` turns it off for the vault.
- **Auto-sync on every computer, by default.** `tools/autosync.py` runs `sync`
  every 5 minutes and after every reboot, so Obsidian and hand edits reach
  everyone too: a launchd agent on macOS, a systemd user timer on Linux (cron
  without systemd), Task Scheduler on Windows. `setup.py init` and `connect`
  install it (`--no-autosync` skips it), and every machine turns it on by itself
  when this update reaches it through `sync`. `autosync.py status` shows whether
  it runs, the last result, and other jobs that would sync the same vault twice.
  `autosync.py uninstall` turns it off on that machine for good.
- A conflict git can't merge (outside task files) shows one desktop notification,
  and another one when it is resolved. Offline runs are retried quietly.
- Syncs never overlap: the scheduled one, agents' and commands' wait for each
  other (`sync --no-wait` gives up instead).

## 1.3.0

- Journal, notes and lists next to the tasks. `Journal/<year>/YYYY-MM-DD.md`:
  one page per day (`journal -m`, `--date`, `--by`); `journal --date D` prints
  the day with its tasks, notes and list items. `Notes/`: one note per topic
  (`memo`). `Lists/`: one checklist per list, e.g. films and books
  (`add`, `check`, `lists`). `find` searches every folder.
- Obsidian: Daily notes opens today's journal page from `Templates/Journal.md`;
  `Views/Day.base` on each page shows that day's tasks and notes;
  `Views/Notes.base` lists notes, journal pages and lists.
- Journal pages, notes and lists merge line by line between machines; `lint`
  checks them and flags lines or items that appear twice.
- `show` on a task also lists journal pages and notes that link to it.
- `update` adds `.obsidian/daily-notes.json` when the vault has none (your own
  Obsidian settings are never overwritten). `setup init` also removes example
  files in subfolders.

## 1.2.0

- Sync no longer stops when two machines changed the same task: it merges
  field by field, keeps both log lines, and notes a clash in the task's log.
  A conflict in any other file stops cleanly and names the file.
- Sync and setup refuse to push to a public GitHub repository.
- Finishing a recurring task ticks the scheduled occurrence and moves
  `scheduled` to the next date, like TaskNotes. `done --date` picks another one.
- Tasks created in Obsidian (no `title` field, local-time stamps) pass `lint`.
- Task history and relations: `note` (a Notes section for details and comments,
  also after done), `show` (one task with notes, log and relations both ways),
  `link --blocked-by/--unblock/--parent/--related`, `list --ready`,
  `new --estimate`, `done --spent`. `done` reports unblocked tasks and open
  subtasks; `lint` catches missing blockers and dependency loops.
- Dependencies use TaskNotes' format (`blockedBy: - uid: ...`) and subtasks its
  convention (parent task in `projects`); the unused `parent` field is gone.
- Vaults update to the newest release tag of the template (not unreleased
  work on its main branch).

## 1.1.0

- Updates bring new template files and remove ones the template dropped
  (a file you edited is kept). The list of template files is `.template-files`.
- `update` pushes the result; other machines get it with `tasks.py sync`, which
  also refreshes their agent skills.
- `setup.py update --check` shows what an update would bring.
- Obsidian comes set up: TaskNotes plugin and settings in `.obsidian/`.
- Grok Build support. MIT license.

## 1.0.0

- First release.
