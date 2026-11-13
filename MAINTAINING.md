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

1. **Here:** change, test, release (below), push.
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
4. Commit, push, and wait for CI (Linux, macOS, Windows) to pass before running
   `update` anywhere.

## Rules for template changes

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

1. The vault's current `setup.py` fetches the `template` remote, checks out the
   new `setup.py`, and runs it (stage 2), so the newest update logic always runs.
2. Stage 2 reads `.template-files` from the new template version, removes files
   the template dropped since the commit recorded in `.task-vault.json`, checks
   out the listed paths, records the new template commit, commits, refreshes
   this machine's agent skills, and runs `tasks.py sync`.

`git revert HEAD` in the vault undoes an update.
