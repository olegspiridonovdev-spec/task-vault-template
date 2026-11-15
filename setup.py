#!/usr/bin/env python3
"""Set up a task vault, connect AI agents to it, and update it from the template.

    python3 setup.py                     first-time setup, asks what it needs
    python3 setup.py init --people "Anna,Max" --private-repo my-tasks
    python3 setup.py connect [--agents all|claude,codex,opencode,gemini,grok,openclaw,hermes] [--remove]
    python3 setup.py update [--check] [--from <template git url>]

init, connect and update also schedule tools/autosync.py on this machine (a sync every
5 minutes and after every reboot); `--no-autosync` skips it. Standard library only; needs git. `python` instead of `python3` on Windows.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
MARKER = ROOT / ".task-vault.json"
SKILL_NAME = "task-vault"

# What the template owns is listed in .template-files. `update` replaces exactly
# those; everything else - Tasks, Archive, People, Projects, Journal, Notes,
# Lists, .obsidian - belongs to the person. The fallback is for a vault whose manifest went missing.
MANIFEST = ".template-files"
# Folders where the template keeps example files (`example: true`); init removes them.
EXAMPLE_FOLDERS = ("Tasks", "People", "Projects", "Journal", "Notes", "Lists")
# Obsidian settings a vault needs for a feature. `.obsidian/` is the person's, so
# update only adds one of these when it is missing and never overwrites it.
OBSIDIAN_DEFAULTS = (".obsidian/daily-notes.json",)
FALLBACK_FRAMEWORK = ["AGENTS.md", "CLAUDE.md", "GEMINI.md", "README.md", "VERSION", "setup.py",
                      ".gitignore", ".gitattributes", "tools", "Views", "Templates", "skill",
                      "tests"]


def parse_manifest(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]

# Where each agent looks for user-level skills (agentskills.io format). One
# shared directory, ~/.agents/skills, is read by Codex, OpenCode, Gemini CLI,
# Grok Build and OpenClaw; Claude Code and Hermes each read only their own.
TARGETS = {
    "claude": {"label": "Claude Code", "dir": ".claude/skills",
               "bins": ["claude"], "homes": [".claude"]},
    "shared": {"label": "Codex, OpenCode, Gemini CLI, Grok Build, OpenClaw", "dir": ".agents/skills",
               "bins": ["codex", "opencode", "gemini", "grok", "openclaw"],
               "homes": [".codex", ".config/opencode", ".gemini", ".grok", ".openclaw",
                         ".agents"]},
    "hermes": {"label": "Hermes", "dir": ".hermes/skills",
               "bins": ["hermes"], "homes": [".hermes"]},
}
AGENT_NAMES = {"claude": "claude", "claude-code": "claude", "hermes": "hermes",
               "codex": "shared", "openai": "shared", "opencode": "shared",
               "gemini": "shared", "grok": "shared", "grok-build": "shared",
               "openclaw": "shared"}
PYTHON = "python" if os.name == "nt" else "python3"


# --- helpers ----------------------------------------------------------------

def say(message: str = "") -> None:
    print(message, flush=True)


def git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{(result.stderr or result.stdout).strip()}")
    return result


def interactive(args) -> bool:
    return not getattr(args, "yes", False) and sys.stdin.isatty()


def ask(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{question}{suffix}: ").strip()
    return answer or default


def confirm(question: str, default: bool = True) -> bool:
    answer = input(f"{question} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not answer else answer.startswith("y")


def is_example(path: Path) -> bool:
    head = path.read_text(encoding="utf-8").split("\n---", 1)[0]
    return re.search(r"^example:\s*true\s*$", head, flags=re.M) is not None


def remotes() -> dict[str, str]:
    out = {}
    for line in git("remote", "-v").stdout.splitlines():
        name, url, *_ = line.split()
        out[name] = url
    return out


def read_marker() -> dict:
    try:
        return json.loads(MARKER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_marker(data: dict) -> None:
    MARKER.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def gh_ready() -> bool:
    return (shutil.which("gh") is not None
            and subprocess.run(["gh", "auth", "status"], capture_output=True).returncode == 0)


# --- init -------------------------------------------------------------------

def cmd_init(args) -> None:
    if shutil.which("git") is None:
        sys.exit("git is required: install it and run setup again")
    first_time = not MARKER.exists()

    if first_time and not args.keep_examples:
        removed = [p for folder in EXAMPLE_FOLDERS
                   for p in sorted((ROOT / folder).rglob("*.md")) if is_example(p)]
        for path in removed:
            path.unlink()
            if path.parent != ROOT / path.relative_to(ROOT).parts[0] and \
                    not any(path.parent.iterdir()):
                path.parent.rmdir()  # e.g. Journal/2026/ once its example page is gone
        if removed:
            say(f"removed {len(removed)} example file(s)")
        # The template's CI is for the template. In a vault it would run the
        # test matrix on every `sync` push and spend the owner's Actions minutes.
        shutil.rmtree(ROOT / ".github", ignore_errors=True)
        (ROOT / "MAINTAINING.md").unlink(missing_ok=True)  # for template developers only

    people = [p.strip() for p in (args.people or "").split(",") if p.strip()]
    if not people and not list((ROOT / "People").glob("*.md")) and interactive(args):
        people = [p.strip() for p in ask("Who will get tasks? Names, comma-separated").split(",")
                  if p.strip()]
    for name in people:
        safe = re.sub(r'[\\/:*?"<>|#^]', "", name)  # not inside the f-string: py<3.12
        note = ROOT / "People" / f"{safe}.md"
        if not note.exists():
            note.parent.mkdir(exist_ok=True)
            note.write_text(f"---\ntype: person\n---\n\n# {name}\n", encoding="utf-8")
            say(f"added People/{note.name}")

    # Git. A vault cloned straight from the template still has the template as
    # `origin`; it becomes `template` (for updates) and origin is left free
    # for the person's own private repository.
    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        git("init", "-q", "-b", "main", check=True)
        say("created a git repository")
    origin = remotes().get("origin")
    if origin and "template" not in remotes():
        cloned_template = bool(args.private_repo or args.remote)
        if not cloned_template and interactive(args):
            cloned_template = not confirm(f"Is {origin} your own private vault repository?"
                                          " (answer n if it is the template you cloned)")
        if cloned_template:
            git("remote", "rename", "origin", "template", check=True)
            say(f"the template remote is now 'template' ({origin})")

    if first_time:
        marker = {"created": dt.date.today().isoformat(), "template_version": VERSION}
        if "template" in remotes():
            # Cloned from the template: HEAD is the template commit we started from.
            # `update` uses it to tell files the template dropped from your own.
            marker["template_commit"] = git("rev-parse", "HEAD").stdout.strip()
        write_marker(marker)
    git("add", "-A")
    if git("diff", "--cached", "--quiet").returncode != 0:
        result = git("commit", "-q", "-m", "Set up task vault")
        if result.returncode != 0:
            sys.exit("could not commit; set your git identity first:\n"
                     '  git config --global user.name "Your Name"\n'
                     '  git config --global user.email "you@example.com"\n'
                     + (result.stderr or result.stdout).strip())
        say("committed the vault")

    if args.agents != "none":
        connect(args.agents, remove=False, force=args.force)

    setup_remote(args)
    ensure_autosync(not args.no_autosync)

    say()
    say(f"Vault ready: {ROOT}")
    say("Next: open this folder in Obsidian (Open folder as vault); TaskNotes is already set up.")


def sync_or_exit() -> None:
    """Push through `tasks.py sync`, which refuses a public GitHub repository."""
    result = subprocess.run([sys.executable, str(ROOT / "tools" / "tasks.py"), "sync",
                             "-m", "Set up task vault"], capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit((result.stderr or result.stdout).strip())


def setup_remote(args) -> None:
    if "origin" in remotes():
        say(f"remote origin: {remotes()['origin']}")
        sync_or_exit()
        return
    name, url = args.private_repo, args.remote
    if not name and not url and interactive(args):
        if gh_ready() and confirm("Create a private GitHub repository for this vault now?"):
            name = ask("Repository name", ROOT.name.lower())
        else:
            url = ask("Git URL of an empty private repository to push to (Enter to skip)")
    if name:
        if not gh_ready():
            sys.exit("--private-repo needs the GitHub CLI, signed in: install `gh`, run "
                     "`gh auth login`, then `python3 setup.py init --private-repo "
                     f"{name}`. Or create an empty private repository yourself and pass --remote URL.")
        result = subprocess.run(["gh", "repo", "create", name, "--private", "--source", str(ROOT),
                                 "--remote", "origin", "--push"], capture_output=True, text=True)
        if result.returncode != 0:
            sys.exit("gh repo create failed:\n" + (result.stderr or result.stdout).strip())
        say(f"created private repository {name} and pushed")
    elif url:
        git("remote", "add", "origin", url, check=True)
        sync_or_exit()
        say(f"pushed to {url}")
    else:
        say("no remote: the vault is local only (add one later with --remote or --private-repo)")


# --- connect ----------------------------------------------------------------

def pick_targets(spec: str) -> list[str]:
    home = Path.home()
    if spec == "all":
        return list(TARGETS)
    if spec == "installed":  # skills already pointing at this vault, to refresh them
        return [key for key, t in TARGETS.items()
                if (path := Path.home() / t["dir"] / SKILL_NAME / "SKILL.md").exists()
                and str(ROOT) in path.read_text(encoding="utf-8")]
    if spec == "auto":
        return [key for key, t in TARGETS.items()
                if any(shutil.which(b) for b in t["bins"])
                or any((home / h).is_dir() for h in t["homes"])]
    picked = []
    for name in spec.split(","):
        key = AGENT_NAMES.get(name.strip().lower())
        if key is None:
            sys.exit(f"unknown agent {name!r}; known: {', '.join(sorted(AGENT_NAMES))}, all, auto")
        if key not in picked:
            picked.append(key)
    return picked


def skill_text() -> str:
    text = (ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8")
    return text.replace("{{VAULT}}", str(ROOT)).replace("{{PYTHON}}", PYTHON)


def connect(spec: str, remove: bool, force: bool) -> None:
    keys = pick_targets(spec)
    if not keys and spec == "installed":
        return
    if not keys:
        say("no AI agents found on this machine; run `python3 setup.py connect --agents all` "
            "to install the skill anyway")
        return
    for key in keys:
        target = TARGETS[key]
        folder = Path.home() / target["dir"] / SKILL_NAME
        path = folder / "SKILL.md"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        ours = not existing or str(ROOT) in existing
        if remove:
            if existing and ours:
                shutil.rmtree(folder)
                say(f"disconnected {target['label']}")
            continue
        if not ours and not force:
            say(f"skipped {target['label']}: {path} belongs to another vault (use --force)")
            continue
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(skill_text(), encoding="utf-8")
        say(f"connected {target['label']}  ->  {path}")
    if not remove and "shared" in keys and (shutil.which("grok") or (Path.home() / ".grok").is_dir()):
        # Grok Build reads a folder's AGENTS.md only after the folder is trusted.
        say(f"Grok Build: run `grok --trust` once in {ROOT} so it reads AGENTS.md there")


def ensure_autosync(wanted: bool = True) -> None:
    """Schedule tools/autosync.py on this machine (a sync every 5 minutes and after every
    reboot), unless this machine turned it off with `autosync.py uninstall`."""
    script = ROOT / "tools" / "autosync.py"
    if wanted and script.exists():
        subprocess.run([sys.executable, str(script), "ensure"])


def cmd_connect(args) -> None:
    connect(args.agents, remove=args.remove, force=args.force)
    if not args.remove:
        ensure_autosync(not args.no_autosync)


# --- update -----------------------------------------------------------------

RELEASE_TAG = re.compile(r"v\d+\.\d+\.\d+")


def template_ref() -> str:
    """The newest release (tag vX.Y.Z) of the template, or its main branch if it
    has no releases. Unreleased work on main never reaches vaults."""
    git("fetch", "-q", "--no-tags", "template", check=True)
    git("fetch", "-q", "--no-tags", "template",
        "+refs/tags/v*:refs/remotes/template/releases/v*")
    tags = git("for-each-ref", "--format=%(refname)", "refs/remotes/template/releases/").stdout
    releases = [t for t in tags.split() if RELEASE_TAG.fullmatch(t.rsplit("/", 1)[1])]
    if releases:
        return max(releases, key=lambda t: version_key(t.rsplit("/", 1)[1]))
    head = git("ls-remote", "--symref", "template", "HEAD").stdout
    match = re.search(r"refs/heads/(\S+)\s+HEAD", head)
    return f"template/{match.group(1) if match else 'main'}"


def show(ref: str, path: str) -> str | None:
    result = git("show", f"{ref}:{path}")
    return result.stdout if result.returncode == 0 else None


def framework_at(ref: str) -> list[str]:
    text = show(ref, MANIFEST)
    return parse_manifest(text) if text is not None else FALLBACK_FRAMEWORK


def version_key(text: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", text)[:3])


def changelog_since(ref: str, current: str) -> list[str]:
    """CHANGELOG.md sections at `ref` newer than `current`."""
    lines, keep = [], False
    for line in (show(ref, "CHANGELOG.md") or "").splitlines():
        heading = re.match(r"##\s+\[?(\d+\.\d+\.\d+)", line)
        if heading:
            keep = version_key(heading.group(1)) > version_key(current)
        if keep:
            lines.append(line)
    return lines


def blob(ref: str, name: str) -> str | None:
    result = git("rev-parse", "-q", "--verify", f"{ref}:{name}")
    return result.stdout.strip() if result.returncode == 0 else None


def take_template_files(ref: str, paths: list[str], base: str | None) -> None:
    """Bring the template's files at `ref`, file by file, without losing the vault's own
    edits. `base` is the template commit the vault took last time:

    - you never changed the file (it is as in `base`): the template's version
    - only you changed it (the template didn't since `base`): yours stays
    - both changed it: a three-way merge; if the lines clash, yours stays and you're told

    Without a known `base` (a vault older than the marker), every file is replaced.
    """
    names = git("ls-tree", "-r", "--name-only", ref, "--", *paths).stdout.splitlines()
    take = []
    for name in names:
        path = ROOT / name
        new = blob(ref, name)
        if base is None or not path.is_file() or name == "setup.py":  # setup.py: stage 1
            take.append(name)
            continue
        mine = git("hash-object", "--path", name, str(path)).stdout.strip()  # as git stores it
        old = blob(base, name)
        if mine == new or mine == old:
            take.append(name)
        elif old == new:
            say(f"kept your edit of {name} (the template did not change it)")
        elif old is not None and merge_file(path, base, ref, name):
            say(f"merged your edit of {name} with the template's changes")
        else:
            say(f"kept your version of {name}; the template changed it too. To compare: "
                f"git diff HEAD {ref} -- \"{name}\"")
    for start in range(0, len(take), 100):  # keep each command line short (Windows)
        git("checkout", ref, "--", *take[start:start + 100], check=True)


def merge_file(path: Path, base: str, ref: str, name: str) -> bool:
    """Three-way merge into `path`; False (file untouched) if the changes clash."""
    with tempfile.TemporaryDirectory() as tmp:
        mine, old, new = Path(tmp) / "mine", Path(tmp) / "base", Path(tmp) / "theirs"
        # Your file as git stores it (line endings normalised by .gitattributes), so a
        # CRLF checkout on Windows doesn't make every line look changed.
        stored = git("hash-object", "-w", "--path", name, str(path)).stdout.strip()
        mine.write_bytes(git_bytes("cat-file", "blob", stored))
        old.write_bytes(git_bytes("show", f"{base}:{name}"))
        new.write_bytes(git_bytes("show", f"{ref}:{name}"))
        result = subprocess.run(["git", "merge-file", "-p", str(mine), str(old), str(new)],
                                capture_output=True)
        if result.returncode != 0:  # >0: conflicts, <0: error
            return False
        path.write_bytes(result.stdout)
        return True


def git_bytes(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True).stdout


def cmd_update(args) -> None:
    if args.from_url:
        if "template" in remotes():
            git("remote", "set-url", "template", args.from_url, check=True)
        else:
            git("remote", "add", "template", args.from_url, check=True)
    if "template" not in remotes():
        sys.exit("no 'template' remote; run `python3 setup.py update --from <template git url>`")

    if args.check:
        ref = template_ref()
        new_version = (show(ref, "VERSION") or "?").strip()
        changed = git("diff", "--name-only", "HEAD", ref, "--", *framework_at(ref)).stdout.split()
        if not changed:
            say(f"up to date (template {VERSION})")
            return
        say(f"update available: {VERSION} -> {new_version}, {len(changed)} file(s)")
        for line in changelog_since(ref, VERSION):
            say(f"  {line}")
        say("apply with `python3 setup.py update`")
        return

    if args.stage2 is None:
        # Stage 1, run by the vault's current setup.py: take the template's
        # setup.py first and let it do the rest, so the newest update logic runs.
        if git("status", "--porcelain").stdout.strip():
            sys.exit("the vault has uncommitted changes; run `python3 tools/tasks.py sync` first")
        ref = template_ref()
        if show(ref, "setup.py") is not None:
            git("checkout", ref, "--", "setup.py", check=True)
        result = subprocess.run([sys.executable, str(ROOT / "setup.py"), "update",
                                 "--stage2", ref, "--old-version", VERSION])
        sys.exit(result.returncode)

    ref, old_version = args.stage2, args.old_version or VERSION
    marker = read_marker()
    new_paths = [p for p in framework_at(ref) if git("cat-file", "-e", f"{ref}:{p}").returncode == 0]

    # Files the template had last time but no longer has: remove them, unless
    # you changed them (then they are yours now).
    old = marker.get("template_commit")
    if old and git("cat-file", "-e", f"{old}^{{commit}}").returncode == 0:
        def files(commit: str, paths: list[str]) -> set[str]:
            out = git("ls-tree", "-r", "--name-only", commit, "--", *paths).stdout
            return set(out.splitlines())
        dropped = files(old, framework_at(old)) - files(ref, framework_at(ref))
        for name in sorted(dropped):
            path = ROOT / name
            if not path.is_file():
                continue
            mine = git("hash-object", str(path)).stdout.strip()
            theirs = git("rev-parse", f"{old}:{name}").stdout.strip()
            if mine == theirs:
                path.unlink()
            else:
                say(f"kept {name}: the template dropped it, but you changed it")

    take_template_files(ref, new_paths, old if old and git(
        "cat-file", "-e", f"{old}^{{commit}}").returncode == 0 else None)
    for name in OBSIDIAN_DEFAULTS:
        content = show(ref, name)
        if content is not None and (ROOT / ".obsidian").is_dir() and not (ROOT / name).exists():
            (ROOT / name).write_text(content, encoding="utf-8")
            say(f"added {name} (Obsidian settings for a new feature)")
    new_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    marker["template_commit"] = git("rev-parse", f"{ref}^{{commit}}").stdout.strip()
    marker["template_version"] = new_version
    git("add", "-A")
    changed = git("diff", "--cached", "--name-only", "--", ".", f":!{MARKER.name}").stdout.split()
    if not changed:
        git("reset", "-q")
        say(f"already up to date (template {new_version})")
        return
    write_marker(marker)
    git("add", "-A")
    git("commit", "-q", "-m", f"Update template {old_version} -> {new_version}", check=True)
    say(f"updated template {old_version} -> {new_version}: {len(changed)} file(s) changed")
    for name in changed:
        say(f"  {name}")
    for line in changelog_since(ref, old_version):
        say(f"  {line}")
    connect("installed", remove=False, force=False)  # the skill text may have changed
    ensure_autosync()  # vaults made before 1.4.0 get auto-sync with the update
    if "origin" in remotes():
        # Share it: other machines take it with their next `tasks.py sync`.
        subprocess.run([sys.executable, str(ROOT / "tools" / "tasks.py"), "sync",
                        "-m", f"Update template to {new_version}"])
    say("undo with `git revert HEAD`")


# --- main -------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("init", help="first-time setup (the default)")
    p.add_argument("--people", help='names, comma-separated: "Anna,Max"')
    p.add_argument("--private-repo", metavar="NAME", help="create a private GitHub repo (needs gh)")
    p.add_argument("--remote", metavar="URL", help="push to an existing empty git repository")
    p.add_argument("--agents", default="auto", help="auto (default), all, none, or a list")
    p.add_argument("--keep-examples", action="store_true")
    p.add_argument("--force", action="store_true", help="overwrite another vault's skill")
    p.add_argument("--yes", action="store_true", help="never ask; use flags and defaults")
    p.add_argument("--no-autosync", dest="no_autosync", action="store_true",
                   help="don't schedule the 5-minute auto-sync on this machine")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("connect", help="install the task-vault skill for AI agents, "
                                       "and auto-sync on this machine")
    p.add_argument("--agents", default="auto", help="auto (default), all, or a list")
    p.add_argument("--remove", action="store_true", help="uninstall the skill instead")
    p.add_argument("--force", action="store_true", help="overwrite another vault's skill")
    p.add_argument("--no-autosync", dest="no_autosync", action="store_true",
                   help="don't schedule the 5-minute auto-sync on this machine")
    p.set_defaults(func=cmd_connect)

    p = sub.add_parser("update", help="take the newest template; tasks are untouched")
    p.add_argument("--from", dest="from_url", metavar="URL", help="template repository URL")
    p.add_argument("--check", action="store_true", help="only show what an update would bring")
    p.add_argument("--stage2", metavar="REF", help=argparse.SUPPRESS)
    p.add_argument("--old-version", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_update)

    argv = sys.argv[1:] or ["init"]
    if argv[0].startswith("-") and argv[0] not in ("-h", "--help"):
        argv = ["init", *argv]
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
