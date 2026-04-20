"""External CSV loaders for CAC / channel map / incentives.

Restored stub: original source was lost from the tree but the compiled
bytecode remained. Signatures match the pyc; implementations are best-effort
CSV → pandas loaders covering the columns referenced in build_dashboards.py.
These paths are only hit when the operator passes --cac-file / --channel-map-file
/ --incentives-file, so accidental regressions land nowhere the default
dashboard build goes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd


def load_address_channel_map(path: Path) -> pd.DataFrame:
    """CSV with columns: address, activation_date, channel."""
    df = pd.read_csv(path)
    required = {"address", "activation_date", "channel"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"channel-map CSV missing columns: {sorted(missing)}")
    df["activation_date"] = pd.to_datetime(df["activation_date"], utc=True).dt.floor("D")
    df["address"] = df["address"].astype(str)
    df["channel"] = df["channel"].astype(str)
    return df[["address", "activation_date", "channel"]]


def load_cac_by_channel(path: Path) -> Dict[str, float]:
    """CSV with columns: channel, cac_stx."""
    df = pd.read_csv(path)
    required = {"channel", "cac_stx"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CAC CSV missing columns: {sorted(missing)}")
    return {str(row.channel): float(row.cac_stx) for row in df.itertuples(index=False)}


def load_incentives(path: Path) -> pd.DataFrame:
    """CSV with columns: address, paid_date, amount_stx."""
    df = pd.read_csv(path)
    required = {"address", "paid_date", "amount_stx"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"incentives CSV missing columns: {sorted(missing)}")
    df["paid_date"] = pd.to_datetime(df["paid_date"], utc=True).dt.floor("D")
    df["address"] = df["address"].astype(str)
    df["amount_stx"] = df["amount_stx"].astype(float)
    return df[["address", "paid_date", "amount_stx"]]
