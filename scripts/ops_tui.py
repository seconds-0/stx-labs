#!/usr/bin/env python3
"""Rich-powered TUI for monitoring ops_runner jobs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from src import ops_tasks
from src.ops_events import EVENT_PREFIX

REFRESH_INTERVAL = 1.0
STALE_THRESHOLD_SECONDS = 60
TAIL_BYTES = 16384


@dataclass
class ProgressSnapshot:
    percent: float | None
    stage: str | None
    detail: str | None
    event_ts: datetime | None


@dataclass
class LogSnapshot:
    log_path: Path | None
    last_line: str
    progress: ProgressSnapshot | None
    updated_at: datetime | None


@dataclass
class TaskState:
    name: str
    description: str
    running: bool
    start_time: datetime | None
    log: LogSnapshot


def _tmux_available() -> bool:
    return shutil.which("tmux") is not None


def _session_exists(session_name: str) -> bool:
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _tail_lines(path: Path) -> list[str]:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            seek = max(size - TAIL_BYTES, 0)
            handle.seek(seek, os.SEEK_SET)
            chunk = handle.read().decode("utf-8", errors="ignore")
    except FileNotFoundError:
        return []
    return chunk.splitlines()


def _parse_progress(lines: Iterable[str]) -> ProgressSnapshot | None:
    for raw in reversed(list(lines)):
        if not raw.startswith(EVENT_PREFIX):
            continue
        _, payload = raw.split(" ", 1)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        total = float(data.get("total", 0.0))
        current = float(data.get("current", 0.0))
        if total <= 0:
            continue
        percent = max(0.0, min(1.0, current / total))
        ts = _parse_iso(data.get("timestamp"))
        return ProgressSnapshot(
            percent=percent,
            stage=str(data.get("stage")),
            detail=str(data.get("detail", "")),
            event_ts=ts,
        )
    return None


def _log_snapshot(path: Path | None) -> LogSnapshot:
    if path is None:
        return LogSnapshot(None, "", None, None)
    lines = _tail_lines(path)
    last_line = ""
    for line in reversed(lines):
        stripped = line.strip()
        if stripped:
            last_line = stripped
            break
    progress = _parse_progress(lines)
    try:
        updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except FileNotFoundError:
        updated_at = None
    return LogSnapshot(path, last_line, progress, updated_at)


def _load_task_state(name: str, config: ops_tasks.TaskConfig) -> TaskState:
    session = ops_tasks.session_name(name)
    running = _session_exists(session)
    meta = _read_json(ops_tasks.meta_path(name))
    log_path = Path(meta["log_path"]) if meta and "log_path" in meta else None
    start_time = _parse_iso(meta.get("started_at") if meta else None)
    log = _log_snapshot(log_path)
    return TaskState(
        name=name,
        description=config.description,
        running=running,
        start_time=start_time,
        log=log,
    )


def _format_elapsed(start: datetime | None) -> str:
    if not start:
        return "--"
    delta = datetime.now(timezone.utc) - start
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _progress_renderable(progress: ProgressSnapshot | None) -> Columns | Text:
    if not progress or progress.percent is None:
        return Text("--", style="dim")
    bar = ProgressBar(total=100, completed=int(progress.percent * 100), width=20)
    percent_text = Text(f"{progress.percent * 100:5.1f}%", style="bold white")
    return Columns([bar, percent_text], expand=False)


def _activity_text(state: TaskState) -> Text:
    if state.log.progress and state.log.progress.detail:
        return Text(state.log.progress.detail, style="cyan")
    if state.log.last_line:
        return Text(state.log.last_line, style="magenta")
    return Text("No logs yet", style="dim")


def _status_text(state: TaskState, now: datetime) -> Text:
    if state.running:
        updated = state.log.updated_at or state.start_time or now
        idle_seconds = (now - updated).total_seconds()
        if idle_seconds > STALE_THRESHOLD_SECONDS:
            return Text(
                f"RUNNING (idle {int(idle_seconds)}s)",
                style="bold yellow",
            )
        spinner = Spinner("line", text="RUNNING", style="green")
        return spinner
    return Text("IDLE", style="dim")


def _build_table(states: list[TaskState]) -> Table:
    now = datetime.now(timezone.utc)
    table = Table(
        title="Ops Monitor",
        box=box.SIMPLE_HEAVY,
        expand=True,
        header_style="bold blue",
    )
    table.add_column("Task", style="bold")
    table.add_column("Status")
    table.add_column("Started (UTC)")
    table.add_column("Elapsed")
    table.add_column("Progress")
    table.add_column("Activity / Download")

    for state in states:
        start_str = state.start_time.strftime("%H:%M:%S") if state.start_time else "--"
        row = [
            f"{state.name}\n[dim]{state.description}[/]",
            _status_text(state, now),
            start_str,
            _format_elapsed(state.start_time),
            _progress_renderable(state.log.progress),
            _activity_text(state),
        ]
        table.add_row(*row)
    return table


def run_monitor() -> None:
    if not _tmux_available():
        Console().print("[red]tmux not found on PATH. Install tmux to monitor jobs.[/]")
        raise SystemExit(1)
    console = Console()
    task_names = list(ops_tasks.DEFAULT_TASKS.keys())
    with Live(console=console, refresh_per_second=4) as live:
        try:
            while True:
                states = [_load_task_state(name, ops_tasks.DEFAULT_TASKS[name]) for name in task_names]
                live.update(_build_table(states))
                time.sleep(REFRESH_INTERVAL)
        except KeyboardInterrupt:
            console.print("\nExiting ops monitor.")


if __name__ == "__main__":
    run_monitor()
