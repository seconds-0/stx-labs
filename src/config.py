"""Configuration helpers for Stacks PoX flywheel analysis."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path("data")
RAW_DATA_DIR = DATA_DIR / "raw"
CACHE_DIR = DATA_DIR / "cache"
OUT_DIR = Path("out")
DUCKDB_PATH = CACHE_DIR / "wallet_metrics.duckdb"

DEFAULT_WINDOWS: Sequence[int] = (30, 90, 180)

SIGNAL21_BASE = os.getenv("SIGNAL21_BASE", "https://api-test.signal21.io")
HIRO_BASE = os.getenv("HIRO_BASE", "https://api.hiro.so")
COINGECKO_BASE = os.getenv("COINGECKO_BASE", "https://api.coingecko.com/api/v3")

HIRO_API_KEY_ENV = "HIRO_API_KEY"
COINGECKO_API_KEY = os.getenv("COIN_GECKO_KEY")

RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)
DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class RetryConfig:
    """Settings for HTTP retry/backoff behaviour."""

    wait_min_seconds: float = 0.5
    wait_max_seconds: float = 8.0
    max_attempts: int = 5
    status_forcelist: tuple[int, ...] = field(
        default_factory=lambda: (429, 500, 502, 503, 504, 522, 525)
    )


DEFAULT_RETRY_CONFIG = RetryConfig()


def resolve_cache_path(prefix: str, key: str, suffix: str = ".json") -> Path:
    """Return a deterministic cache path under data/raw for a given key."""
    sanitized_prefix = prefix.replace("/", "_")
    filename = f"{sanitized_prefix}_{key}{suffix}"
    return RAW_DATA_DIR / filename


def default_date_horizon_days() -> int:
    """Default number of days to request when no explicit horizon supplied."""
    env_value = os.getenv("DEFAULT_HISTORY_DAYS")
    if env_value:
        try:
            return int(env_value)
        except ValueError:
            pass
    return 365
