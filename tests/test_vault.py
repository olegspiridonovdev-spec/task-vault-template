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
        self.tmp = Path(tempfile.mkdtemp()).resolve()  # long path on Windows (no RUNNER~1)
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
        self.setup("init", "--people", "Sam, Maria", "--yes")

        self.assertFalse(list((self.vault / "Tasks").glob("*.md")), "examples are removed")
        self.assertFalse((self.vault / "People" / "Anna.md").exists())
        self.assertFalse((self.vault / ".github").exists(), "template CI stays in the template")
        self.assertFalse((self.vault / "MAINTAINING.md").exists(), "template docs stay there too")
        self.assertTrue((self.vault / "People" / "Sam.md").exists())
        self.assertTrue((self.vault / "People" / "Maria.md").exists())
        self.assertIn("Set up task vault", self.git(self.vault, "log", "--oneline"))
        self.assertEqual(self.git(self.vault, "status", "--porcelain"), "")

        for folder in (".claude/skills", ".hermes/skills"):
            skill = (self.home / folder / "task-vault" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(str(self.vault), skill)
            self.assertNotIn("{{", skill)
            self.assertTrue(skill.startswith("---\nname: task-vault\ndescription: "))
        self.assertFalse((self.home / ".agents").exists(), "no Codex-family agent was detected")

    def test_grok_build_is_detected_and_uses_the_shared_skill_folder(self) -> None:
        (self.home / ".grok").mkdir()
        out = self.setup("init", "--yes").stdout
        self.assertIn("grok --trust", out, "Grok loads AGENTS.md only in trusted folders")
        skill = self.home / ".agents" / "skills" / "task-vault" / "SKILL.md"
        self.assertIn(str(self.vault), skill.read_text(encoding="utf-8"))
        self.setup("connect", "--agents", "grok", "--remove")
        self.assertFalse(skill.parent.exists())

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


class TestTemplateUpdates(VaultTest):
    """The template moves on; a vault takes the new version with `update`."""

    def setUp(self) -> None:
        super().setUp()
        self.published = self.tmp / "published"
        shutil.copytree(TEMPLATE, self.published, ignore=IGNORE)
        self.git(self.published, "init", "-q", "-b", "main")
        self.git(self.published, "add", "-A")
        self.git(self.published, "commit", "-q", "-m", "template 1")
        self.mine = self.bare("mine")
        self.vault = self.tmp / "cloned"
        self.run_in(self.tmp, "git", "clone", "-q", str(self.published), str(self.vault))
        self.setup("init", "--yes", "--agents", "none", "--people", "Anna",
                   "--remote", str(self.mine))

    def publish(self, message: str) -> None:
        (self.published / "VERSION").write_text("9.9.9\n", encoding="utf-8")
        self.git(self.published, "add", "-A")
        self.git(self.published, "commit", "-q", "-m", message)

    def test_new_files_arrive_and_deleted_ones_go_but_yours_stay(self) -> None:
        manifest = self.published / ".template-files"
        lines = manifest.read_text(encoding="utf-8").splitlines()
        lines = [line for line in lines if line != "GEMINI.md"] + ["NEWS.md"]
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        (self.published / "NEWS.md").write_text("news\n", encoding="utf-8")
        (self.published / "GEMINI.md").unlink()
        (self.published / "tools" / "tasks.py").write_text(
            (self.published / "tools" / "tasks.py").read_text(encoding="utf-8") + "\n# v2\n",
            encoding="utf-8")
        self.publish("template 2")
        (self.vault / "Views" / "Mine.base").write_text("filters: {}\n", encoding="utf-8")
        self.tasks("sync", "-m", "my view")

        self.setup("update")

        self.assertEqual((self.vault / "NEWS.md").read_text(encoding="utf-8"), "news\n")
        self.assertFalse((self.vault / "GEMINI.md").exists(), "removed from the template")
        self.assertIn("# v2", (self.vault / "tools" / "tasks.py").read_text(encoding="utf-8"))
        self.assertTrue((self.vault / "Views" / "Mine.base").exists(), "your own view stays")
        self.assertTrue((self.vault / "People" / "Anna.md").exists())
        self.assertIn("Update template", self.git(self.mine, "log", "-1", "--format=%s"),
                      "update pushes, so other machines get it with sync")

    def test_a_template_file_you_edited_is_kept_when_the_template_drops_it(self) -> None:
        (self.vault / "GEMINI.md").write_text("my own notes\n", encoding="utf-8")
        self.tasks("sync", "-m", "edit")
        (self.published / "GEMINI.md").unlink()
        self.publish("template 2")
        out = self.setup("update").stdout
        self.assertEqual((self.vault / "GEMINI.md").read_text(encoding="utf-8"), "my own notes\n")
        self.assertIn("kept GEMINI.md", out)

    def test_sync_says_when_the_template_has_an_update(self) -> None:
        self.assertNotIn("update available", self.tasks("sync").stdout)
        self.publish("template 2")
        self.assertIn("template update available", self.tasks("sync").stdout)
        self.setup("update")
        self.assertNotIn("update available", self.tasks("sync").stdout)

    def test_check_reports_without_changing_anything(self) -> None:
        self.publish("template 2")
        out = self.setup("update", "--check").stdout
        self.assertIn("9.9.9", out)
        self.assertNotEqual((self.vault / "VERSION").read_text(encoding="utf-8").strip(), "9.9.9")
        self.assertEqual(self.git(self.vault, "status", "--porcelain"), "")

    def test_other_machines_get_the_update_and_new_skill_text_with_sync(self) -> None:
        other = self.tmp / "other"
        self.run_in(self.tmp, "git", "clone", "-q", str(self.mine), str(other))
        other_home = self.tmp / "other-home"
        other_home.mkdir()
        env = dict(self.env, HOME=str(other_home), USERPROFILE=str(other_home))
        def on_other(*cmd: str) -> None:
            result = subprocess.run(list(cmd), cwd=str(other), env=env, capture_output=True,
                                    text=True, stdin=subprocess.DEVNULL)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        on_other(sys.executable, str(other / "setup.py"), "connect", "--agents", "claude")

        skill = self.published / "skill" / "SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8") + "\nNEW SKILL LINE\n", encoding="utf-8")
        self.publish("template 2")
        self.setup("update")
        on_other(sys.executable, str(other / "tools" / "tasks.py"), "sync")

        self.assertEqual((other / "VERSION").read_text(encoding="utf-8").strip(), "9.9.9")
        installed = other_home / ".claude" / "skills" / "task-vault" / "SKILL.md"
        self.assertIn("NEW SKILL LINE", installed.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
