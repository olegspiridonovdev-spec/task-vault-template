#!/usr/bin/env python3
"""Set up a task vault, connect AI agents to it, and update it from the template.

    python3 setup.py                     first-time setup, asks what it needs
    python3 setup.py init --people "Anna,Max" --private-repo my-tasks
    python3 setup.py connect [--agents all|claude,codex,opencode,gemini,grok,openclaw,hermes] [--remove]
    python3 setup.py update [--from <template git url>]

Standard library only; needs git. `python` instead of `python3` on Windows.
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
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
MARKER = ROOT / ".task-vault.json"
SKILL_NAME = "task-vault"

# What the template owns. `update` replaces exactly these; everything else -
# Tasks, Archive, People, Projects, .obsidian - belongs to the person.
FRAMEWORK = ["AGENTS.md", "CLAUDE.md", "GEMINI.md", "README.md", "VERSION", "setup.py",
             ".gitignore", ".gitattributes", "tools", "Views", "Templates", "skill", "tests"]

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


def gh_ready() -> bool:
    return (shutil.which("gh") is not None
            and subprocess.run(["gh", "auth", "status"], capture_output=True).returncode == 0)


# --- init -------------------------------------------------------------------

def cmd_init(args) -> None:
    if shutil.which("git") is None:
        sys.exit("git is required: install it and run setup again")
    first_time = not MARKER.exists()

    if first_time and not args.keep_examples:
        removed = [p for folder in ("Tasks", "People", "Projects")
                   for p in (ROOT / folder).glob("*.md") if is_example(p)]
        for path in removed:
            path.unlink()
        if removed:
            say(f"removed {len(removed)} example file(s)")
        # The template's CI is for the template. In a vault it would run the
        # test matrix on every `sync` push and spend the owner's Actions minutes.
        shutil.rmtree(ROOT / ".github", ignore_errors=True)

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
        MARKER.write_text(json.dumps({"created": dt.date.today().isoformat(),
                                      "template_version": VERSION}, indent=2) + "\n",
                          encoding="utf-8")
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

    say()
    say(f"Vault ready: {ROOT}")
    say("Next: open this folder in Obsidian and follow 'One-time Obsidian setup' in README.md.")


def setup_remote(args) -> None:
    if "origin" in remotes():
        say(f"remote origin: {remotes()['origin']}")
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
        branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        git("push", "-q", "-u", "origin", branch, check=True)
        say(f"pushed to {url}")
    else:
        say("no remote: the vault is local only (add one later with --remote or --private-repo)")


# --- connect ----------------------------------------------------------------

def pick_targets(spec: str) -> list[str]:
    home = Path.home()
    if spec == "all":
        return list(TARGETS)
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


def cmd_connect(args) -> None:
    connect(args.agents, remove=args.remove, force=args.force)


# --- update -----------------------------------------------------------------

def cmd_update(args) -> None:
    if git("status", "--porcelain").stdout.strip():
        sys.exit("the vault has uncommitted changes; run `python3 tools/tasks.py sync` first")
    if args.from_url:
        if "template" in remotes():
            git("remote", "set-url", "template", args.from_url, check=True)
        else:
            git("remote", "add", "template", args.from_url, check=True)
    if "template" not in remotes():
        sys.exit("no 'template' remote; run `python3 setup.py update --from <template git url>`")
    git("fetch", "-q", "template", check=True)
    head = git("ls-remote", "--symref", "template", "HEAD").stdout
    match = re.search(r"refs/heads/(\S+)\s+HEAD", head)
    ref = f"template/{match.group(1) if match else 'main'}"
    paths = [p for p in FRAMEWORK if git("cat-file", "-e", f"{ref}:{p}").returncode == 0]
    git("checkout", ref, "--", *paths, check=True)
    new_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    git("add", "-A")
    if git("diff", "--cached", "--quiet").returncode == 0:
        say(f"already up to date (template {new_version})")
        return
    changed = git("diff", "--cached", "--name-only").stdout.split()
    git("commit", "-q", "-m", f"Update template {VERSION} -> {new_version}", check=True)
    say(f"updated template {VERSION} -> {new_version}: {len(changed)} file(s) changed")
    for name in changed:
        say(f"  {name}")
    # Refresh the skills that already point at this vault; the text may have changed.
    for key, target in TARGETS.items():
        path = Path.home() / target["dir"] / SKILL_NAME / "SKILL.md"
        if path.exists() and str(ROOT) in path.read_text(encoding="utf-8"):
            subprocess.run([sys.executable, str(ROOT / "setup.py"), "connect", "--agents",
                            {"claude": "claude", "shared": "codex", "hermes": "hermes"}[key]])
    say("review with `git show`, undo with `git revert HEAD`")


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
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("connect", help="install the task-vault skill for AI agents")
    p.add_argument("--agents", default="auto", help="auto (default), all, or a list")
    p.add_argument("--remove", action="store_true", help="uninstall it instead")
    p.add_argument("--force", action="store_true", help="overwrite another vault's skill")
    p.set_defaults(func=cmd_connect)

    p = sub.add_parser("update", help="take the newest template; tasks are untouched")
    p.add_argument("--from", dest="from_url", metavar="URL", help="template repository URL")
    p.set_defaults(func=cmd_update)

    argv = sys.argv[1:] or ["init"]
    if argv[0].startswith("-") and argv[0] not in ("-h", "--help"):
        argv = ["init", *argv]
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
