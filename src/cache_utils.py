"""Utility helpers for reading/writing cached parquet artefacts."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def read_parquet(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    return df


def write_parquet(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
