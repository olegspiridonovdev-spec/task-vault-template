# Task Vault

A shared task board for daily tasks and home management: tasks split between
people and projects, shown as a **Kanban board**, a **calendar** and **lists**,
with a **journal** (one page per day), **notes** and **lists** (films, books …)
next to them, and managed together with any AI agent: Claude Code, OpenAI Codex, OpenCode,
Gemini CLI, Grok Build, Hermes, OpenClaw, or anything else that can read files and run a
command.

Every task, journal page, note and list is one Markdown file. There is no
database and no server, and git keeps the history. Each person or household
keeps their own vault in a **private** repository.

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
   [Obsidian](#obsidian-the-board-and-calendar).

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
[Obsidian](#obsidian-the-board-and-calendar).

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

3. Open the folder in Obsidian (see [Obsidian](#obsidian-the-board-and-calendar)).
   The plugin and its settings come with the repository.

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

## Obsidian (the board and calendar)

The vault comes with Obsidian already set up: the **TaskNotes** plugin (4.18.2),
its settings and the **Bases** core plugin are in `.obsidian/`. You only open it:

1. Install Obsidian 1.12 or newer from <https://obsidian.md>.
2. **Open folder as vault** → choose the vault folder (`~/Tasks`).
3. Obsidian asks **"Do you trust the author of this vault?"**. Choose to trust
   the author and enable plugins: the only plugin is TaskNotes, copied from the
   official community list. If you picked restricted mode by mistake, turn it off
   in **Settings → Community plugins**.
4. Open `Views/Board.base`. TaskNotes' ribbon buttons and commands (Kanban,
   Tasks, Calendar, Agenda) open the vault's own views in `Views/`.

The settings that come with it:

| TaskNotes setting | Value |
|---|---|
| Tasks folder / archive folder | `Tasks` / `Archive` |
| Task detection | tag `task`; `Templates/` is excluded |
| File name | the task title |
| Statuses | `inbox`, `todo`, `in-progress`, `waiting`, `done` (completed), `cancelled` (completed); default `inbox` |
| Priorities | `none`, `low`, `normal`, `high`; default `normal` |
| Custom fields | `assignee`, `waiting_on` (text) |
| New tasks | not scheduled automatically |

Obsidian's own **Daily notes** plugin is set up for the journal: its calendar
button (or the command *Daily notes: Open today's daily note*) opens
`Journal/<year>/<date>.md`, made from `Templates/Journal.md`. For a new note in
`Notes/`, create the file and use *Templates: Insert template* → `Note`.

Settings and plugins sync with the vault, so a change made on one machine
reaches everyone at the next `sync`. Each person's theme (`appearance.json`) and
window layout stay on their own machine. TaskNotes updates through
**Settings → Community plugins → Check for updates**, and that update syncs too.

## Views

| File | Views |
|---|---|
| `Views/Board.base` | **By status** (columns = status, a row per person), **By person**, **By project** |
| `Views/Calendar.base` | **Month**, **Week**, **Agenda** (open tasks), **Completed** (done tasks on their completion date) |
| `Views/Lists.base` | **Today**, **Overdue**, **Next 7 days**, **Inbox**, **Waiting**, **Done this week**, **Done (all)** |
| `Views/Notes.base` | **Recent notes**, **Journal** (newest day first), **Lists** |
| `Views/Day.base` | embedded at the top of every journal page: that day's tasks (planned, due, finished) and the notes written that day |

Dragging a card on the board changes the task's `status` in its file, so agents
see it immediately. Finishing a recurring task (in Obsidian or with
`tasks.py done`) ticks that occurrence and moves it to the next date.

## Everyday use

- Ask your agent: *"add 'buy filters' for Anna on Friday"*, *"what's on today?"*,
  *"Max fixed the tap"*, *"weekly review"*, *"the tap needs the washer first"*,
  *"note on the tap: valve is 3/4 inch"*, *"what's the story with the tap?"*.
- Each task keeps its own story: a description, **Notes** (details and comments,
  also after it's done) and a dated **Log** of everything that happened. Tasks
  can be **blocked by** others (TaskNotes shows the dependency, `list --ready`
  hides them until unblocked), be **subtasks** of a bigger task, or link to
  **related** tasks. `python3 tools/tasks.py show "<task>"` prints all of it.
- **Journal, notes and lists** for everything that isn't a task: *"write in
  today's journal: we decided to switch the boiler company"*, *"remember: the
  router password is on the box"*, *"add Dune to my films"*, *"I watched Dune,
  8/10"*, *"what's left on my book list?"*, *"what happened on 10 November?"*,
  *"what did I write about the boiler?"*.

  | What | Where | Command |
  |---|---|---|
  | what happened, conclusions, memories of a day | `Journal/2026/2026-11-14.md` | `journal -m "..."` (`--date`, `--by`) |
  | things to keep, not tied to a day | `Notes/Wi-Fi setup.md` | `memo "Wi-Fi setup" -m "..."` |
  | collections to come back to | `Lists/Films.md`: `- [ ] Dune — why (added …)` | `add Films "Dune"`, `check Films dune -m "8/10"`, `lists` |
  | a day at a glance | journal page, tasks, notes, list items of that day | `journal --date 2026-11-10` |
  | search everything | tasks, archive, journal, notes, lists, projects | `find boiler` |

  Two machines adding to the same day, note or list both keep their lines.
- Or in Obsidian: the TaskNotes command **Create new task**, or drag cards on the board.
- Or in a terminal: `python3 tools/tasks.py --help`.
- New person: a note in `People/`. New project or area: a note in `Projects/`.
- Repeating chores and bills: set `recurrence`, e.g. `FREQ=WEEKLY;BYDAY=SA` or
  `FREQ=MONTHLY;BYMONTHDAY=1`.
- Sharing between machines and people: `python3 tools/tasks.py sync` commits,
  pulls and pushes. Agents run it at the start and end of their work. If two
  machines changed the same task, sync merges it field by field (the newer edit
  wins a clash, and the other value goes into the task's log).
- Privacy: `sync` refuses to push to a **public** GitHub repository, so tasks
  can't leak by a wrong visibility setting. On a phone,
  use Obsidian Sync, or the Obsidian Git plugin against the same private repository.

## Updating

Improvements to the template (new commands, rules, views) reach your vault in
one step on **one** machine. The other machines follow on their own.

```sh
python3 setup.py update --check     # what's new (versions, changed files, changelog)
python3 setup.py update             # take it: commits "Update template A -> B" and pushes
```

- When an update is out, every `python3 tools/tasks.py sync` prints
  *"template update available"*. Agents run `sync` at the start of a session,
  so they tell you. You can also ask an agent: *"update the task vault"*.
- **Other machines and people need nothing**: their next `sync` pulls the
  update and refreshes their agent skills.
- Updates replace only the files listed in `.template-files` (rules, tools,
  views, templates, setup, docs). Tasks, people, projects, the journal, notes,
  lists and Obsidian settings are never touched; the one exception is that an
  update adds an Obsidian settings file a new feature needs if you don't have
  it (1.3.0: `.obsidian/daily-notes.json`). A template file you edited yourself is kept if the
  template drops it.
- Each update is one commit; `git revert HEAD` undoes it.
- **Vault made with "Use this template" on GitHub (2A)?** It has no link to the
  template yet. Run this once and plain `update` works from then on:
  `python3 setup.py update --from https://github.com/olegspiridonovdev-spec/task-vault-template.git`

## Layout

```
AGENTS.md          rules for every AI agent (CLAUDE.md, GEMINI.md point here)
Tasks/             one file per task
Archive/<year>/    closed tasks older than 30 days
People/  Projects/ one note per person / project or area
Journal/<year>/    one page per day: Journal/2026/2026-11-14.md
Notes/             one note per topic
Lists/             one checklist per list (Films.md, Books.md …)
Views/             board, calendar, list, notes and day views (Obsidian Bases)
Templates/         what a task, journal page and note look like
tools/tasks.py     tasks (list, new, set, done, note, show, link …), journal, memo,
                   add, check, lists, find, lint, archive, sync
skill/SKILL.md     the skill that setup installs for agents
setup.py           init, connect, update
.template-files    what `update` may replace (everything else is yours)
CHANGELOG.md       what each template version changed
.obsidian/          Obsidian settings and the TaskNotes plugin
LICENSE, NOTICE    MIT; NOTICE covers the bundled TaskNotes plugin
```
