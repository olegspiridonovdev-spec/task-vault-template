# Task Vault

A shared task board for daily tasks and home management: tasks split between
people and projects, shown as a **Kanban board**, a **calendar** and **lists**,
and managed together with any AI agent: Claude Code, OpenAI Codex, OpenCode,
Gemini CLI, Grok Build, Hermes, OpenClaw, or anything else that can read files and run a
command.

Every task is one Markdown file. There is no database and no server, and git
keeps the history. Each person or household keeps their own vault in a
**private** repository.

## Install

Pick the case that fits:

| You want to… | Go to |
|---|---|
| start a new vault for yourself or your household | [1. Prerequisites](#1-prerequisites), then [2A](#2a-new-vault-on-github-web) or [2B](#2b-new-vault-from-the-command-line) |
| use a vault on another computer of yours | [3. Another machine](#3-another-machine-or-another-person) |
| join a vault someone else created | [3. Another person](#3-another-machine-or-another-person) |
| connect an AI agent | [Connecting AI agents](#connecting-ai-agents) |

### 1. Prerequisites

You need **git** and **Python 3.9+**. The GitHub CLI (`gh`) is optional. Setup
uses it to create your private repository, and it saves you from typing passwords
when you push.

| System | Install |
|---|---|
| macOS | `xcode-select --install` (git and Python), then optionally `brew install gh` |
| Windows | `winget install Git.Git`, `winget install Python.Python.3.13`, optionally `winget install GitHub.cli`; open a new terminal afterwards |
| Ubuntu / Debian | `sudo apt install git python3 gh` |

Then, once per machine:

```sh
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
gh auth login            # only if you use gh
```

On **Windows**, type `python` wherever this README says `python3`.

### 2A. New vault on GitHub (web)

1. Open <https://github.com/olegspiridonovdev-spec/task-vault-template>, click
   **Use this template → Create a new repository**, give it a name, and choose
   **Private**. Your tasks will live there, so it must be private.
2. Clone your new repository and run setup in it:

   ```sh
   git clone https://github.com/<you>/<your-vault>.git ~/Tasks
   cd ~/Tasks
   python3 setup.py
   ```

   Setup asks for the people's names and whether the remote is your own vault
   repository. Answer **y** to that question.
3. Continue with [Connecting AI agents](#connecting-ai-agents) and
   [One-time Obsidian setup](#one-time-obsidian-setup-for-the-board-and-calendar).

### 2B. New vault from the command line

```sh
git clone https://github.com/olegspiridonovdev-spec/task-vault-template.git ~/Tasks
cd ~/Tasks
python3 setup.py init --people "Anna,Max" --private-repo my-tasks
```

`--private-repo` creates a private GitHub repository through `gh` and pushes the
vault to it. With another host (GitLab, Bitbucket, Gitea), create an empty
private repository there and pass `--remote <its git url>` instead. Without
either option, the vault stays on this machine only, and you can add a remote later.

Then continue with [Connecting AI agents](#connecting-ai-agents) and
[One-time Obsidian setup](#one-time-obsidian-setup-for-the-board-and-calendar).

#### What setup does

1. Removes the example tasks and adds a note in `People/` for each name you give.
2. Makes the folder a git repository with a first commit. If you cloned the
   template, its remote is renamed `template` so that updates can come from it.
3. Removes the template's test workflow, so syncing doesn't use your GitHub Actions minutes.
4. Connects the AI agents it finds on this machine (see below).
5. Creates the private repository and pushes to it, if you asked for one.

### 3. Another machine or another person

The vault is just your private repository, so every other machine and person
clones that repository, **not the template**.

1. **Another person only:** the owner adds them on GitHub (the repository →
   **Settings → Collaborators → Add people**), and they accept the invitation.
   The owner also adds a note for them: `People/<Name>.md` (copy an existing one).
2. On the new machine, do [1. Prerequisites](#1-prerequisites), then:

   ```sh
   git clone https://github.com/<owner>/<vault>.git ~/Tasks
   cd ~/Tasks
   python3 setup.py connect
   ```

3. Open the folder in Obsidian. The plugins and settings come with the
   repository; approve the community plugins once when Obsidian asks.

Everyone shares changes with `python3 tools/tasks.py sync`, and agents run it themselves.

## Connecting AI agents

An agent finds the vault in one of two ways, and setup arranges both:

- **Started inside the vault folder**, an agent reads the rules in `AGENTS.md`.
  `CLAUDE.md` and `GEMINI.md` point Claude Code and Gemini CLI to that file;
  Codex, OpenCode and Grok Build read it directly.
- **Started anywhere else** (a personal assistant such as OpenClaw or Hermes, or
  a coding agent in another project), the agent finds the vault through a
  `task-vault` skill. The skill holds the vault's full path and the commands to use.

### Step by step

1. **Install your agents first**, then run, in the vault folder:

   ```sh
   python3 setup.py connect
   ```

   It detects the agents on this machine and installs the skill for each:

   | Agent | Skill installed to | First start inside the vault |
   |---|---|---|
   | Claude Code | `~/.claude/skills/task-vault/` | trust the folder when asked |
   | OpenAI Codex | `~/.agents/skills/task-vault/` | trust the folder when asked |
   | OpenCode | `~/.agents/skills/task-vault/` | nothing |
   | Gemini CLI | `~/.agents/skills/task-vault/` | trust the folder if asked |
   | Grok Build | `~/.agents/skills/task-vault/` | run `grok --trust` once in the vault, or accept the trust prompt. Until then Grok ignores `AGENTS.md` there |
   | OpenClaw | `~/.agents/skills/task-vault/` | runs from its own folder and uses the skill |
   | Hermes | `~/.hermes/skills/task-vault/` | runs from its own folder and uses the skill |

   Codex, OpenCode, Gemini CLI, Grok Build and OpenClaw share one folder, so one copy
   serves them all. On Windows the folders are the same, under `%USERPROFILE%`.

2. **Restart** any agent that was running, since agents read skills at start.
3. **Check it**: start the agent in your home folder, not the vault, and ask
   *"What's on the task board today?"*. It should run
   `tools/tasks.py list --when today` from your vault. For Grok Build,
   `grok inspect` lists `task-vault` under **Skills**. Run inside the vault, after
   trusting it, it also lists `AGENTS.md` under **Project Instructions**.

### Options

```sh
python3 setup.py connect                      # agents detected on this machine
python3 setup.py connect --agents all         # every location above, installed or not
python3 setup.py connect --agents grok,hermes # only these
python3 setup.py connect --remove             # uninstall the skill
python3 setup.py connect --force              # replace a skill that points to another vault
```

Agent names for `--agents`: `claude`, `codex`, `opencode`, `gemini`, `grok`,
`openclaw`, `hermes`.

Run `connect` again when:

- you **install another agent** later;
- you **move or rename the vault folder** (add `--force`, because the old skill
  still points to the old path).

`python3 setup.py update` refreshes the installed skills by itself.

### Any other agent

Give it this one instruction: *"Read `<path to vault>/AGENTS.md` and manage
tasks only through `python3 <path to vault>/tools/tasks.py`."* The tool prints
short, one-line answers, so an agent spends few tokens per question.

### Troubleshooting

| Symptom | Fix |
|---|---|
| The agent doesn't know about the vault | restart it; check the skill file exists in the folder from the table; run `connect --agents <name>` |
| Grok ignores the rules inside the vault | `grok --trust` in the vault; check with `grok inspect` |
| `skipped …: belongs to another vault` | the skill points to another vault folder; use `connect --force` if this one should win |
| `sync` asks for a password or is rejected | run `gh auth login`, or ask the owner to add you as a collaborator |
| `python3` not found on Windows | use `python` |

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
python3 setup.py update                       # if you cloned the template (2B)
python3 setup.py update --from https://github.com/olegspiridonovdev-spec/task-vault-template.git  # first time, for 2A
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
