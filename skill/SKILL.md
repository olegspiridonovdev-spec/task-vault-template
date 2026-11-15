---
name: task-vault
description: Manage the shared task board (Kanban and calendar of daily tasks, chores, errands, bills and home management) and the journal, notes and lists (films, books to read …) stored in {{VAULT}}. Use when the user asks to add, find, assign, schedule, update, complete or cancel a task, asks what is due today or this week or who is doing what, wants a morning summary or weekly review, or wants to write down, remember or look up a note, a journal entry for a day, or an item on a list.
---

# Task vault

The task board is a folder of Markdown files at `{{VAULT}}`, one file per task,
viewed by people in Obsidian. Next to it: a journal (one page per day), notes
(one per topic) and lists (one checklist per list). The full rules are in
`{{VAULT}}/AGENTS.md`; read them before your first change in a session.

Always go through the vault's own tool (it works from any directory):

```sh
{{PYTHON}} "{{VAULT}}/tools/tasks.py" sync                         # first: get others' changes
{{PYTHON}} "{{VAULT}}/tools/tasks.py" list --when today            # or: week, overdue
{{PYTHON}} "{{VAULT}}/tools/tasks.py" list --assignee Anna --project Home
{{PYTHON}} "{{VAULT}}/tools/tasks.py" new "Title" --assignee Anna --project Home --scheduled YYYY-MM-DD
{{PYTHON}} "{{VAULT}}/tools/tasks.py" set "Title" status=waiting waiting_on="..." -m "why"
{{PYTHON}} "{{VAULT}}/tools/tasks.py" done "Title" -m "what was done"
{{PYTHON}} "{{VAULT}}/tools/tasks.py" show "Title"                     # history, notes, relations
{{PYTHON}} "{{VAULT}}/tools/tasks.py" note "Title" -m "detail or comment"
{{PYTHON}} "{{VAULT}}/tools/tasks.py" link "Title" --blocked-by "Other"   # or --parent, --related
{{PYTHON}} "{{VAULT}}/tools/tasks.py" journal -m "what happened, a conclusion"   # today's page; --date D
{{PYTHON}} "{{VAULT}}/tools/tasks.py" memo "Topic" -m "something to keep"           # a note
{{PYTHON}} "{{VAULT}}/tools/tasks.py" add Films "Title" -m "why"                    # check Films "Title" -m "8/10"
{{PYTHON}} "{{VAULT}}/tools/tasks.py" find "word"                                    # search everything
{{PYTHON}} "{{VAULT}}/tools/tasks.py" lint
{{PYTHON}} "{{VAULT}}/tools/tasks.py" sync -m "what changed"       # last: commit and share
```

Statuses: `inbox`, `todo`, `in-progress`, `waiting`, `done`, `cancelled`.
People are the notes in `{{VAULT}}/People/`, projects the notes in `{{VAULT}}/Projects/`.
Never delete a task file; cancel it instead. A thing to do is a task; a thought or
memory of the day goes in the journal; something to keep goes in a note; a
collection (films, books) goes in a list. AGENTS.md says more.
