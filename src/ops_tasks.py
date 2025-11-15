"""Shared ops-runner task configuration and helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_ROOT = REPO_ROOT / "logs" / "ops_runner"


@dataclass(frozen=True)
class TaskConfig:
    name: str
    description: str
    command: str


DEFAULT_TASKS: dict[str, TaskConfig] = {
    "update-balances": TaskConfig(
        name="update-balances",
        description="Refresh funded wallet balances with conservative rate limiting.",
        command=(
            ".venv/bin/python scripts/update_wallet_balances.py "
            "--max-days 365 --activation-days 30 --delay-seconds 1.5 --batch-size 20 --max-workers 4"
        ),
    ),
    "refresh-cache": TaskConfig(
        name="refresh-cache",
        description="Precompute wallet + ROI aggregates for dashboard builds.",
        command=(
            ".venv/bin/python scripts/refresh_dashboard_cache.py "
            "--wallet-max-days 365 --wallet-windows 15 30 60 90 --roi-windows 15 30 60 90 180"
        ),
    ),
    "build-wallet": TaskConfig(
        name="build-wallet",
        description="Regenerate wallet + value dashboards using the DuckDB snapshot.",
        command=(
            ".venv/bin/python scripts/build_dashboards.py "
            "--wallet-max-days 365 --wallet-windows 15 30 60 90 "
            "--value-windows 15 30 60 90 --wallet-db-snapshot --cpa-target-stx 5"
        ),
    ),
    "build-roi": TaskConfig(
        name="build-roi",
        description="Build only the ROI one-pager with a DuckDB snapshot.",
        command=(
            ".venv/bin/python scripts/build_dashboards.py "
            "--wallet-max-days 365 --wallet-windows 15 30 60 90 "
            "--roi-windows 15 30 60 90 180 --wallet-db-snapshot --one-pager-only"
        ),
    ),
}


def list_task_configs(names: Iterable[str] | None = None) -> list[TaskConfig]:
    if names is None:
        return list(DEFAULT_TASKS.values())
    configs: list[TaskConfig] = []
    for name in names:
        cfg = DEFAULT_TASKS.get(name)
        if cfg is not None:
            configs.append(cfg)
    return configs


def get_task_config(name: str) -> TaskConfig | None:
    return DEFAULT_TASKS.get(name)


def session_name(name: str) -> str:
    return f"ops-{name}"


def task_log_dir(name: str) -> Path:
    path = LOG_ROOT / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def meta_path(name: str) -> Path:
    return task_log_dir(name) / "latest.json"


def log_path(name: str, timestamp: str) -> Path:
    return task_log_dir(name) / f"{timestamp}.log"
