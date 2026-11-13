# Changelog

`python3 setup.py update --check` shows the entries newer than your vault.

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
