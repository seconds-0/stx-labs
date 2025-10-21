"""Price helpers for combining Signal21 STX/BTC series."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from .signal21 import fetch_price_series


def load_price_panel(
    start: datetime,
    end: datetime,
    *,
    frequency: str = "1h",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Return merged STX-USD, BTC-USD, and STX/BTC hourly data."""
    stx = fetch_price_series("STX-USD", start, end, frequency=frequency, force_refresh=force_refresh)
    btc = fetch_price_series("BTC-USD", start, end, frequency=frequency, force_refresh=force_refresh)

    df = (
        stx.rename(columns={"px": "stx_usd"})
        .merge(btc.rename(columns={"px": "btc_usd"}), on="ts", how="outer")
        .sort_values("ts")
    )
    df["stx_usd"] = df["stx_usd"].astype(float)
    df["btc_usd"] = df["btc_usd"].astype(float)
    df["stx_usd"] = df["stx_usd"].interpolate(method="time")
    df["btc_usd"] = df["btc_usd"].interpolate(method="time")
    df["stx_btc"] = df["stx_usd"] / df["btc_usd"]
    return df
