"""End-to-end checks: setup, agent connection, the task tool, sync and update.

Each test copies the template into a temporary directory, with its own HOME
(so skills land in a throwaway home, never the real one) and a bare git
repository standing in for the private remote. Run: python3 -m unittest discover tests
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent
IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".task-vault.json", ".obsidian")


class VaultTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        # A PATH holding only git: agent binaries installed next to python or
        # git on the real machine must not leak into detection.
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        git_bin = Path(shutil.which("git"))
        try:
            (bin_dir / git_bin.name).symlink_to(git_bin)
            path = str(bin_dir)
        except OSError:  # Windows without symlink rights
            path = str(git_bin.parent)
        self.env = {
            "HOME": str(self.home), "USERPROFILE": str(self.home),
            "PATH": path, "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        }
        self.vault = self.tmp / "vault"
        shutil.copytree(TEMPLATE, self.vault, ignore=IGNORE)

    def run_in(self, cwd: Path, *cmd: str, ok: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(list(cmd), cwd=str(cwd), env=self.env,
                                capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def setup(self, *args: str, vault: Path | None = None, ok: bool = True):
        vault = vault or self.vault
        return self.run_in(vault, sys.executable, str(vault / "setup.py"), *args, ok=ok)

    def tasks(self, *args: str, vault: Path | None = None, ok: bool = True):
        vault = vault or self.vault
        return self.run_in(self.tmp, sys.executable, str(vault / "tools" / "tasks.py"), *args, ok=ok)

    def bare(self, name: str) -> Path:
        path = self.tmp / f"{name}.git"
        self.run_in(self.tmp, "git", "init", "-q", "--bare", "-b", "main", str(path))
        return path

    def git(self, cwd: Path, *args: str) -> str:
        return self.run_in(cwd, "git", *args).stdout.strip()


class TestSetup(VaultTest):
    def test_init_personalises_commits_and_connects_detected_agents(self) -> None:
        (self.home / ".claude").mkdir()
        (self.home / ".hermes").mkdir()
        self.setup("init", "--people", "Oleg, Maria", "--yes")

        self.assertFalse(list((self.vault / "Tasks").glob("*.md")), "examples are removed")
        self.assertFalse((self.vault / "People" / "Anna.md").exists())
        self.assertFalse((self.vault / ".github").exists(), "template CI stays in the template")
        self.assertTrue((self.vault / "People" / "Oleg.md").exists())
        self.assertTrue((self.vault / "People" / "Maria.md").exists())
        self.assertIn("Set up task vault", self.git(self.vault, "log", "--oneline"))
        self.assertEqual(self.git(self.vault, "status", "--porcelain"), "")

        for folder in (".claude/skills", ".hermes/skills"):
            skill = (self.home / folder / "task-vault" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(str(self.vault), skill)
            self.assertNotIn("{{", skill)
            self.assertTrue(skill.startswith("---\nname: task-vault\ndescription: "))
        self.assertFalse((self.home / ".agents").exists(), "no Codex-family agent was detected")

    def test_connect_all_and_remove(self) -> None:
        self.setup("init", "--yes", "--agents", "none")
        self.setup("connect", "--agents", "all")
        for folder in (".claude/skills", ".agents/skills", ".hermes/skills"):
            self.assertTrue((self.home / folder / "task-vault" / "SKILL.md").exists(), folder)
        self.setup("connect", "--agents", "all", "--remove")
        for folder in (".claude/skills", ".agents/skills", ".hermes/skills"):
            self.assertFalse((self.home / folder / "task-vault").exists(), folder)

    def test_connect_leaves_another_vaults_skill_alone(self) -> None:
        other = self.home / ".agents" / "skills" / "task-vault"
        other.mkdir(parents=True)
        (other / "SKILL.md").write_text("vault at /somewhere/else\n", encoding="utf-8")
        self.setup("init", "--yes", "--agents", "none")
        out = self.setup("connect", "--agents", "codex").stdout
        self.assertIn("belongs to another vault", out)
        self.assertIn("/somewhere/else", (other / "SKILL.md").read_text(encoding="utf-8"))

    def test_init_pushes_to_a_given_remote(self) -> None:
        remote = self.bare("mine")
        self.setup("init", "--yes", "--agents", "none", "--remote", str(remote))
        self.assertIn("Set up task vault", self.git(remote, "log", "--oneline", "main"))


class TestTaskTool(VaultTest):
    def setUp(self) -> None:
        super().setUp()
        self.setup("init", "--people", "Anna", "--yes", "--agents", "none")

    def test_create_list_close_and_lint(self) -> None:
        path = self.tasks("new", "Fix the tap", "--assignee", "Anna", "--project", "Home",
                          "--status", "todo", "--due", "2000-01-01").stdout.strip()
        self.assertEqual(path, "Tasks/Fix the tap.md")
        self.assertIn("Fix the tap", self.tasks("list", "--when", "overdue").stdout)
        self.tasks("done", "Fix the tap", "-m", "washer replaced")
        text = (self.vault / path).read_text(encoding="utf-8")
        self.assertIn("status: done", text)
        self.assertIn("completedDate: ", text)
        self.assertIn("status -> done: washer replaced", text)
        self.assertNotIn("Fix the tap", self.tasks("list").stdout)
        self.assertEqual(self.tasks("lint").stdout.strip(), "ok")

    def test_a_recurring_task_stays_open(self) -> None:
        self.tasks("new", "Water plants", "--assignee", "Anna", "--project", "Home",
                   "--status", "todo", "--scheduled", "2026-01-03",
                   "--recurrence", "FREQ=WEEKLY;BYDAY=SA")
        self.tasks("done", "Water plants")
        text = (self.vault / "Tasks" / "Water plants.md").read_text(encoding="utf-8")
        self.assertIn("status: todo", text)
        self.assertIn("complete_instances:\n  - ", text)
        self.assertNotIn("completedDate", text)

    def test_lint_catches_unknown_people_and_statuses(self) -> None:
        self.tasks("new", "Bad", "--assignee", "Nobody", "--project", "Home")
        self.tasks("set", "Bad", "status=whatever", ok=False)
        result = self.tasks("lint", ok=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("'Nobody' has no note in People/", result.stdout)

    def test_archive_moves_only_old_closed_tasks(self) -> None:
        self.tasks("new", "Old", "--assignee", "Anna", "--project", "Home", "--status", "todo")
        self.tasks("set", "Old", "status=done", "completedDate=2020-05-01")
        self.tasks("new", "Fresh", "--assignee", "Anna", "--project", "Home", "--status", "todo")
        self.tasks("done", "Fresh")
        self.tasks("archive")
        self.assertTrue((self.vault / "Archive" / "2020" / "Old.md").exists())
        self.assertTrue((self.vault / "Tasks" / "Fresh.md").exists())
        self.assertIn("Old", self.tasks("list", "--all", "--archive").stdout)

    def test_sync_shares_changes_between_two_machines(self) -> None:
        remote = self.bare("shared")
        self.git(self.vault, "remote", "add", "origin", str(remote))
        self.tasks("sync")
        second = self.tmp / "second"
        self.run_in(self.tmp, "git", "clone", "-q", str(remote), str(second))

        self.tasks("new", "From laptop", "--project", "Home")
        self.tasks("sync", "-m", "laptop")
        self.tasks("new", "From desktop", "--project", "Home", vault=second)
        out = self.tasks("sync", "-m", "desktop", vault=second).stdout
        self.assertIn("synced with origin", out)
        self.assertTrue((second / "Tasks" / "From laptop.md").exists())
        self.tasks("sync")
        self.assertTrue((self.vault / "Tasks" / "From desktop.md").exists())


class TestUpdate(VaultTest):
    def test_update_takes_template_files_and_keeps_tasks(self) -> None:
        # A published template, and a vault cloned from it (Option B).
        published = self.tmp / "published"
        shutil.copytree(TEMPLATE, published, ignore=IGNORE)
        self.git(published, "init", "-q", "-b", "main")
        self.git(published, "add", "-A")
        self.git(published, "commit", "-q", "-m", "template 1")
        vault = self.tmp / "cloned"
        self.run_in(self.tmp, "git", "clone", "-q", str(published), str(vault))
        mine = self.bare("mine")
        self.setup("init", "--yes", "--agents", "none", "--people", "Anna",
                   "--remote", str(mine), vault=vault)
        self.assertIn("template", self.git(vault, "remote"))
        self.tasks("new", "Mine", "--assignee", "Anna", "--project", "Home", vault=vault)
        self.tasks("sync", vault=vault)

        (published / "AGENTS.md").write_text("# new rules\n", encoding="utf-8")
        (published / "VERSION").write_text("9.9.9\n", encoding="utf-8")
        self.git(published, "commit", "-qam", "template 2")

        out = self.setup("update", vault=vault).stdout
        self.assertIn("-> 9.9.9", out)
        self.assertEqual((vault / "AGENTS.md").read_text(encoding="utf-8"), "# new rules\n")
        self.assertTrue((vault / "Tasks" / "Mine.md").exists())
        self.assertTrue((vault / "People" / "Anna.md").exists())
        self.assertFalse((vault / "Tasks" / "Scan passports.md").exists(),
                         "examples do not come back with an update")


if __name__ == "__main__":
    unittest.main()
