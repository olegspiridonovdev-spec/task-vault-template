"""End-to-end checks: setup, agent connection, the task tool, sync and update.

Each test copies the template into a temporary directory, with its own HOME
(so skills land in a throwaway home, never the real one) and a bare git
repository standing in for the private remote. Run: python3 -m unittest discover tests
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
            # Never schedule a real launchd/systemd/cron/Task Scheduler job from a test.
            "TASK_VAULT_SCHEDULER": "0",
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
        self.assertIn("complete_instances:\n  - 2026-01-03", text, "the occurrence, not today")
        self.assertIn("scheduled: 2026-01-10", text, "moves on to the next occurrence")
        self.assertNotIn("completedDate", text)

    def write_task(self, name: str, front: str) -> Path:
        path = self.vault / "Tasks" / f"{name}.md"
        path.write_text(f"---\n{front.strip()}\ntags:\n  - task\n---\n", encoding="utf-8")
        return path

    def test_recurring_rules_move_to_the_right_next_date(self) -> None:
        cases = [  # recurrence, scheduled, next scheduled
            ("DTSTART:20261114;FREQ=WEEKLY;BYDAY=SA", "2026-11-14", "2026-11-21"),
            ("FREQ=WEEKLY;INTERVAL=2;BYDAY=SA", "2026-11-14", "2026-11-28"),
            ("FREQ=WEEKLY;BYDAY=MO,TH", "2026-11-16T09:00", "2026-11-19T09:00"),
            ("FREQ=DAILY;INTERVAL=2", "2026-11-14", "2026-11-16"),
            ("FREQ=MONTHLY;BYMONTHDAY=1", "2026-11-01", "2026-12-01"),
            ("FREQ=MONTHLY;BYMONTHDAY=31", "2026-10-31", "2026-12-31"),
            ("FREQ=MONTHLY;BYDAY=-1FR", "2026-11-27", "2026-12-25"),
            ("FREQ=MONTHLY;BYDAY=1MO", "2026-11-02", "2026-12-07"),
            ("FREQ=YEARLY", "2026-02-10", "2027-02-10"),
        ]
        for i, (rule, scheduled, expected) in enumerate(cases):
            with self.subTest(rule=rule):
                path = self.write_task(f"Chore {i}", f"title: Chore {i}\nstatus: todo\n"
                                       f"scheduled: {scheduled}\nrecurrence: {rule}")
                self.tasks("done", f"Chore {i}")
                text = path.read_text(encoding="utf-8")
                self.assertIn(f"scheduled: {expected}", text)
                self.assertIn(f"  - {scheduled[:10]}", text)

    def test_done_with_a_date_ticks_that_occurrence(self) -> None:
        path = self.write_task("Bins", "title: Bins\nstatus: todo\nscheduled: 2026-11-14\n"
                               "recurrence: FREQ=WEEKLY;BYDAY=SA")
        self.tasks("done", "Bins", "--date", "2026-11-21")
        text = path.read_text(encoding="utf-8")
        self.assertIn("  - 2026-11-21", text)
        self.assertIn("scheduled: 2026-11-28", text)

    def test_tasks_written_by_tasknotes_pass_lint(self) -> None:
        # What TaskNotes 4.18 writes: no title (the file name is the title),
        # local-time stamps with an offset, DTSTART in the rule, skipped_instances.
        self.write_task("Buy filters", """
status: done
priority: high
due: 2026-11-20
scheduled: 2026-11-14
contexts:
  - shop
projects:
  - "[[Home]]"
timeEstimate: 30
dateCreated: 2026-11-13T17:19:05.129-05:00
dateModified: 2026-11-13T17:19:07.030-05:00
assignee: "[[Anna]]"
completedDate: 2026-11-13
skipped_instances: []
""")
        self.assertIn("ok", self.tasks("lint").stdout)
        self.assertIn("| Buy filters |", self.tasks("list", "--all").stdout)

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


class TestTaskDetails(VaultTest):
    """History, notes and relations between tasks."""

    def setUp(self) -> None:
        super().setUp()
        self.setup("init", "--people", "Anna", "--yes", "--agents", "none")
        for title in ("Order parts", "Fix the tap", "Buy washer"):
            self.tasks("new", title, "--assignee", "Anna", "--project", "Home", "--status", "todo")

    def read(self, title: str) -> str:
        return (self.vault / "Tasks" / f"{title}.md").read_text(encoding="utf-8")

    def test_notes_go_in_their_own_section_even_after_completion(self) -> None:
        self.tasks("note", "Fix the tap", "-m", "washer is 3/4 inch")
        self.tasks("done", "Fix the tap", "-m", "fixed")
        self.tasks("note", "Fix the tap", "-m", "plumber said: replace the valve next year")
        text = self.read("Fix the tap")
        notes, log = text.split("## Notes", 1)[1].split("## Log", 1)
        self.assertIn("washer is 3/4 inch", notes)
        self.assertIn("replace the valve next year", notes)
        self.assertIn("status -> done: fixed", log)
        shown = self.tasks("show", "Fix the tap").stdout
        self.assertIn("washer is 3/4 inch", shown)
        self.assertIn("status -> done", shown)

    def test_blocked_by_is_written_like_tasknotes_and_used_by_list_and_done(self) -> None:
        self.tasks("link", "Fix the tap", "--blocked-by", "Order parts")
        self.assertIn('blockedBy:\n  - uid: "[[Order parts]]"\n    reltype: FINISHTOSTART',
                      self.read("Fix the tap"))
        self.assertIn("blocked by Order parts", self.tasks("list").stdout)
        self.assertNotIn("Fix the tap", self.tasks("list", "--ready").stdout)
        self.assertIn("blocks: Fix the tap", self.tasks("show", "Order parts").stdout)
        self.assertIn("unblocked: Fix the tap", self.tasks("done", "Order parts").stdout)
        self.assertIn("Fix the tap", self.tasks("list", "--ready").stdout)
        self.assertIn("blocked by: Order parts (done)", self.tasks("show", "Fix the tap").stdout)
        self.assertIn("ok", self.tasks("lint").stdout)

    def test_dependencies_written_by_tasknotes_are_read_and_kept(self) -> None:
        path = self.vault / "Tasks" / "Fix the tap.md"
        text = path.read_text(encoding="utf-8").replace(
            "tags:", 'blockedBy:\n  - uid: "[[Order parts]]"\n    reltype: FINISHTOSTART\n'
                     "    gap: P1D\ntags:", 1)
        path.write_text(text, encoding="utf-8")
        self.assertIn("blocked by Order parts", self.tasks("list").stdout)
        self.tasks("set", "Fix the tap", "priority=high")
        self.assertIn("    gap: P1D", self.read("Fix the tap"), "other edits keep the dependency")
        self.tasks("link", "Fix the tap", "--blocked-by", "Buy washer")
        text = self.read("Fix the tap")
        self.assertIn("    gap: P1D", text)
        self.assertIn('  - uid: "[[Buy washer]]"', text)
        self.assertIn("ok", self.tasks("lint").stdout)

    def test_subtasks_use_the_parent_in_projects_like_tasknotes(self) -> None:
        self.tasks("link", "Buy washer", "--parent", "Fix the tap")
        text = self.read("Buy washer")
        self.assertIn('  - "[[Home]]"', text)
        self.assertIn('  - "[[Fix the tap]]"', text)
        self.assertIn("subtasks: Buy washer (todo)", self.tasks("show", "Fix the tap").stdout)
        self.assertIn("parent: Fix the tap", self.tasks("show", "Buy washer").stdout)
        self.assertIn("1 subtask still open: Buy washer", self.tasks("done", "Fix the tap").stdout)
        self.assertIn("ok", self.tasks("lint").stdout)

    def test_related_tasks_are_linked_from_the_notes(self) -> None:
        self.tasks("link", "Order parts", "--related", "Buy washer", "-m", "same shop")
        self.assertIn("related: [[Buy washer]] (same shop)", self.read("Order parts"))
        self.assertIn("mentioned in: Order parts", self.tasks("show", "Buy washer").stdout)

    def test_estimate_and_actual_time(self) -> None:
        self.tasks("new", "Paint fence", "--assignee", "Anna", "--project", "Home",
                   "--estimate", "120")
        self.assertIn("timeEstimate: 120", self.read("Paint fence"))
        self.tasks("done", "Paint fence", "--spent", "150", "-m", "two coats")
        self.assertIn("took 150 min (estimate 120)", self.read("Paint fence"))

    def test_lint_catches_missing_blockers_and_loops(self) -> None:
        self.tasks("link", "Fix the tap", "--blocked-by", "Order parts")
        self.tasks("link", "Order parts", "--blocked-by", "Fix the tap")
        out = self.tasks("lint", ok=False).stdout
        self.assertIn("dependency loop", out)
        self.tasks("link", "Order parts", "--unblock", "Fix the tap")
        path = self.vault / "Tasks" / "Buy washer.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "tags:", 'blockedBy:\n  - "[[No such task]]"\ntags:', 1), encoding="utf-8")
        self.assertIn("No such task", self.tasks("lint", ok=False).stdout)


class TestNotesJournalLists(VaultTest):
    """The journal, notes and lists next to the tasks."""

    def setUp(self) -> None:
        super().setUp()
        self.setup("init", "--yes", "--agents", "none", "--people", "Anna")
        self.today = time.strftime("%Y-%m-%d")
        self.page = self.vault / "Journal" / self.today[:4] / f"{self.today}.md"

    def read(self, *parts: str) -> str:
        return self.vault.joinpath(*parts).read_text(encoding="utf-8")

    def test_init_removes_the_examples_and_their_empty_folders(self) -> None:
        for folder in ("Journal", "Notes", "Lists"):
            self.assertFalse(list((self.vault / folder).rglob("*.md")) if
                             (self.vault / folder).exists() else [], folder)
        self.assertFalse((self.vault / "Journal" / "2026").exists())

    def test_journal_entries_go_to_the_day_page(self) -> None:
        self.tasks("journal", "-m", "decided to switch the boiler company")
        self.tasks("journal", "-m", "called them\nthey come Friday", "--by", "anna")
        text = self.page.read_text(encoding="utf-8")
        self.assertIn(f"date: {self.today}", text)
        self.assertIn("  - journal", text)
        self.assertIn("![[Views/Day.base]]", text)
        self.assertRegex(text, r"- \d\d:\d\d — decided to switch the boiler company\n")
        self.assertRegex(text, r"- \d\d:\d\d — Anna: called them\n  they come Friday\n")
        self.tasks("journal", "--date", "2026-01-05", "-m", "looking back")
        self.assertIn("\n- looking back\n", self.read("Journal", "2026", "2026-01-05.md"))
        self.assertEqual(self.tasks("journal", "-m", "x", "--by", "Nobody", ok=False).returncode, 1)
        self.tasks("lint")

    def test_journal_prints_the_day_with_its_tasks_notes_and_list_items(self) -> None:
        self.tasks("new", "Fix the tap", "--scheduled", self.today)
        self.tasks("new", "Buy filters")
        self.tasks("done", "Buy filters")
        self.tasks("memo", "Boiler", "-m", "the old one is from 2009")
        self.tasks("add", "Books", "Project Hail Mary")
        self.tasks("journal", "-m", "busy day")
        out = self.tasks("journal").stdout
        self.assertIn("busy day", out)
        self.assertIn("Fix the tap (inbox; planned)", out)
        self.assertIn("Buy filters (done; finished)", out)
        self.assertIn("- Boiler", out)
        self.assertIn("Books: [ ] Project Hail Mary", out)
        self.assertNotIn("Day.base", out)
        self.assertIn("(no journal page)", self.tasks("journal", "--date", "2026-01-05").stdout)

    def test_memo_creates_adds_to_and_prints_a_note(self) -> None:
        self.tasks("memo", "Wi-Fi setup", "-m", "router password is on the box", "--project", "Home")
        self.tasks("memo", "wifi SETUP", "-m", "channel 6")
        text = self.read("Notes", "Wi-Fi setup.md")
        self.assertIn(f"created: {self.today}", text)
        self.assertIn('  - "[[Home]]"', text)
        self.assertIn(f"router password is on the box\n\n- {self.today}: channel 6\n", text)
        self.assertEqual(len(list((self.vault / "Notes").glob("*.md"))), 1)
        self.assertIn("channel 6", self.tasks("memo", "wifi").stdout)
        out = self.tasks("memo", "Wi-Fi", "-m", "a different note").stdout
        self.assertIn("similar note exists: Notes/Wi-Fi setup.md", out)
        self.tasks("lint")

    def test_lists_add_check_undo_and_show(self) -> None:
        self.tasks("add", "Films", "Dune Part Two", "-m", "Alex recommended", "--by", "Anna")
        self.assertIn("already on the list", self.tasks("add", "films", "dune part two").stdout)
        self.tasks("add", "Films", "Arrival")
        line = f"- [ ] Dune Part Two — Alex recommended (added {self.today} by Anna)"
        self.assertIn(line, self.read("Lists", "Films.md"))
        self.tasks("check", "Films", "dune", "-m", "8/10 (great)")
        done = f"- [x] Dune Part Two — Alex recommended (added {self.today} by Anna; done {self.today}: 8/10 (great))"
        self.assertIn(done, self.read("Lists", "Films.md"))
        self.assertIn("already done", self.tasks("check", "Films", "dune").stdout)
        self.tasks("check", "Films", "dune", "--undo")
        self.assertIn(line + "\n", self.read("Lists", "Films.md"))
        self.tasks("check", "Films", "dune")
        self.assertEqual(self.tasks("check", "Films", "Matrix", ok=False).returncode, 1)
        self.tasks("add", "Films", "Arrival 2")
        self.assertIn("several items match", self.tasks("check", "Films", "arr", ok=False).stderr)
        self.assertIn("Films: 2 open, 1 done", self.tasks("lists").stdout)
        self.assertNotIn("Dune", self.tasks("lists", "Films", "--open").stdout)
        self.tasks("lint")

    def test_find_searches_every_folder(self) -> None:
        self.tasks("new", "Service the boiler")
        self.tasks("journal", "-m", "boiler makes a noise")
        self.tasks("memo", "Boiler", "-m", "model X200")
        out = self.tasks("find", "boiler").stdout
        self.assertIn("Tasks/Service the boiler.md\n", out)
        self.assertIn("— boiler makes a noise", out)
        self.assertIn("Notes/Boiler.md\n", out)
        narrow = self.tasks("find", "boiler", "x200").stdout
        self.assertIn("Notes/Boiler.md: model X200", narrow)
        self.assertNotIn("Tasks/", narrow)

    def test_show_lists_journal_pages_and_notes_that_link_to_a_task(self) -> None:
        self.tasks("new", "Fix the tap")
        self.tasks("journal", "-m", "plumber came for [[Fix the tap]]")
        self.tasks("memo", "Plumbing", "-m", "see [[Fix the tap]]")
        out = self.tasks("show", "Fix the tap").stdout
        self.assertIn(f"mentioned in: {self.today}, Plumbing", out)

    def test_lint_catches_duplicates_and_wrong_dates(self) -> None:
        self.tasks("add", "Films", "Dune")
        films = self.vault / "Lists" / "Films.md"
        films.write_text(films.read_text(encoding="utf-8")
                         + "- [x] Dune (done 2026-01-01)\n", encoding="utf-8")
        out = self.tasks("lint").stdout
        self.assertIn("an item is on the list 2 times", out)
        page = self.vault / "Journal" / "2026" / "2026-01-05.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("---\ndate: 2026-01-06\ndate: 2026-01-05\ntags:\n  - journal\n---\n"
                        "- same\n- same\n", encoding="utf-8")
        out = self.tasks("lint", ok=False).stdout
        self.assertIn("field 'date' appears twice", out)
        self.assertIn("this line appears 2 times: - same", out)


class TestNotesSync(VaultTest):
    """Two machines add to the same journal page, note and list between syncs."""

    def test_both_sides_lines_are_kept(self) -> None:
        self.setup("init", "--yes", "--agents", "none", "--people", "Anna",
                   "--remote", str(self.bare("shared")))
        self.tasks("journal", "-m", "first")
        self.tasks("add", "Films", "Dune")
        self.tasks("memo", "Boiler", "-m", "old")
        self.tasks("sync")
        second = self.tmp / "second"
        self.run_in(self.tmp, "git", "clone", "-q", str(self.tmp / "shared.git"), str(second))
        self.tasks("journal", "-m", "from here")
        self.tasks("add", "Films", "Arrival")
        self.tasks("check", "Films", "Dune", "-m", "8/10")
        self.tasks("memo", "Boiler", "-m", "here")
        self.tasks("journal", "-m", "from there", vault=second)
        self.tasks("add", "Films", "Heat", vault=second)
        self.tasks("memo", "Boiler", "-m", "there", vault=second)
        self.tasks("sync", "-m", "one")
        self.assertIn("synced with origin", self.tasks("sync", "-m", "two", vault=second).stdout)
        self.tasks("sync")
        for parts in (("Lists", "Films.md"), ("Notes", "Boiler.md")):
            self.assertEqual(self.vault.joinpath(*parts).read_text(encoding="utf-8"),
                             second.joinpath(*parts).read_text(encoding="utf-8"))
        films = (second / "Lists" / "Films.md").read_text(encoding="utf-8")
        for item in ("- [x] Dune", "- [ ] Arrival", "- [ ] Heat"):
            self.assertIn(item, films)
        page = next((second / "Journal").rglob("*.md")).read_text(encoding="utf-8")
        for entry in ("first", "from here", "from there"):
            self.assertIn(entry, page)
        boiler = (second / "Notes" / "Boiler.md").read_text(encoding="utf-8")
        self.assertIn("here", boiler)
        self.assertIn("there", boiler)
        self.assertNotIn("<<<<<<<", films + page + boiler)
        self.tasks("lint", vault=second)


class TestSyncConflicts(VaultTest):
    """Two machines change the same task between syncs."""

    def setUp(self) -> None:
        super().setUp()
        self.setup("init", "--yes", "--agents", "none", "--people", "Anna",
                   "--remote", str(self.bare("shared")))
        self.tasks("new", "Fix the tap", "--assignee", "Anna", "--project", "Home")
        self.tasks("sync")
        self.second = self.tmp / "second"
        self.run_in(self.tmp, "git", "clone", "-q", str(self.tmp / "shared.git"), str(self.second))
        self.tasks("sync", vault=self.second)

    def read(self, vault: Path) -> str:
        return (vault / "Tasks" / "Fix the tap.md").read_text(encoding="utf-8")

    def both_sync(self) -> None:
        self.tasks("sync", "-m", "first")
        out = self.tasks("sync", "-m", "second", vault=self.second)
        self.assertIn("synced with origin", out.stdout)
        self.tasks("sync")
        self.assertEqual(self.read(self.vault), self.read(self.second))
        self.tasks("lint")

    def test_different_fields_and_both_logs_are_kept(self) -> None:
        self.tasks("set", "Fix the tap", "status=waiting", "waiting_on=plumber", "-m", "called")
        self.tasks("set", "Fix the tap", "priority=high", "-m", "it drips", vault=self.second)
        self.both_sync()
        text = self.read(self.vault)
        self.assertIn("status: waiting", text)
        self.assertIn("priority: high", text)
        self.assertIn("called", text)
        self.assertIn("it drips", text)
        self.assertNotIn("<<<<<<<", text)

    def test_same_field_newer_edit_wins_and_the_other_is_logged(self) -> None:
        self.tasks("set", "Fix the tap", "status=waiting", "-m", "older")
        time.sleep(1.1)
        self.tasks("set", "Fix the tap", "status=in-progress", "-m", "newer", vault=self.second)
        self.both_sync()
        text = self.read(self.vault)
        self.assertIn("status: in-progress", text)
        self.assertRegex(text, r"sync conflict: status was waiting on another machine")

    def test_notes_edited_on_both_machines_are_both_kept(self) -> None:
        for vault, note in ((self.vault, "Washer size 3/4."), (self.second, "Shop on Main St.")):
            path = vault / "Tasks" / "Fix the tap.md"
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("\n## Log", f"\n{note}\n\n## Log", 1), encoding="utf-8")
        self.both_sync()
        text = self.read(self.vault)
        self.assertIn("Washer size 3/4.", text)
        self.assertIn("Shop on Main St.", text)

    def test_newer_means_later_in_time_whatever_the_timestamp_format(self) -> None:
        # 17:30-05:00 (TaskNotes, local time) is 22:30 UTC: later than 22:00Z.
        def task(status: str, stamp: str) -> str:
            return f"---\ntitle: T\nstatus: {status}\ndateModified: {stamp}\ntags:\n  - task\n---\n"
        files = {"base": task("todo", "2026-11-13T21:00:00Z"),
                 "ours": task("waiting", "2026-11-13T22:00:00Z"),
                 "theirs": task("done", "2026-11-13T17:30:00.000-05:00")}
        for name, content in files.items():
            (self.tmp / name).write_text(content, encoding="utf-8")
        self.run_in(self.tmp, sys.executable, str(self.vault / "tools" / "tasks.py"), "merge-driver",
                    *(str(self.tmp / n) for n in ("base", "ours", "theirs")))
        merged = (self.tmp / "ours").read_text(encoding="utf-8")
        self.assertIn("status: done", merged)
        self.assertIn("status was waiting on another machine", merged)

    def test_notes_added_on_both_machines_are_merged_without_duplicates(self) -> None:
        self.tasks("note", "Fix the tap", "-m", "first note")
        self.tasks("sync")
        self.tasks("sync", vault=self.second)
        self.tasks("note", "Fix the tap", "-m", "from laptop")
        self.tasks("note", "Fix the tap", "-m", "from desktop", vault=self.second)
        self.both_sync()
        text = self.read(self.vault)
        for line in ("first note", "from laptop", "from desktop"):
            self.assertEqual(text.count(line), 1, line)
        self.assertEqual(text.count("## Notes"), 1)

    def test_a_conflict_outside_tasks_stops_cleanly_and_says_which_file(self) -> None:
        for vault, rule in ((self.vault, "one"), (self.second, "two")):
            (vault / "Projects" / "Home.md").write_text(f"# Home\n{rule}\n", encoding="utf-8")
        self.tasks("sync")
        out = self.tasks("sync", vault=self.second, ok=False)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("Projects/Home.md", out.stdout + out.stderr)
        self.assertEqual(self.git(self.second, "status", "--porcelain"), "",
                         "the rebase is aborted; nothing is left half-merged")


class TestAutoSync(VaultTest):
    """Every change is shared at once; tools/autosync.py catches the rest."""

    def setUp(self) -> None:
        super().setUp()
        self.env["TASK_VAULT_AUTOSYNC_QUIET"] = "1"  # notifications go to the log
        self.remote = self.bare("shared")
        self.setup("init", "--yes", "--agents", "none", "--people", "Anna",
                   "--remote", str(self.remote))
        self.second = self.tmp / "second"
        self.run_in(self.tmp, "git", "clone", "-q", str(self.remote), str(self.second))

    def pushed(self) -> str:
        return self.git(self.remote, "log", "-1", "--format=%s")

    def autosync(self, *args: str, vault: Path | None = None):
        vault = vault or self.vault
        return self.run_in(self.tmp, sys.executable, str(vault / "tools" / "autosync.py"), *args)

    def test_each_change_is_committed_and_pushed_right_away(self) -> None:
        out = self.tasks("new", "Fix the tap", "--assignee", "Anna")
        self.assertIn("saved and synced", out.stderr)
        self.assertEqual(out.stdout.strip(), "Tasks/Fix the tap.md")  # stdout stays one line
        self.assertEqual(self.pushed(), 'Add task "Fix the tap"')
        self.tasks("set", "Fix the tap", "status=todo", "-m", "triaged")
        self.assertEqual(self.pushed(), 'Update "Fix the tap": status=todo: triaged')
        self.tasks("done", "Fix the tap", "-m", "new washer")
        self.assertEqual(self.pushed(), 'Done: "Fix the tap": new washer')
        self.tasks("add", "Films", "Dune")
        self.assertEqual(self.pushed(), 'Add "Dune" to Films')
        self.tasks("journal", "-m", "Quiet day")
        self.assertEqual(self.pushed(), "Journal today: Quiet day")
        self.assertEqual(self.git(self.vault, "status", "--porcelain"), "")
        self.tasks("sync", vault=self.second)  # the other machine has it all
        self.assertTrue((self.second / "Tasks" / "Fix the tap.md").exists())
        self.assertTrue((self.second / "Lists" / "Films.md").exists())

    def test_reading_or_a_change_that_changes_nothing_makes_no_commit(self) -> None:
        self.tasks("add", "Films", "Dune")
        before = self.git(self.remote, "rev-parse", "HEAD")
        self.tasks("list")
        self.tasks("add", "Films", "Dune")  # already on the list
        self.tasks("archive", "--dry-run")
        self.assertEqual(self.git(self.remote, "rev-parse", "HEAD"), before)

    def test_no_sync_flag_and_setting_leave_the_change_for_later(self) -> None:
        before = self.pushed()
        self.tasks("new", "Batch one", "--no-sync")
        self.env["TASK_VAULT_AUTOSYNC"] = "0"
        self.tasks("new", "Batch two")
        del self.env["TASK_VAULT_AUTOSYNC"]
        self.assertEqual(self.pushed(), before)
        self.assertIn("Batch one", self.git(self.vault, "status", "--porcelain", "-uall"))
        self.tasks("sync", "-m", "two tasks")
        self.assertEqual(self.pushed(), "two tasks")
        marker = self.vault / ".task-vault.json"
        marker.write_text(marker.read_text(encoding="utf-8").replace(
            "{", '{\n  "sync_after_change": false,', 1), encoding="utf-8")
        self.tasks("new", "Kept local")
        self.assertIn("Kept local", self.git(self.vault, "status", "--porcelain", "-uall"))

    def test_offline_the_change_is_kept_and_the_command_still_succeeds(self) -> None:
        self.git(self.vault, "remote", "set-url", "origin", str(self.tmp / "missing.git"))
        out = self.tasks("new", "Offline task")
        self.assertIn("saved on this machine, not shared yet", out.stderr)
        self.assertEqual(self.git(self.vault, "log", "-1", "--format=%s"), 'Add task "Offline task"')
        self.git(self.vault, "remote", "set-url", "origin", str(self.remote))
        self.autosync("run")  # what the schedule does next time
        self.assertEqual(self.pushed(), 'Add task "Offline task"')

    def test_the_template_repository_itself_never_commits(self) -> None:
        plain = self.tmp / "plain"
        shutil.copytree(TEMPLATE, plain, ignore=IGNORE)  # no .task-vault.json: not a vault
        self.run_in(plain, "git", "init", "-q", "-b", "main")
        out = self.tasks("new", "Example", vault=plain)
        self.assertNotIn("saved", out.stderr)
        self.assertEqual(self.run_in(plain, "git", "log", ok=False).returncode, 128)  # no commits

    def test_a_running_sync_makes_others_wait_or_skip(self) -> None:
        lock = self.vault / ".git" / "task-vault-sync.lock"
        lock.mkdir()
        busy = self.tasks("sync", "--no-wait", ok=False)
        self.assertNotEqual(busy.returncode, 0)
        self.assertIn("another sync is running", busy.stderr)
        self.autosync("run")  # skipped quietly, not a failure
        log = (self.vault / ".git" / "autosync" / "autosync.log").read_text(encoding="utf-8")
        self.assertIn("skipped", log)
        self.assertFalse((self.vault / ".git" / "autosync" / "state").exists())
        lock.rmdir()

    def test_scheduled_run_shares_hand_edits_and_reports_a_conflict_once(self) -> None:
        self.tasks("sync", vault=self.second)
        rules = "House note.md"
        (self.vault / "Projects" / rules).write_text("edited here\n", encoding="utf-8")
        self.autosync("run")
        self.assertEqual(self.pushed(), f"Auto-sync from {platform_host()}")
        self.tasks("sync", vault=self.second)
        (self.vault / "Projects" / rules).write_text("edited here again\n", encoding="utf-8")
        (self.second / "Projects" / rules).write_text("edited there\n", encoding="utf-8")
        self.tasks("sync", vault=self.second)
        data = self.vault / ".git" / "autosync"
        self.autosync("run")
        self.autosync("run")
        self.assertEqual((data / "state").read_text(encoding="utf-8").strip(), "failed")
        log = (data / "autosync.log").read_text(encoding="utf-8")
        self.assertEqual(log.count("(notification) Sync stopped"), 1)  # once, not every run
        self.assertIn("conflict", self.autosync("status").stdout)
        # Resolve it as the status output says, then the next run recovers.
        self.run_in(self.vault, "git", "pull", "-q", "--rebase", ok=False)
        (self.vault / "Projects" / rules).write_text("edited here again\nedited there\n",
                                                     encoding="utf-8")
        self.git(self.vault, "add", f"Projects/{rules}")
        self.env["GIT_EDITOR"] = ":"  # keep the message; PATH has only git
        self.git(self.vault, "rebase", "--continue")
        self.autosync("run")
        self.assertEqual((data / "state").read_text(encoding="utf-8").strip(), "ok")
        self.assertIn("(notification) Back in sync", (data / "autosync.log").read_text(encoding="utf-8"))

    def test_scheduling_is_off_in_tests_and_a_machine_can_opt_out(self) -> None:
        out = self.autosync("install")
        self.assertIn("not scheduled (TASK_VAULT_SCHEDULER=0)", out.stdout)
        self.autosync("ensure")  # quiet no-op here
        self.autosync("uninstall")
        self.assertTrue((self.vault / ".git" / "autosync" / "disabled").exists())
        self.assertIn("turned off here", self.autosync("status").stdout)


def platform_host() -> str:
    import platform
    return platform.node().split(".")[0] or "computer"


class TestPrivacy(VaultTest):
    """Tasks never go to a public GitHub repository."""

    def setUp(self) -> None:
        super().setUp()
        import http.server
        import json as json_
        import threading
        self.visibility = {"private": True}
        test = self

        class FakeGitHub(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = json_.dumps(test.visibility).encode()
                self.send_response(200 if self.path == "/repos/me/tasks" else 404)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), FakeGitHub)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.env["TASK_VAULT_GITHUB_API"] = f"http://127.0.0.1:{server.server_port}"
        # A github.com address that git quietly sends to a local bare repository.
        self.remote = self.bare("tasks")
        config = self.tmp / "gitconfig"
        config.write_text(f'[url "{self.remote.as_posix()}"]\n'
                          '\tinsteadOf = https://github.com/me/tasks.git\n', encoding="utf-8")
        self.env["GIT_CONFIG_GLOBAL"] = str(config)

    def test_sync_pushes_to_a_private_repository(self) -> None:
        self.setup("init", "--yes", "--agents", "none", "--remote", "https://github.com/me/tasks.git")
        self.assertIn("Set up task vault", self.git(self.remote, "log", "--format=%s"))

    def test_setup_and_sync_refuse_a_public_repository(self) -> None:
        self.visibility = {"private": False}
        out = self.setup("init", "--yes", "--agents", "none",
                         "--remote", "https://github.com/me/tasks.git", ok=False)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("PUBLIC", out.stdout + out.stderr)
        self.assertEqual(self.git(self.remote, "log", "--all", "--format=%s"), "", "nothing pushed")
        self.tasks("new", "Secret", "--project", "Home")
        out = self.tasks("sync", ok=False)
        self.assertIn("PUBLIC", out.stdout + out.stderr)
        self.assertEqual(self.git(self.remote, "log", "--all", "--format=%s"), "", "nothing pushed")


class TestUpdate(VaultTest):
    def test_update_takes_template_files_and_keeps_tasks(self) -> None:
        # A published template, and a vault cloned from it (README 2B).
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

    def test_update_adds_the_household_note(self) -> None:
        published = self.tmp / "published"
        shutil.copytree(TEMPLATE, published, ignore=IGNORE)
        self.git(published, "init", "-q", "-b", "main")
        self.git(published, "add", "-A")
        self.git(published, "commit", "-q", "-m", "template 1")
        vault = self.tmp / "cloned"
        self.run_in(self.tmp, "git", "clone", "-q", str(published), str(vault))
        self.setup("init", "--yes", "--agents", "none", "--people", "Anna",
                   "--remote", str(self.bare("mine")), vault=vault)
        (vault / "People" / "Household.md").unlink()  # a vault from before 1.5.0
        self.tasks("sync", vault=vault)
        (published / "VERSION").write_text("9.9.9\n", encoding="utf-8")
        self.git(published, "commit", "-qam", "template 2")
        self.setup("update", vault=vault)
        self.assertTrue((vault / "People" / "Household.md").exists())


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

    def test_your_edits_of_template_files_survive_an_update(self) -> None:
        views = self.published / "Views"
        board = (views / "Board.base").read_text(encoding="utf-8")
        calendar = (views / "Calendar.base").read_text(encoding="utf-8")
        lists = (views / "Lists.base").read_text(encoding="utf-8")
        # The vault edits three views: one the template leaves alone, one the template
        # changes elsewhere in the file, one the template changes on the same line.
        mine_board = board.replace("views:", "views:\n  # our own board tweak", 1)
        mine_calendar = calendar + "# our calendar note\n"
        first = lists.splitlines()[0]
        mine_lists = lists.replace(first, first + "  # ours", 1)
        for name, text in (("Board", mine_board), ("Calendar", mine_calendar), ("Lists", mine_lists)):
            # CRLF on every system, as a Windows checkout or editor writes it: line endings
            # alone must not count as an edit or break the merge.
            (self.vault / "Views" / f"{name}.base").write_bytes(text.replace("\n", "\r\n").encode())
        self.tasks("sync", "-m", "our views")

        (views / "Calendar.base").write_text("# template header\n" + calendar, encoding="utf-8")
        (views / "Lists.base").write_text(lists.replace(first, first + "  # template", 1),
                                          encoding="utf-8")
        (self.published / "AGENTS.md").write_text("new rules\n", encoding="utf-8")
        self.publish("template 2")

        out = self.setup("update").stdout
        read = lambda name: (self.vault / "Views" / f"{name}.base").read_text(encoding="utf-8")
        self.assertEqual(read("Board"), mine_board)
        self.assertIn("kept your edit of Views/Board.base", out)
        self.assertEqual(read("Calendar"), "# template header\n" + mine_calendar)
        self.assertIn("merged your edit of Views/Calendar.base", out)
        self.assertEqual(read("Lists"), mine_lists)
        self.assertIn("kept your version of Views/Lists.base; the template changed it too", out)
        self.assertEqual((self.vault / "AGENTS.md").read_text(encoding="utf-8"), "new rules\n",
                         "files you never edited still take the template's version")
        self.assertEqual(self.git(self.vault, "status", "--porcelain"), "")
        self.assertIn("up to date", self.setup("update", "--check").stdout,
                      "edits you kept are not a pending update")

    def test_update_adds_missing_obsidian_settings_but_keeps_yours(self) -> None:
        settings = '{"folder": "Journal", "format": "YYYY/YYYY-MM-DD"}\n'
        (self.published / ".obsidian").mkdir()
        (self.published / ".obsidian" / "daily-notes.json").write_text(settings, encoding="utf-8")
        self.publish("template 2")
        (self.vault / ".obsidian").mkdir()
        mine = self.tmp / "mine-vault"
        self.run_in(self.tmp, "git", "clone", "-q", str(self.vault), str(mine))
        self.assertIn("added .obsidian/daily-notes.json", self.setup("update").stdout)
        self.assertEqual((self.vault / ".obsidian" / "daily-notes.json").read_text(encoding="utf-8"),
                         settings)

        (self.vault / ".obsidian" / "daily-notes.json").write_text('{"folder": "Days"}\n',
                                                                   encoding="utf-8")
        self.tasks("sync", "-m", "my settings")
        (self.published / "README.md").write_text("v3\n", encoding="utf-8")
        self.publish("template 3")
        self.setup("update")
        self.assertEqual((self.vault / ".obsidian" / "daily-notes.json").read_text(encoding="utf-8"),
                         '{"folder": "Days"}\n', "your own Obsidian settings are never replaced")

    def test_sync_says_when_the_template_has_an_update(self) -> None:
        self.assertNotIn("update available", self.tasks("sync").stdout)
        self.publish("template 2")
        self.assertIn("template update available", self.tasks("sync").stdout)
        self.setup("update")
        self.assertNotIn("update available", self.tasks("sync").stdout)

    def test_with_release_tags_vaults_take_the_newest_release_not_main(self) -> None:
        self.publish("template 2")
        self.git(self.published, "tag", "-a", "v9.9.9", "-m", "release")
        (self.published / "AGENTS.md").write_text("# work in progress\n", encoding="utf-8")
        (self.published / "VERSION").write_text("10.0.0-dev\n", encoding="utf-8")
        self.git(self.published, "commit", "-qam", "unreleased work on main")

        self.assertIn("template update available", self.tasks("sync").stdout)
        self.setup("update")
        self.assertEqual((self.vault / "VERSION").read_text(encoding="utf-8").strip(), "9.9.9")
        self.assertNotIn("work in progress", (self.vault / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertNotIn("update available", self.tasks("sync").stdout,
                         "unreleased commits on main are not an update")

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


class TestPeriods(unittest.TestCase):
    """Goal periods: years, months and ISO weeks (no vault needed)."""

    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(TEMPLATE / "tools"))
        import goals
        cls.g = goals

    def test_ranges(self) -> None:
        D = dt.date
        p = self.g.parse_period
        self.assertEqual(p("2026"), ("year", D(2026, 1, 1), D(2026, 12, 31)))
        self.assertEqual(p("2026-02"), ("month", D(2026, 2, 1), D(2026, 2, 28)))
        self.assertEqual(p("2026-W47"), ("week", D(2026, 11, 16), D(2026, 11, 22)))
        self.assertEqual(p("2026-W53"), ("week", D(2026, 12, 28), D(2027, 1, 3)))
        self.assertEqual(p("2027-W01"), ("week", D(2027, 1, 4), D(2027, 1, 10)))
        for bad in ("2025-W53", "2026-W00", "2026-13", "2026-00", "26-11", "2026-11-01", "", None):
            with self.subTest(bad=bad):
                self.assertIsNone(p(bad))

    def test_contains(self) -> None:
        c = self.g.contains
        for outer, inner in (("2026", "2026-11"), ("2026", "2026-W47"), ("2026-11", "2026-W47"),
                             ("2026-12", "2026-W49"), ("2026", "2026-W53")):
            with self.subTest(outer=outer, inner=inner):
                self.assertTrue(c(outer, inner))
        for outer, inner in (("2026-11", "2026-W49"), ("2027", "2026-W53"), ("2026-11", "2026-11"),
                             ("2026-W47", "2026-11"), ("2025", "2026-11"), ("2026", "nonsense")):
            with self.subTest(outer=outer, inner=inner):
                self.assertFalse(c(outer, inner))

    def test_default_review_period(self) -> None:
        D, d = dt.date, self.g.default_period
        self.assertEqual(d("month", D(2026, 11, 15)), "2026-10")
        self.assertEqual(d("month", D(2026, 11, 29)), "2026-11")
        self.assertEqual(d("week", D(2026, 11, 15)), "2026-W46")
        self.assertEqual(d("week", D(2026, 11, 18)), "2026-W46")
        self.assertEqual(d("year", D(2026, 11, 15)), "2025")
        self.assertEqual(d("year", D(2026, 12, 30)), "2026")
        self.assertEqual(self.g.current_periods(D(2026, 11, 15)), ["2026-W46", "2026-11", "2026"])


class GoalTest(VaultTest):
    """Helpers for the goal tests: a vault with Anna, Ben and Household."""

    def setUp(self) -> None:
        super().setUp()
        self.setup("init", "--people", "Anna, Ben", "--yes", "--agents", "none")
        self.today = dt.date.today()
        self.month = self.today.strftime("%Y-%m")

    def goal(self, *args: str, ok: bool = True):
        return self.tasks("goal", *args, ok=ok)

    def read(self, name: str) -> str:
        return (self.vault / "Goals" / f"{name}.md").read_text(encoding="utf-8")

    def task_text(self, name: str) -> str:
        return (self.vault / "Tasks" / f"{name}.md").read_text(encoding="utf-8")

    def write_task(self, name: str, front: str) -> Path:
        path = self.vault / "Tasks" / f"{name}.md"
        path.write_text(f"---\ntitle: {name}\n{front.strip()}\ntags:\n  - task\n---\n",
                        encoding="utf-8")
        return path


class TestGoals(GoalTest):
    def test_household_note_stays_and_example_goals_go(self) -> None:
        self.assertTrue((self.vault / "People" / "Household.md").exists())
        self.assertFalse(list((self.vault / "Goals").glob("*.md")))

    def test_new_goal_writes_the_fields(self) -> None:
        out = self.goal("new", "Read 12 books", "--period", "2026", "--owner", "anna",
                        "--target", "12", "--unit", "books", "-m", "one a month").stdout.strip()
        self.assertEqual(out, "Goals/Read 12 books.md")
        text = self.read("Read 12 books")
        for line in ("title: Read 12 books", "type: goal", "period: 2026", 'owner: "[[Anna]]"',
                     "status: active", "target: 12", "progress: 0", "unit: books",
                     "dateModified: ", "  - goal", "one a month", "created for 2026"):
            self.assertIn(line, text)
        self.assertNotIn("  - task", text)

    def test_parent_must_be_a_longer_period_that_contains_it(self) -> None:
        self.goal("new", "Read 12 books", "--period", "2026", "--owner", "Anna")
        self.goal("new", "Finish Dune", "--period", "2026-11", "--owner", "Anna",
                  "--parent", "Read 12")
        self.assertIn('parent: "[[Read 12 books]]"', self.read("Finish Dune"))
        bad = self.goal("new", "Old", "--period", "2025-11", "--owner", "Anna",
                        "--parent", "Read 12 books", ok=False)
        self.assertIn("cannot be the parent", bad.stderr)
        bad = self.goal("new", "X", "--period", "2026-W99", "--owner", "Anna", ok=False)
        self.assertIn("period must be", bad.stderr)
        bad = self.goal("new", "X", "--period", "2026", "--owner", "Nobody", ok=False)
        self.assertIn("no note in People", bad.stderr)

    def test_same_title_in_another_period_gets_its_own_file(self) -> None:
        self.goal("new", "Gym three times", "--period", "2026-W47", "--owner", "Household")
        out = self.goal("new", "Gym three times", "--period", "2026-W48",
                        "--owner", "Household").stdout.strip()
        self.assertEqual(out, "Goals/Gym three times (2026-W48).md")
        self.assertIn("title: Gym three times\n", self.read("Gym three times (2026-W48)"))

    def test_set_status_records_the_date_and_the_log(self) -> None:
        self.goal("new", "Paint", "--period", "2026-11", "--owner", "Household")
        self.goal("set", "Paint", "status=dropped", "-m", "moving in spring")
        text = self.read("Paint")
        self.assertIn("status: dropped", text)
        self.assertIn("completedDate: ", text)
        self.assertIn("status -> dropped: moving in spring", text)
        self.goal("set", "Paint", "status=active")
        self.assertNotIn("completedDate", self.read("Paint"))
        bad = self.goal("set", "Paint", "status=finished", ok=False)
        self.assertIn("unknown goal status", bad.stderr)

    def test_blocked_by_another_goal(self) -> None:
        self.goal("new", "Save the deposit", "--period", "2026", "--owner", "Household")
        self.goal("new", "Buy the car", "--period", "2026", "--owner", "Household",
                  "--blocked-by", "Save the deposit")
        self.assertIn('  - uid: "[[Save the deposit]]"', self.read("Buy the car"))
        self.goal("set", "Buy the car", "--unblock", "Save the deposit")
        self.assertNotIn("blockedBy", self.read("Buy the car"))

    def test_tasks_count_toward_goals(self) -> None:
        self.goal("new", "Repaint the hallway", "--period", self.month, "--owner", "Household")
        self.tasks("new", "Buy paint", "--assignee", "Anna", "--project", "Home",
                   "--goal", "Repaint")
        self.assertIn('  - "[[Home]]"\n  - "[[Repaint the hallway]]"', self.task_text("Buy paint"))
        self.tasks("new", "Paint walls", "--assignee", "Ben")
        self.tasks("link", "Paint walls", "--parent", "Repaint the hallway")
        text = self.task_text("Paint walls")
        self.assertIn('  - "[[Repaint the hallway]]"', text)
        self.assertIn("counts toward [[Repaint the hallway]]", text)
        self.assertEqual(self.tasks("lint").stdout.strip(), "ok")
        bad = self.tasks("new", "X", "--goal", "No such goal", ok=False)
        self.assertIn("cannot pick one goal", bad.stderr)

    def test_household_is_not_an_assignee(self) -> None:
        self.tasks("new", "Shared chore", "--assignee", "Household")
        out = self.tasks("lint", ok=False).stdout
        self.assertIn("Household is for shared goals", out)

    def test_progress_rolls_up_through_the_goal_tree(self) -> None:
        self.goal("new", "Get fit", "--period", "2026", "--owner", "Anna",
                  "--target", "500", "--unit", "km")
        self.goal("new", "Run in November", "--period", "2026-11", "--owner", "Anna",
                  "--parent", "Get fit")
        self.goal("new", "Run week 47", "--period", "2026-W47", "--owner", "Anna",
                  "--parent", "Run in November")
        self.tasks("new", "Buy shoes", "--assignee", "Anna", "--goal", "Run in November")
        self.tasks("new", "Long run", "--assignee", "Anna", "--goal", "Run week 47")
        self.tasks("new", "Old plan", "--assignee", "Anna", "--goal", "Run week 47")
        self.tasks("done", "Buy shoes")
        self.tasks("set", "Old plan", "status=cancelled")
        self.write_task("Saturday run", 'status: todo\nassignee: "[[Anna]]"\nprojects:\n'
                        '  - "[[Run in November]]"\nscheduled: 2026-11-21\n'
                        "recurrence: FREQ=WEEKLY;BYDAY=SA\ncomplete_instances:\n"
                        "  - 2026-10-31\n  - 2026-11-07\n  - 2026-11-14")
        self.goal("progress", "Get fit", "+42.5", "-m", "october runs")
        out = self.goal("show", "Get fit").stdout
        self.assertIn("42.5/500 km (8%)", out)
        self.assertIn("tasks 3/6", out)  # shoes 1/1, long run 0/1, Saturdays 2/4; cancelled left out
        self.assertIn("0 of 1 month goal achieved", out)
        self.assertIn("progress 42.5/500 km: october runs", self.read("Get fit"))
        out = self.goal("show", "Run in November").stdout
        self.assertIn("Saturday run (2/4 this period)", out)
        self.assertIn("0 of 1 week goal achieved", out)
        self.assertIn("Run week 47 | tasks 0/1", self.tasks("goals", "--period", "2026-W47").stdout)
        self.goal("progress", "Get fit", "=10")
        self.goal("progress", "Get fit", "-2")
        self.assertIn("progress: 8\n", self.read("Get fit"))
        bad = self.goal("progress", "Run week 47", "+1", ok=False)
        self.assertIn("has no number target", bad.stderr)

    def test_goals_lists_the_current_periods_by_owner(self) -> None:
        year, week, _ = self.today.isocalendar()
        self.goal("new", "Weekly", "--period", f"{year}-W{week:02d}", "--owner", "Ben")
        self.goal("new", "Monthly", "--period", self.month, "--owner", "Household")
        self.goal("new", "Ancient goal", "--period", "2020", "--owner", "Anna")
        out = self.tasks("goals").stdout
        self.assertIn("Ben:", out)
        self.assertIn("Household:", out)
        self.assertLess(out.index("Ben:"), out.index("Household:"))
        self.assertIn("Weekly", out)
        self.assertNotIn("Ancient goal", out)
        self.assertIn("Ancient goal", self.tasks("goals", "--all").stdout)
        self.assertNotIn("Weekly", self.tasks("goals", "--owner", "Household").stdout)
        self.assertIn("Monthly", self.tasks("goals", "--month").stdout)
        self.assertNotIn("Weekly", self.tasks("goals", "--month").stdout)

    def test_lint_checks_goals(self) -> None:
        folder = self.vault / "Goals"
        folder.mkdir(exist_ok=True)
        (folder / "Broken.md").write_text(
            '---\ntitle: Broken\nperiod: 2026-14\nowner: "[[Nobody]]"\nstatus: done\n'
            'parent: "[[Missing]]"\ntarget: lots\nblockedBy:\n  - uid: "[[Ghost]]"\n'
            "    reltype: FINISHTOSTART\ntags:\n  - goal\n---\n", encoding="utf-8")
        out = self.tasks("lint", ok=False).stdout
        for message in ("period '2026-14' is not", "owner 'Nobody' has no note", "status 'done' is not",
                        "parent 'Missing' is not a goal", "target 'lots' is not a number",
                        "blockedBy 'Ghost' is not a goal"):
            self.assertIn(message, out)
        (folder / "Broken.md").unlink()
        self.goal("new", "Year", "--period", "2026", "--owner", "Anna")
        self.goal("new", "Month", "--period", "2026-11", "--owner", "Anna", "--parent", "Year")
        month = folder / "Month.md"
        month.write_text(month.read_text(encoding="utf-8").replace("period: 2026-11", "period: 2027-01"),
                         encoding="utf-8")
        self.assertIn("does not contain 2027-01", self.tasks("lint", ok=False).stdout)
        month.unlink()
        self.goal("new", "Last year", "--period", "2025-03", "--owner", "Anna")
        out = self.tasks("lint").stdout
        self.assertIn("warning: Goals/Last year.md: still active, but 2025-03 ended", out)

    def test_carry_moves_an_unfinished_goal_on(self) -> None:
        self.goal("new", "Get fit", "--period", "2026", "--owner", "Anna")
        self.goal("new", "Repaint", "--period", "2026-11", "--owner", "Household",
                  "--parent", "Get fit", "-m", "hall and stairs")
        self.tasks("new", "Buy paint", "--assignee", "Anna", "--goal", "Repaint")
        self.tasks("done", "Buy paint")
        self.tasks("new", "Paint walls", "--assignee", "Anna", "--goal", "Repaint")
        out = self.goal("carry", "Repaint", "--to", "2026-12").stdout
        self.assertIn("Goals/Repaint (2026-12).md", out)
        self.assertIn("1 open task(s) now count toward Repaint (2026-12)", out)
        new, old = self.read("Repaint (2026-12)"), self.read("Repaint")
        for piece in ("period: 2026-12", "status: active", "hall and stairs",
                      'parent: "[[Get fit]]"', "carried over from [[Repaint]] (2026-11)"):
            self.assertIn(piece, new)
        self.assertIn("status: partial", old)
        self.assertIn("carried over to [[Repaint (2026-12)]]", old)
        self.assertIn('"[[Repaint (2026-12)]]"', self.task_text("Paint walls"))
        self.assertNotIn('"[[Repaint]]"', self.task_text("Paint walls"))
        self.assertIn('"[[Repaint]]"', self.task_text("Buy paint"), "done tasks stay with the old goal")
        out = self.goal("carry", "Repaint (2026-12)", "--to", "2027-01").stdout
        self.assertIn("no longer under Get fit", out)
        self.assertNotIn("parent:", self.read("Repaint (2027-01)"))
        bad = self.goal("carry", "Repaint (2027-01)", "--to", "2027-W05", ok=False)
        self.assertIn("--to must be a later month", bad.stderr)

    def test_list_shows_the_goal_and_find_searches_goals(self) -> None:
        self.goal("new", "Repaint the hallway", "--period", self.month, "--owner", "Household")
        self.tasks("new", "Buy paint", "--assignee", "Anna", "--goal", "Repaint",
                   "--status", "todo", "--scheduled", self.today.isoformat())
        self.assertIn("Buy paint → Repaint the hallway", self.tasks("list", "--when", "today").stdout)
        self.tasks("review", "--period", self.month)
        out = self.tasks("find", "hallway").stdout
        self.assertIn("Goals/Repaint the hallway.md", out)
        self.assertIn(f"Reviews/{self.month}.md: ", out)


class TestGoalReviews(GoalTest):
    """The page at the end of a week, month or year."""

    def test_month_review_page(self) -> None:
        self.goal("new", "Get fit", "--period", "2026", "--owner", "Anna",
                  "--target", "500", "--unit", "km")
        self.goal("new", "Run 40 km", "--period", "2026-11", "--owner", "Anna", "--parent", "Get fit")
        self.goal("new", "Repaint the hallway", "--period", "2026-11", "--owner", "Household",
                  "--project", "Home")
        self.goal("new", "Learn Spanish", "--period", "2026-11", "--owner", "Ben")
        self.goal("set", "Repaint the hallway", "status=achieved")
        self.write_task("Buy paint", 'status: done\nassignee: "[[Anna]]"\nprojects:\n  - "[[Home]]"\n'
                        '  - "[[Repaint the hallway]]"\ncompletedDate: 2026-11-12')
        self.write_task("Long run", 'status: todo\nassignee: "[[Anna]]"\nprojects:\n'
                        '  - "[[Run 40 km]]"\nscheduled: 2026-11-29')
        page = self.vault / "Journal" / "2026" / "2026-11-12.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("---\ndate: 2026-11-12\ntags:\n  - journal\n---\n"
                        "- 18:40 — bought paint, Repaint the hallway is on track\n"
                        "- 19:00 — nothing else\n", encoding="utf-8")
        path = self.tasks("review", "--period", "2026-11").stdout.strip()
        self.assertEqual(path, "Reviews/2026-11.md")
        text = (self.vault / path).read_text(encoding="utf-8")
        for piece in ("period: 2026-11", "  - review", "# November 2026 — review",
                      "### Anna", "### Ben", "### Household",
                      "- ⬜ **Run 40 km** → Get fit · tasks 0/1",
                      "  - open: Long run (scheduled 2026-11-29",
                      "- ✅ **Repaint the hallway** (Home) · tasks 1/1",
                      "- ⬜ **Learn Spanish** · no tasks linked",
                      "## Year so far (2026)", "- Get fit · 0/500 km (0%)",
                      "## Done this month (1 task)", "- Anna · Home: Buy paint (2026-11-12)",
                      "## Slipped", "- Long run (scheduled 2026-11-29) → Run 40 km",
                      "## From the journal", "- [[2026-11-12]] 18:40 — bought paint",
                      "## Verdicts", "- Repaint the hallway: achieved", "- Run 40 km:\n",
                      "## What worked / what didn't", "## Next month"):
            self.assertIn(piece, text)
        self.assertNotIn("nothing else", text)
        self.assertLess(text.index("### Anna"), text.index("### Ben"))
        self.assertLess(text.index("### Ben"), text.index("### Household"))

    def test_refresh_keeps_what_people_wrote(self) -> None:
        self.goal("new", "Repaint", "--period", "2026-11", "--owner", "Household")
        self.tasks("review", "--period", "2026-11")
        page = self.vault / "Reviews" / "2026-11.md"
        text = page.read_text(encoding="utf-8").replace("- Repaint:", "- Repaint: missed")
        page.write_text(text + "\nThe weather was bad.\n", encoding="utf-8")
        self.goal("new", "Fix the bike", "--period", "2026-11", "--owner", "Ben")
        self.tasks("review", "--period", "2026-11")
        text = page.read_text(encoding="utf-8")
        self.assertIn("- Repaint: missed", text)
        self.assertIn("The weather was bad.", text)
        self.assertIn("**Fix the bike**", text)
        self.assertIn("- Fix the bike:", text)
        self.assertEqual(text.count("<!-- generated"), 1)

    def test_week_and_year_pages(self) -> None:
        self.goal("new", "Get fit", "--period", "2026", "--owner", "Anna")
        self.goal("new", "Run in March", "--period", "2026-03", "--owner", "Anna", "--parent", "Get fit")
        self.goal("set", "Run in March", "status=achieved")
        self.goal("new", "Run in April", "--period", "2026-04", "--owner", "Anna", "--parent", "Get fit")
        self.goal("new", "Gym", "--period", "2026-W47", "--owner", "Ben")
        week = (self.vault / self.tasks("review", "--period", "2026-W47").stdout.strip()).read_text(encoding="utf-8")
        self.assertIn("# Week 47, 2026 — review (16 Nov – 22 Nov)", week)
        self.assertIn("**Gym**", week)
        self.assertIn("## Done this week (0 tasks)\n(nothing finished)", week)
        self.assertNotIn("## From the journal", week)
        self.assertIn("## Next week", week)
        year = (self.vault / self.tasks("review", "--period", "2026").stdout.strip()).read_text(encoding="utf-8")
        self.assertIn("# 2026 — review", year)
        self.assertIn("  - ✅ Run in March (2026-03)", year)
        self.assertIn("## Month by month\nMar 1/1 · Apr 0/1", year)

    def test_apply_sets_verdicts_and_suggests_carrying(self) -> None:
        for name in ("Repaint", "Fix the bike", "Learn Spanish"):
            self.goal("new", name, "--period", "2026-11", "--owner", "Ben")
        self.tasks("review", "--period", "2026-11")
        page = self.vault / "Reviews" / "2026-11.md"
        text = (page.read_text(encoding="utf-8")
                .replace("- Repaint:", "- Repaint: achieved, finally")
                .replace("- Fix the bike:", "- Fix the bike: great")
                .replace("## What worked", "- Unknown goal: missed\n\n## What worked"))
        page.write_text(text, encoding="utf-8")
        out = self.tasks("review", "--period", "2026-11", "--apply")
        self.assertIn("Repaint: active -> achieved", out.stdout)
        self.assertIn("'great' is not one of", out.stderr)
        self.assertIn("no 2026-11 goal called 'Unknown goal'", out.stderr)
        self.assertIn("status: achieved", self.read("Repaint"))
        self.assertIn("verdict from Reviews/2026-11", self.read("Repaint"))
        self.assertIn('goal carry "Fix the bike" --to 2026-12', out.stdout)
        self.assertIn('goal carry "Learn Spanish" --to 2026-12', out.stdout)
        self.assertNotIn('goal carry "Repaint"', out.stdout)
        self.assertIn("- ✅ **Repaint**", page.read_text(encoding="utf-8"))
        self.assertIn("- Repaint: achieved, finally", page.read_text(encoding="utf-8"))


class TestGoalSync(VaultTest):
    def test_two_machines_change_one_goal(self) -> None:
        self.setup("init", "--yes", "--agents", "none", "--people", "Anna",
                   "--remote", str(self.bare("shared")))
        self.tasks("goal", "new", "Read 12 books", "--period", "2026", "--owner", "Anna",
                   "--target", "12")
        self.tasks("sync")
        second = self.tmp / "second"
        self.run_in(self.tmp, "git", "clone", "-q", str(self.tmp / "shared.git"), str(second))
        self.tasks("sync", vault=second)
        self.tasks("goal", "progress", "Read 12 books", "+1", "-m", "Dune")
        self.tasks("goal", "set", "Read 12 books", "unit=books", "-m", "counting books", vault=second)
        self.tasks("sync")
        self.assertIn("synced with origin", self.tasks("sync", vault=second).stdout)
        self.tasks("sync")
        path = Path("Goals") / "Read 12 books.md"
        mine = (self.vault / path).read_text(encoding="utf-8")
        self.assertEqual(mine, (second / path).read_text(encoding="utf-8"))
        for piece in ("progress: 1", "unit: books", "Dune", "counting books"):
            self.assertIn(piece, mine)
        self.assertNotIn("<<<<<<<", mine)
