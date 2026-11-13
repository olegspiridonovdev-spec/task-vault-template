# Changelog

`python3 setup.py update --check` shows the entries newer than your vault.

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
