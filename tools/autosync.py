#!/usr/bin/env python3
"""Keep the vault in sync automatically: `tasks.py sync` every few minutes, on any computer.

    python3 tools/autosync.py status        scheduled here? last result, conflicts, duplicate jobs
    python3 tools/autosync.py install [--interval 5]
    python3 tools/autosync.py uninstall     stop it on this machine (setup won't re-add it)
    python3 tools/autosync.py run           one sync now; this is what the schedule runs

`setup.py init` and `setup.py connect` install it by default (`--no-autosync` to skip),
and a machine that takes a template update through `sync` gets it the same way. Edits made
with `tasks.py` already sync right away; this catches everything else: Obsidian edits,
hand edits, and changes that could not be pushed earlier (offline).

Scheduler per system: macOS launchd agent (at login, then every 5 min), Linux systemd user
timer (cron when there is no systemd), Windows Task Scheduler. Each run calls
`tasks.py sync --no-wait`: a sync already in progress makes the run a no-op. Task files that
two machines changed are merged by tasks.py; any other clash stops that machine's sync with
nothing pushed, and this script shows a notification once, and again when it recovers.
Offline runs are skipped quietly. Log and state are per machine, in .git/autosync/.
Standard library only; `python` instead of `python3` on Windows.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "tools" / "tasks.py"
ME = Path(__file__).resolve()
DATA = ROOT / ".git" / "autosync"
LOG, STATE, OPTED_OUT = DATA / "autosync.log", DATA / "state", DATA / "disabled"
VAULT_ID = hashlib.sha1(str(ROOT).encode()).hexdigest()[:6]
NAME = f"task-vault-autosync-{VAULT_ID}"           # systemd units, Windows task, cron mark
LABEL = f"com.task-vault.autosync.{VAULT_ID}"      # launchd
CRON_MARK = f"# {NAME}"
SYSTEM = platform.system()                          # Darwin, Linux, Windows
HOST = platform.node().split(".")[0] or "computer"
DEFAULT_INTERVAL = 5

# Failures that fix themselves: retried next run without a notification.
TRANSIENT = ("Could not resolve host", "Failed to connect", "unable to access",
             "Connection timed out", "Network is unreachable", "Operation timed out",
             "Temporary failure in name resolution", "index.lock", "another sync is running")


def say(msg: str = "") -> None:
    print(msg, flush=True)


def sh(*cmd: str, input: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, input=input)
    except OSError as e:  # the tool is missing
        return subprocess.CompletedProcess(list(cmd), 127, "", str(e))


def scheduling_allowed() -> bool:
    """TASK_VAULT_SCHEDULER=0 turns scheduling off (the template's tests set it)."""
    return os.environ.get("TASK_VAULT_SCHEDULER", "1") != "0"


def is_vault() -> bool:
    """A vault made by setup.py, not the template repository itself."""
    return (ROOT / ".task-vault.json").exists() and (ROOT / ".git").is_dir()


# --- run ----------------------------------------------------------------------

def log(line: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {line}\n")
    lines = LOG.read_text(encoding="utf-8").splitlines()
    if len(lines) > 2000:
        LOG.write_text("\n".join(lines[-1000:]) + "\n", encoding="utf-8")


def notify(message: str) -> None:
    """Best-effort desktop notification; never fails the run."""
    title = "Task vault"
    if os.environ.get("TASK_VAULT_AUTOSYNC_QUIET"):  # tests
        log(f"(notification) {message}")
        return
    try:
        if SYSTEM == "Darwin":
            safe = message.replace('"', "'")
            sh("/usr/bin/osascript", "-e", f'display notification "{safe}" with title "{title}"')
        elif SYSTEM == "Linux" and shutil.which("notify-send"):
            sh("notify-send", title, message)
        elif SYSTEM == "Windows":
            safe = message.replace("'", "''")
            ps = ("Add-Type -AssemblyName System.Windows.Forms;"
                  "$n=New-Object System.Windows.Forms.NotifyIcon;"
                  "$n.Icon=[System.Drawing.SystemIcons]::Information;$n.Visible=$true;"
                  f"$n.ShowBalloonTip(10000,'{title}','{safe}',"
                  "[System.Windows.Forms.ToolTipIcon]::Info);Start-Sleep 11;$n.Dispose()")
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        pass


def job_path() -> str:
    """PATH for the scheduled job: the folders of the git and gh this user runs, then the
    usual places, then the rest. Schedulers start jobs with a bare PATH where `git` can be
    a stub that doesn't work (macOS: /usr/bin/git before the Xcode license is accepted)."""
    first = [str(Path(found).parent) for found in (shutil.which("git"), shutil.which("gh")) if found]
    usual = ["/opt/homebrew/bin", "/usr/local/bin"] if SYSTEM != "Windows" else []
    rest = os.environ.get("PATH", "").split(os.pathsep)
    out: list[str] = []
    for folder in first + usual + rest:
        if folder and folder not in out and os.path.isdir(folder):
            out.append(folder)
    return os.pathsep.join(out)


def cmd_run(args) -> int:
    env = dict(os.environ, TASK_VAULT_AUTOSYNC_RUN="1", PATH=job_path())
    result = subprocess.run([sys.executable, str(TASKS), "sync", "--no-wait",
                             "-m", f"Auto-sync from {HOST}"],
                            capture_output=True, text=True, env=env, cwd=str(ROOT))
    out = " | ".join((result.stdout + result.stderr).strip().splitlines())
    previous = STATE.read_text(encoding="utf-8").strip() if STATE.exists() else ""
    if result.returncode == 0:
        if "committed:" in out or "template" in out:
            log(f"ok: {out}")
        if previous == "failed":
            log("recovered")
            notify("Back in sync.")
        DATA.mkdir(parents=True, exist_ok=True)
        STATE.write_text("ok\n", encoding="utf-8")
    elif any(t in out for t in TRANSIENT):
        log(f"skipped (offline or busy): {out}")
    else:
        log(f"FAILED: {out}")
        if previous != "failed":
            notify("Sync stopped, likely a conflict. Run: python3 tools/autosync.py status")
        STATE.write_text("failed\n", encoding="utf-8")
    if getattr(args, "verbose", False):
        say(out)
    return 0


# --- schedulers ---------------------------------------------------------------

def python_for_schedule() -> str:
    exe = Path(sys.executable)
    if SYSTEM == "Windows":
        quiet = exe.with_name("pythonw.exe")   # no console window every few minutes
        if quiet.exists():
            return str(quiet)
    return str(exe)


def launchd_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def systemd_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user"


def has_systemd_user() -> bool:
    return shutil.which("systemctl") is not None and \
        sh("systemctl", "--user", "show-environment").returncode == 0


def launchd_plist(interval: int) -> bytes:
    return plistlib.dumps({
        "Label": LABEL, "ProgramArguments": [python_for_schedule(), str(ME), "run"],
        "EnvironmentVariables": {"HOME": str(Path.home()), "PATH": job_path()},
        "StartInterval": interval * 60, "RunAtLoad": True,
        "ProcessType": "Background", "LowPriorityIO": True,
        "StandardOutPath": str(DATA / "launchd.log"), "StandardErrorPath": str(DATA / "launchd.log"),
    })


def install_launchd(interval: int) -> str:
    path, uid, wanted = launchd_path(), os.getuid(), launchd_plist(interval)
    loaded = sh("/bin/launchctl", "print", f"gui/{uid}/{LABEL}").returncode == 0
    if loaded and path.exists() and path.read_bytes() == wanted:
        return "already"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wanted)
    reload = (f"/bin/launchctl bootout gui/{uid}/{LABEL} 2>/dev/null; sleep 1; "
              f"/bin/launchctl bootstrap gui/{uid} '{path}'")
    if os.environ.get("TASK_VAULT_AUTOSYNC_RUN"):
        # Called from inside this job (an update arrived through a scheduled sync): bootout
        # would kill us mid-run, so reload from a detached shell once we are done.
        subprocess.Popen(["/bin/sh", "-c", f"sleep 20; {reload}"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "updated (reloads in a moment)"
    r = sh("/bin/sh", "-c", reload)
    if sh("/bin/launchctl", "print", f"gui/{uid}/{LABEL}").returncode != 0:
        sys.exit(f"launchctl could not load {path}: {(r.stderr or r.stdout).strip()}")
    return "installed"


def install_systemd(interval: int) -> str:
    d = systemd_dir()
    service = (f"[Unit]\nDescription=Task vault auto-sync ({ROOT})\n\n"
               f"[Service]\nType=oneshot\nEnvironment=\"PATH={job_path()}\"\n"
               f"ExecStart=\"{python_for_schedule()}\" \"{ME}\" run\n")
    timer = (f"[Unit]\nDescription=Task vault auto-sync every {interval} min\n\n"
             f"[Timer]\nOnBootSec=1min\nOnUnitActiveSec={interval}min\nPersistent=true\n\n"
             "[Install]\nWantedBy=timers.target\n")
    files = {d / f"{NAME}.service": service, d / f"{NAME}.timer": timer}
    same = all(p.exists() and p.read_text(encoding="utf-8") == t for p, t in files.items())
    active = sh("systemctl", "--user", "is-active", f"{NAME}.timer").stdout.strip() == "active"
    if same and active:
        return "already"
    d.mkdir(parents=True, exist_ok=True)
    for p, t in files.items():
        p.write_text(t, encoding="utf-8")
    sh("systemctl", "--user", "daemon-reload")
    r = sh("systemctl", "--user", "enable", "--now", f"{NAME}.timer")
    if r.returncode != 0:
        sys.exit(f"systemctl failed: {r.stderr.strip()}")
    linger = sh("loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger").stdout
    if "Linger=yes" not in linger and sh("loginctl", "enable-linger").returncode != 0:
        say("note: it runs while you are logged in. To run it from boot with nobody logged "
            "in (a server): sudo loginctl enable-linger $USER")
    return "installed"


def install_cron(interval: int) -> str:
    py = python_for_schedule()
    current = sh("crontab", "-l").stdout
    keep = [l for l in current.splitlines() if CRON_MARK not in l]
    run = f"PATH='{job_path()}' \"{py}\" \"{ME}\" run"
    ours = [f"*/{interval} * * * * {run} {CRON_MARK}",
            f"@reboot sleep 60 && {run} {CRON_MARK}"]
    if [l for l in current.splitlines() if CRON_MARK in l] == ours:
        return "already"
    r = sh("crontab", "-", input="\n".join(keep + ours) + "\n")
    if r.returncode != 0:
        sys.exit(f"crontab failed: {r.stderr.strip()}")
    return "installed"


def install_windows(interval: int) -> str:
    tr = f'"{python_for_schedule()}" "{ME}" run'
    r = sh("schtasks", "/Create", "/F", "/TN", NAME, "/SC", "MINUTE", "/MO", str(interval), "/TR", tr)
    if r.returncode != 0:
        sys.exit(f"schtasks failed: {(r.stderr or r.stdout).strip()}")
    # At logon too; needs rights some accounts lack, and the 5-minute task covers it anyway.
    sh("schtasks", "/Create", "/F", "/TN", f"{NAME}-logon", "/SC", "ONLOGON", "/TR", tr)
    return "installed"


def scheduler_name() -> str:
    if SYSTEM == "Darwin":
        return f"launchd agent {LABEL} (at login, then every {{}} min)"
    if SYSTEM == "Linux":
        return (f"systemd user timer {NAME}.timer (1 min after boot, then every {{}} min)"
                if has_systemd_user() else "cron (at boot, then every {} min)")
    return f"Task Scheduler task {NAME} (every {{}} min while logged in)"


def install(interval: int) -> str:
    """Schedule `run`; returns 'installed', 'already', 'updated ...' or exits with why not."""
    DATA.mkdir(parents=True, exist_ok=True)
    if SYSTEM == "Darwin":
        return install_launchd(interval)
    if SYSTEM == "Linux" and has_systemd_user():
        return install_systemd(interval)
    if SYSTEM == "Linux" and shutil.which("crontab"):
        return install_cron(interval)
    if SYSTEM == "Windows":
        return install_windows(interval)
    sys.exit("no scheduler found (launchd, systemd, cron or Task Scheduler); "
             "run `python3 tools/autosync.py run` from your own scheduler")


def uninstall() -> None:
    if SYSTEM == "Darwin":
        sh("/bin/launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}")
        launchd_path().unlink(missing_ok=True)
    elif SYSTEM == "Linux":
        if shutil.which("systemctl"):
            sh("systemctl", "--user", "disable", "--now", f"{NAME}.timer")
            for ext in ("timer", "service"):
                (systemd_dir() / f"{NAME}.{ext}").unlink(missing_ok=True)
            sh("systemctl", "--user", "daemon-reload")
        if shutil.which("crontab"):
            cur = sh("crontab", "-l").stdout
            if CRON_MARK in cur:
                keep = [l for l in cur.splitlines() if CRON_MARK not in l]
                sh("crontab", "-", input="\n".join(keep) + "\n")
    elif SYSTEM == "Windows":
        sh("schtasks", "/Delete", "/F", "/TN", NAME)
        sh("schtasks", "/Delete", "/F", "/TN", f"{NAME}-logon")


def installed() -> str | None:
    if SYSTEM == "Darwin":
        return f"launchd {LABEL}" if launchd_path().exists() else None
    if SYSTEM == "Linux":
        if (systemd_dir() / f"{NAME}.timer").exists():
            return f"systemd {NAME}.timer"
        if shutil.which("crontab") and CRON_MARK in sh("crontab", "-l").stdout:
            return "cron"
        return None
    if SYSTEM == "Windows":
        return f"Task Scheduler {NAME}" if sh("schtasks", "/Query", "/TN", NAME).returncode == 0 else None
    return None


# --- duplicates ---------------------------------------------------------------

def other_sync_jobs() -> list[str]:
    """Other scheduled things on this machine that sync this vault (two at once collide)."""
    found, needles = [], ("tasks.py sync", str(ROOT), "task-vault-autosync")

    def hit(text: str) -> bool:
        return any(n in text for n in needles) and VAULT_ID not in text and str(ME) not in text

    if shutil.which("crontab"):
        for line in sh("crontab", "-l").stdout.splitlines():
            if hit(line) and not line.lstrip().startswith("#"):
                found.append(f"cron: {line.strip()}")
    folder = {"Darwin": Path.home() / "Library" / "LaunchAgents", "Linux": systemd_dir()}.get(SYSTEM)
    if folder and folder.is_dir():
        for f in sorted(folder.iterdir()):
            try:
                text = f.read_bytes().decode("utf-8", "ignore")
            except OSError:
                continue
            if hit(f.name + text) and VAULT_ID not in f.name:
                found.append(f"{'launchd' if SYSTEM == 'Darwin' else 'systemd'}: {f}")
    if SYSTEM == "Windows":
        for line in sh("schtasks", "/Query", "/FO", "CSV", "/V").stdout.splitlines():
            if hit(line):
                found.append(f"Task Scheduler: {line.split(',')[1].strip(chr(34))}")
    git_plugin = ROOT / ".obsidian" / "plugins" / "obsidian-git" / "data.json"
    if git_plugin.exists():
        text = git_plugin.read_text(encoding="utf-8", errors="ignore")
        if re.search(r'"(autoSaveInterval|autoPullInterval)":\s*[1-9]', text):
            found.append(f"Obsidian Git auto commit/pull is on ({git_plugin}); turn it off on computers")
    return found


def warn_duplicates() -> None:
    jobs = other_sync_jobs()
    if jobs:
        say("WARNING: other jobs on this machine also sync this vault. Keep only one; remove:")
        for j in jobs:
            say(f"  - {j}")
        say("  (an agent's own scheduler, e.g. a Hermes or OpenClaw cron job, is not detected)")


# --- commands -----------------------------------------------------------------

def cmd_install(args) -> int:
    if args.interval < 1:
        sys.exit("--interval must be at least 1 minute")
    if not scheduling_allowed():
        say("auto-sync: not scheduled (TASK_VAULT_SCHEDULER=0)")
        return 0
    OPTED_OUT.unlink(missing_ok=True)
    result = install(args.interval)
    say(f"auto-sync {result}: {scheduler_name().format(args.interval)}")
    warn_duplicates()
    return 0


def cmd_ensure(args) -> int:
    """Install unless this machine opted out; what setup and template updates call. Quiet."""
    if not scheduling_allowed() or not is_vault() or OPTED_OUT.exists():
        return 0
    try:
        result = install(DEFAULT_INTERVAL)
    except SystemExit as e:  # never break setup or sync over this
        say(f"auto-sync not installed: {e.code}")
        return 0
    if result != "already":
        say(f"auto-sync {result}: {scheduler_name().format(DEFAULT_INTERVAL)}")
        say("  (python3 tools/autosync.py uninstall to turn it off on this machine)")
        warn_duplicates()
    return 0


def cmd_uninstall(args) -> int:
    uninstall()
    DATA.mkdir(parents=True, exist_ok=True)
    OPTED_OUT.write_text("turned off by `autosync.py uninstall`; `install` turns it on\n",
                         encoding="utf-8")
    say("auto-sync removed from this machine (setup and updates won't re-add it)")
    return 0


def cmd_status(args) -> int:
    where = installed()
    say(f"vault:     {ROOT}")
    say(f"scheduled: {where or ('NO, turned off here' if OPTED_OUT.exists() else 'NO')}"
        + ("" if where else " - `python3 tools/autosync.py install` turns it on"))
    state = STATE.read_text(encoding="utf-8").strip() if STATE.exists() else "never ran"
    say(f"state:     {state}")
    if LOG.exists():
        say("log (only changes and problems are logged):")
        for line in LOG.read_text(encoding="utf-8").splitlines()[-5:]:
            say(f"  {line}")
    if state == "failed":
        say("\nSync stopped on a conflict git could not merge. In the vault:\n"
            "  git pull --rebase            # names the conflicting files\n"
            "  # edit each: keep both people's changes, delete the <<<<<<< ======= >>>>>>> lines\n"
            "  git add <file> && git rebase --continue\n"
            "  python3 tools/tasks.py sync  # the next scheduled run then says 'Back in sync'\n"
            "Never force-push or reset away someone else's commits.")
    warn_duplicates()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("install", help="schedule auto-sync on this machine")
    p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="minutes (default 5)")
    p.set_defaults(func=cmd_install)
    sub.add_parser("ensure", help=argparse.SUPPRESS).set_defaults(func=cmd_ensure)
    sub.add_parser("uninstall", help="stop it on this machine").set_defaults(func=cmd_uninstall)
    sub.add_parser("status", help="scheduled? last result, duplicate jobs").set_defaults(func=cmd_status)
    p = sub.add_parser("run", help="one sync now (what the schedule runs)")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_run)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
