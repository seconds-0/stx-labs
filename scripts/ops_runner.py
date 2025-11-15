#!/usr/bin/env python3
"""tmux-based task launcher for long running wallet/ROI jobs.

This helper keeps heavy commands out of the interactive terminal by spawning
them inside dedicated tmux sessions while mirroring stdout/stderr into log
files under logs/ops_runner/<task>. Each task can be tailed or queried for
status without attaching to the process directly.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import ops_tasks

REPO_ROOT = ops_tasks.REPO_ROOT
LOG_ROOT = ops_tasks.LOG_ROOT

TaskName = str
TASKS = ops_tasks.DEFAULT_TASKS


def _tmux_available() -> bool:
    return shutil.which("tmux") is not None


def _session_name(task: TaskName) -> str:
    return f"ops-{task}"


def _ensure_log_dir(task: TaskName) -> Path:
    path = LOG_ROOT / task
    path.mkdir(parents=True, exist_ok=True)
    return path


def _latest_meta(task: TaskName) -> dict | None:
    meta_path = LOG_ROOT / task / "latest.json"
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text())


def _write_meta(task: TaskName, log_path: Path, command: str) -> None:
    meta = {
        "task": task,
        "command": command,
        "log_path": str(log_path),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    (LOG_ROOT / task / "latest.json").write_text(json.dumps(meta, indent=2))


def _session_exists(session: str) -> bool:
    result = subprocess.run(
        ["tmux", "has-session", "-t", session],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _run_tmux(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def list_tasks(tasks: dict[TaskName, ops_tasks.TaskConfig]) -> None:
    for name, payload in tasks.items():
        print(f"{name:>15}  {payload.description}")


def start_task(task: TaskName, extra_args: Iterable[str]) -> None:
    if task not in TASKS:
        print(f"Unknown task '{task}'. Use 'tasks' to list available jobs.", file=sys.stderr)
        sys.exit(1)
    if not _tmux_available():
        print("tmux is required but not found in PATH.", file=sys.stderr)
        sys.exit(1)
    session = _session_name(task)
    if _session_exists(session):
        print(f"Session {session} already running. Attach with: tmux attach -t {session}")
        return

    base_command = TASKS[task].command
    if extra_args:
        base_command = f"{base_command} {' '.join(extra_args)}"
    log_dir = _ensure_log_dir(task)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{timestamp}.log"
    _write_meta(task, log_path, base_command)
    log_path_quoted = shlex.quote(str(log_path))
    env_prefix = f"OPS_TASK={shlex.quote(task)} "
    command_with_logging = f"({env_prefix}{base_command}) 2>&1 | tee -a {log_path_quoted}"
    shell_cmd = (
        f"cd {REPO_ROOT} && "
        "source .venv/bin/activate && "
        "set -o pipefail && "
        f"{command_with_logging}"
    )
    result = _run_tmux(
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            session,
            "bash",
            "-lc",
            shell_cmd,
        ]
    )
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        sys.exit(result.returncode)
    print(f"Launched {task} in tmux session '{session}'.")
    print(f"Log: {log_path}")
    print(f"Attach with: tmux attach -t {session}")
    print(f"Tail logs with: python scripts/ops_runner.py tail {task}")


def stop_task(task: TaskName) -> None:
    session = _session_name(task)
    if not _session_exists(session):
        print(f"No running session for '{task}'.")
        return
    result = _run_tmux(["tmux", "kill-session", "-t", session])
    if result.returncode == 0:
        print(f"Stopped session {session}.")
    else:
        print(result.stderr.strip(), file=sys.stderr)


def status(task: TaskName | None) -> None:
    names = [task] if task else sorted(TASKS.keys())
    for name in names:
        session = _session_name(name)
        exists = _session_exists(session)
        meta = _latest_meta(name)
        log_path = Path(meta["log_path"]) if meta else None
        started = meta["started_at"] if meta else "unknown"
        line = f"{name:>15}: {'RUNNING' if exists else 'idle'}"
        if exists:
            line += f" (session {session})"
        line += f", last start: {started}"
        if log_path and log_path.exists():
            try:
                last_line = log_path.read_text().rstrip().splitlines()[-1]
                line += f", last log: {last_line[:120]}"
            except IndexError:
                pass
        print(line)


def tail_logs(task: TaskName, lines: int, follow: bool) -> None:
    meta = _latest_meta(task)
    if meta is None:
        print(f"No log metadata for task '{task}'. Start the task first.", file=sys.stderr)
        sys.exit(1)
    log_path = Path(meta["log_path"])
    if not log_path.exists():
        print(f"Log file not found at {log_path}", file=sys.stderr)
        sys.exit(1)
    tail_cmd = ["tail", f"-n{lines}"]
    if follow:
        tail_cmd.append("-f")
    tail_cmd.append(str(log_path))
    subprocess.run(tail_cmd, check=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("tasks", help="List available predefined tasks.")

    start_parser = sub.add_parser("start", help="Launch a task in a detached tmux session.")
    start_parser.add_argument("task", help="Task name to run.")
    start_parser.add_argument("extra", nargs=argparse.REMAINDER, help="Extra args appended to the underlying command.")

    stop_parser = sub.add_parser("stop", help="Stop a running task/session.")
    stop_parser.add_argument("task")

    status_parser = sub.add_parser("status", help="Show task/session status.")
    status_parser.add_argument("task", nargs="?", help="Optional specific task.")

    tail_parser = sub.add_parser("tail", help="Tail the latest log for a task.")
    tail_parser.add_argument("task")
    tail_parser.add_argument("--lines", type=int, default=40, help="Number of lines to show (default: 40).")
    tail_parser.add_argument("--follow", action="store_true", help="Follow logs (tail -f).")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "tasks":
        list_tasks(TASKS)
    elif args.command == "start":
        start_task(args.task, args.extra)
    elif args.command == "stop":
        stop_task(args.task)
    elif args.command == "status":
        status(args.task)
    elif args.command == "tail":
        tail_logs(args.task, args.lines, args.follow)
    else:  # pragma: no cover - argparse should prevent this
        print(f"Unknown command {args.command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
