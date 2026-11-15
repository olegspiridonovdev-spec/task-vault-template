# Maintaining the template

This repository is the **template**, not a task vault. It holds only example
tasks (CI fails on anything else). Real tasks live in each person's private
vault, made from this template with `setup.py`. `setup.py init` deletes this
file from those vaults.

## How a change reaches the vaults

```
template repo (here) --push--> GitHub --`setup.py update`--> one machine's vault
                                                              |
                                              `tasks.py sync` (push)
                                                              v
                                    the vault's private repo --sync--> other machines
```

1. **Here:** change, test, push to `main`, then **release** it by pushing a tag
   `vX.Y.Z` (below). Vaults only ever take the newest release tag, so work in
   progress on `main` is safe.
2. **Any one machine with the vault:** `python3 setup.py update`. It takes the
   new template files, commits ("Update template A -> B") and pushes.
3. **Every other machine:** nothing to do. Its next `tasks.py sync` (agents run
   it at the start of each session) pulls the update and refreshes that
   machine's agent skills.

Until step 2, every `sync` prints *"template update available"*, so the vault's
agents tell the user an update is ready.

## Making a change

```sh
# edit files
python3 -m unittest discover tests        # all must pass
python3 tools/tasks.py lint
```

Before you push a change meant for vaults:

1. **Bump `VERSION`** (`1.1.0` -> `1.2.0` for a feature, `1.1.1` for a fix).
2. **Add a `## <version>` section at the top of `CHANGELOG.md`**, written for the
   person updating. `update --check` and `update` print it.
3. **New top-level file or folder?** Add it to `.template-files`, or vaults
   never receive it. Files inside folders already listed (`tools/`, `Views/`, …)
   need nothing.
4. Commit, push, and wait for CI (Linux, macOS, Windows) to pass.
5. **Release:** tag the commit with the same version and push the tag. CI
   checks the tag matches `VERSION`.

   ```sh
   git tag -a v1.3.0 -m "v1.3.0" && git push origin v1.3.0
   gh release create v1.3.0 --notes-file <(awk '/^## 1.3.0/{f=1;next}/^## /{f=0}f' CHANGELOG.md)
   ```

   Until you push the tag, vaults see nothing. A wrong release is fixed by
   releasing a new version, never by moving or deleting a tag.

## Rules for template changes

- **Never schedule from tests.** The test harness sets `TASK_VAULT_SCHEDULER=0`,
  so `tools/autosync.py` and `setup.py` never install a real launchd, systemd,
  cron or Task Scheduler job. Keep it in any new harness. `TASK_VAULT_AUTOSYNC_QUIET=1`
  writes notifications to the log instead of the desktop.
- **Sync after each change** runs only in a vault (`.task-vault.json` exists), so
  using `tasks.py` in this repository never commits or pushes here. A new command
  that writes files goes in `WRITERS` and `change_message()` in `tools/tasks.py`.

- **The template owns only what `.template-files` lists.** `update` replaces
  those paths and never touches `Tasks/`, `Archive/`, `People/`, `Projects/` or
  `.obsidian/`. Don't add those to the list.
- **Renaming or deleting a template file is safe.** `update` removes files the
  template dropped, unless the person edited them (then it keeps them and says so).
- **Changing task fields or statuses** means existing task files may need a
  migration. Do it in `setup.py update` (stage 2 runs the new code), keep it
  idempotent, and add a test with old-format files.
- **Obsidian settings** (`.obsidian/`) belong to each vault after setup, so
  updates don't overwrite them. A new TaskNotes version or setting reaches new
  vaults only. Existing ones update the plugin from inside Obsidian.
- **Example tasks** must keep `example: true` in their front matter.

## How `update` works

1. The vault's current `setup.py` fetches the `template` remote and picks the
   newest release tag (or `main` if the template has no tags yet), checks out
   that version's `setup.py`, and runs it (stage 2), so the newest update logic
   always runs.
2. Stage 2 reads `.template-files` from the new template version, removes files
   the template dropped since the commit recorded in `.task-vault.json`, and
   takes the listed paths file by file against that commit: files the vault
   never changed get the new version, files only the vault changed stay, files
   both changed are merged with `git merge-file` (on a clash the vault's version
   stays and the file is named). Then it records the new template commit,
   commits, refreshes this machine's agent skills and auto-sync, and runs
   `tasks.py sync`. So a template change to a file must still work for vaults
   that kept their own copy of it.

`git revert HEAD` in the vault undoes an update.
