# Task Vault

A shared task board for daily tasks and home management: tasks split between
people and projects, shown as a **Kanban board**, a **calendar** and **lists**,
and managed together with any AI agent: Claude Code, OpenAI Codex, OpenCode,
Gemini CLI, Hermes, OpenClaw, or anything else that can read files and run a
command.

Every task is one Markdown file. There is no database and no server, and git
keeps the history. Each person or household keeps their own vault in a
**private** repository.

## Install

You need **git** and **Python 3.9+**. To create the private repository
automatically, you also need the GitHub CLI (`gh`), signed in with `gh auth login`.

### Option A: on GitHub (no command line for the repository)

1. On this template's GitHub page, click **Use this template → Create a new
   repository**, give it a name, and choose **Private**.
2. Clone your new repository and run setup in it:

   ```sh
   git clone https://github.com/<you>/<your-vault>.git ~/Tasks
   cd ~/Tasks
   python3 setup.py
   ```

   When setup asks whether the remote is your own vault repository, answer **y**.

### Option B: one command

```sh
git clone <template-url> ~/Tasks && cd ~/Tasks
python3 setup.py init --people "Anna,Max" --private-repo my-tasks
```

`--private-repo` creates a private GitHub repository through `gh` and pushes the
vault to it. If you use another host (GitLab, Bitbucket, Gitea), create an empty
private repository there and pass `--remote <its git url>` instead.

### What setup does

1. Removes the example tasks and adds a note in `People/` for each name you give.
2. Makes the folder a git repository with a first commit. If you cloned the
   template, its remote is renamed `template` so that updates can come from it.
3. Connects the AI agents it finds on this machine (see below).
4. Creates the private repository and pushes to it, if you asked for one.

On a **second machine**, clone *your* private vault (not the template) and run
`python3 setup.py connect`. Everything else is already in the repository.

## Connecting AI agents

There are two ways an agent finds the vault, and setup arranges both.

- **Started inside the vault folder**, every agent reads the rules in `AGENTS.md`.
  `CLAUDE.md` and `GEMINI.md` point Claude Code and Gemini CLI to the same file.
- **Started anywhere else** (a personal assistant such as OpenClaw or Hermes, or
  a coding agent in another project), the agent finds the vault through a
  `task-vault` skill that setup installs:

| Agent | Skill installed to |
|---|---|
| Claude Code | `~/.claude/skills/task-vault/` |
| OpenAI Codex, OpenCode, Gemini CLI, OpenClaw | `~/.agents/skills/task-vault/` (one shared folder) |
| Hermes | `~/.hermes/skills/task-vault/` |

```sh
python3 setup.py connect                      # agents detected on this machine
python3 setup.py connect --agents all         # every location above
python3 setup.py connect --agents codex,hermes
python3 setup.py connect --remove             # uninstall the skill
```

If an agent isn't listed, give it this one instruction: *"Read
`<path to vault>/AGENTS.md` and manage tasks only through
`python3 <path to vault>/tools/tasks.py`."* The tool prints short, one-line answers,
so an agent spends few tokens per question.

## One-time Obsidian setup (for the board and calendar)

1. Install Obsidian (obsidian.md) and choose **Open folder as vault** → this folder.
2. **Settings → Core plugins**: make sure **Bases** is on (Obsidian 1.9 or newer).
3. **Settings → Community plugins**: turn them on, **Browse**, install **TaskNotes**
   (the stable 4.x line), and enable it.
4. **Settings → TaskNotes**:
   - **General**: tasks folder `Tasks`, archive folder `Archive`; identify tasks by
     the tag `task` (the default).
   - **Task statuses**: replace the defaults with, in this order:
     `inbox`, `todo`, `in-progress`, `waiting`, `done` (completed), `cancelled` (completed).
     Default status: `inbox`.
   - **Priorities**: keep `none`, `low`, `normal`, `high`; default `normal`.
   - **Task properties → custom (user) fields**: add `assignee` and `waiting_on` (text).
5. Open `Views/Board.base`. If the **By status** view shows no row per person, open
   the view's settings and set **Swim lane** to `assignee`.

The `.obsidian/` folder is committed. A second machine or person who opens the
vault gets the same plugins and settings, and only has to approve community
plugins once.

## Views

| File | Views |
|---|---|
| `Views/Board.base` | **By status** (columns = status, a row per person), **By person**, **By project** |
| `Views/Calendar.base` | **Month**, **Week**, **Agenda** (open tasks), **Completed** (done tasks on their completion date) |
| `Views/Lists.base` | **Today**, **Overdue**, **Next 7 days**, **Inbox**, **Waiting**, **Done this week**, **Done (all)** |

Dragging a card on the board changes the task's `status` in its file, so agents
see it immediately. If the **Completed** calendar stays empty, **Done (all)** in
`Lists.base` shows the same history.

## Everyday use

- Ask your agent: *"add 'buy filters' for Anna on Friday"*, *"what's on today?"*,
  *"Max fixed the tap"*, *"weekly review"*.
- Or in Obsidian: the TaskNotes command **Create new task**, or drag cards on the board.
- Or in a terminal: `python3 tools/tasks.py --help`.
- New person: a note in `People/`. New project or area: a note in `Projects/`.
- Repeating chores and bills: set `recurrence`, e.g. `FREQ=WEEKLY;BYDAY=SA` or
  `FREQ=MONTHLY;BYMONTHDAY=1`.
- Sharing between machines and people: `python3 tools/tasks.py sync` commits,
  pulls and pushes. Agents run it at the start and end of their work. On a phone,
  use Obsidian Sync, or the Obsidian Git plugin against the same private repository.

## Updating

```sh
python3 setup.py update                       # if you cloned the template (Option B)
python3 setup.py update --from <template-url> # the first time, for Option A
```

Updates replace only the template's own files: `AGENTS.md`, `tools/`, `Views/`,
`Templates/`, `skill/`, `setup.py` and the docs. Your tasks, people, projects and
Obsidian settings are never touched. Each update is a single commit, so
`git revert HEAD` undoes it.

## Layout

```
AGENTS.md          rules for every AI agent (CLAUDE.md, GEMINI.md point here)
Tasks/             one file per task
Archive/<year>/    closed tasks older than 30 days
People/  Projects/ one note per person / project or area
Views/             board, calendar and list definitions (Obsidian Bases)
Templates/Task.md  what a task file looks like
tools/tasks.py     list, new, set, done, log, lint, archive, sync
skill/SKILL.md     the skill that setup installs for agents
setup.py           init, connect, update
```
