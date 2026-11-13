---
name: task-vault
description: Manage the shared task board (Kanban and calendar of daily tasks, chores, errands, bills and home management) stored in {{VAULT}}. Use when the user asks to add, find, assign, schedule, update, complete or cancel a task, asks what is due today or this week or who is doing what, or wants a morning summary or weekly review.
---

# Task vault

The task board is a folder of Markdown files at `{{VAULT}}`, one file per task,
viewed by people in Obsidian. The full rules are in `{{VAULT}}/AGENTS.md`; read
them before your first change in a session.

Always go through the vault's own tool (it works from any directory):

```sh
{{PYTHON}} "{{VAULT}}/tools/tasks.py" sync                         # first: get others' changes
{{PYTHON}} "{{VAULT}}/tools/tasks.py" list --when today            # or: week, overdue
{{PYTHON}} "{{VAULT}}/tools/tasks.py" list --assignee Anna --project Home
{{PYTHON}} "{{VAULT}}/tools/tasks.py" new "Title" --assignee Anna --project Home --scheduled YYYY-MM-DD
{{PYTHON}} "{{VAULT}}/tools/tasks.py" set "Title" status=waiting waiting_on="..." -m "why"
{{PYTHON}} "{{VAULT}}/tools/tasks.py" done "Title" -m "what was done"
{{PYTHON}} "{{VAULT}}/tools/tasks.py" lint
{{PYTHON}} "{{VAULT}}/tools/tasks.py" sync -m "what changed"       # last: commit and share
```

Statuses: `inbox`, `todo`, `in-progress`, `waiting`, `done`, `cancelled`.
People are the notes in `{{VAULT}}/People/`, projects the notes in `{{VAULT}}/Projects/`.
Never delete a task file; cancel it instead.
