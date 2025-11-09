"""Wallet value modeling (CPI/CPA framing) built atop cached Hiro activity.

This module computes per-wallet Network Value (NV) as fee-denominated revenue
converted to BTC using historical STX/BTC prices, and an initial Wallet
Adjusted Lifetime Value (WALTV) where derived value and incentives are pluggable
extensions. It also classifies wallets into funnel stages (funded, active,
value) using configurable thresholds.

Design goals:
- Rerunnable and delta-friendly: uses existing DuckDB transaction cache
  from `src.wallet_metrics` and price caches from `src.prices`.
- Deterministic windows: compute NV/WALTV for standard 15/30/60/90/180 day windows
  from wallet activation (first non-trivial transaction).
- Extensible: provides hooks for balance lookups (funded threshold) and for
  derived value/incentive adjustments without hitting live services in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable, Mapping, Sequence

import pandas as pd

from . import prices
from . import wallet_metrics
from .hiro import fetch_address_balances


MICROSTX_PER_STX = 1_000_000


@dataclass(frozen=True)
class ClassificationThresholds:
    """Thresholds for funnel classification.

    - funded_stx_min: wallet STX balance threshold to be considered funded.
    - active_min_tx_30d: minimum tx count within 30 days from activation.
    - value_min_fee_stx_30d: minimum fees (STX) within 30 days to be a value wallet.
    """

    funded_stx_min: float = 10.0
    active_min_tx_30d: int = 3
    value_min_fee_stx_30d: float = 1.0


def _as_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def compute_activation(first_seen: pd.DataFrame) -> pd.DataFrame:
    """Return activation timestamps per wallet (first_seen cache).

    Expects columns: address, first_seen (UTC tz-aware timestamp)
    Returns: address, activation_time (UTC), activation_date (UTC date floored)
    """
    if first_seen.empty:
        return pd.DataFrame(columns=["address", "activation_time", "activation_date"])
    df = first_seen.copy()
    df["activation_time"] = pd.to_datetime(df["first_seen"], utc=True)
    df["activation_date"] = df["activation_time"].dt.floor("D")
    return df[["address", "activation_time", "activation_date"]]


def load_price_panel_for_activity(
    activity: pd.DataFrame, *, frequency: str = "1h", force_refresh: bool = False
) -> pd.DataFrame:
    """Load STX/BTC prices spanning the activity range (±1 day margin)."""
    if activity.empty:
        return pd.DataFrame(columns=["ts", "stx_btc"])
    start = _as_utc(pd.to_datetime(activity["block_time"].min(), utc=True)) - timedelta(
        days=1
    )
    end = _as_utc(pd.to_datetime(activity["block_time"].max(), utc=True)) + timedelta(
        days=1
    )
    panel = prices.load_price_panel(
        start, end, frequency=frequency, force_refresh=force_refresh
    )
    panel["ts"] = pd.to_datetime(panel["ts"], utc=True)
    return panel[["ts", "stx_btc"]]


def _enrich_activity_with_prices(
    activity: pd.DataFrame, price_panel: pd.DataFrame
) -> pd.DataFrame:
    if activity.empty:
        return activity.copy()
    df = activity.copy()
    df["block_time"] = pd.to_datetime(df["block_time"], utc=True)
    price_panel = price_panel.copy()
    price_panel["ts"] = pd.to_datetime(price_panel["ts"], utc=True)
    df = pd.merge_asof(
        df.sort_values("block_time"),
        price_panel.sort_values("ts"),
        left_on="block_time",
        right_on="ts",
        direction="nearest",
    )
    df = df.drop(columns=["ts"]) if "ts" in df else df
    df["fee_stx"] = df["fee_ustx"].astype(float) / MICROSTX_PER_STX
    # If price is missing, NV contribution is unknown; treat as 0 and flag could be added
    df["stx_btc"] = df["stx_btc"].astype(float)
    df["nv_btc"] = (df["fee_stx"] * df["stx_btc"]).fillna(0.0)
    return df


def compute_wallet_windows(
    activity: pd.DataFrame,
    first_seen: pd.DataFrame,
    price_panel: pd.DataFrame,
    *,
    windows: Sequence[int] = (15, 30, 60, 90, 180),
) -> pd.DataFrame:
    """Aggregate per-wallet metrics over windows from activation.

    Returns a DataFrame with one row per (address, window_days):
      - activation_date
      - tx_count
      - fee_stx_sum
      - nv_btc_sum
    """
    if activity.empty or first_seen.empty:
        return pd.DataFrame(
            columns=[
                "address",
                "activation_date",
                "window_days",
                "tx_count",
                "fee_stx_sum",
                "nv_btc_sum",
            ]
        )
    enriched = _enrich_activity_with_prices(activity, price_panel)
    activation = compute_activation(first_seen)
    merged = enriched.merge(activation, on="address", how="left")
    merged = merged.dropna(subset=["activation_time"])  # ensure known start
    merged["days_since_activation"] = (
        merged["block_time"] - merged["activation_time"]
    ).dt.total_seconds() / 86400.0
    merged = merged[merged["days_since_activation"] >= 0]
    if merged.empty:
        return pd.DataFrame(
            columns=[
                "address",
                "activation_date",
                "window_days",
                "tx_count",
                "fee_stx_sum",
                "nv_btc_sum",
            ]
        )

    results: list[dict[str, object]] = []
    for w in sorted(set(int(x) for x in windows if x > 0)):
        window_slice = merged[merged["days_since_activation"] < w]
        if window_slice.empty:
            continue
        agg = (
            window_slice.groupby(["address", "activation_date"])[
                ["tx_id", "fee_stx", "nv_btc"]
            ]
            .agg(
                tx_count=("tx_id", "count"),
                fee_stx_sum=("fee_stx", "sum"),
                nv_btc_sum=("nv_btc", "sum"),
            )
            .reset_index()
        )
        agg["window_days"] = w
        results.append(agg)
    if not results:
        return pd.DataFrame(
            columns=[
                "address",
                "activation_date",
                "window_days",
                "tx_count",
                "fee_stx_sum",
                "nv_btc_sum",
            ]
        )
    out = pd.concat(results, ignore_index=True)
    # Ensure types
    out["tx_count"] = out["tx_count"].astype(int)
    out["fee_stx_sum"] = out["fee_stx_sum"].astype(float)
    out["nv_btc_sum"] = out["nv_btc_sum"].astype(float)
    out["window_days"] = out["window_days"].astype(int)
    return out


def classify_wallets(
    *,
    first_seen: pd.DataFrame,
    activity: pd.DataFrame,
    windows_agg: pd.DataFrame,
    thresholds: ClassificationThresholds = ClassificationThresholds(),
    balance_lookup: Mapping[str, float] | None = None,
    max_balance_lookups: int | None = 500,
) -> pd.DataFrame:
    """Classify wallets into funded/active/value using the provided thresholds.

    balance_lookup allows injecting known balances in STX for testing; when not
    provided, the function fetches current balances for at most max_balance_lookups
    addresses via Hiro (cached). If there are more wallets than the cap, it will
    set funded=False for the overflow to avoid heavy API usage.
    """
    if first_seen.empty:
        return pd.DataFrame(
            columns=["address", "activation_date", "funded", "active_30d", "value_30d"]
        )

    activation = compute_activation(first_seen)
    addresses = activation["address"].astype(str).tolist()

    # Determine funded via balances
    funded_map: dict[str, bool] = {}
    if balance_lookup is not None:
        for addr, bal in balance_lookup.items():
            funded_map[str(addr)] = bool(bal >= thresholds.funded_stx_min)
    else:
        to_fetch = (
            addresses
            if max_balance_lookups is None
            else addresses[:max_balance_lookups]
        )
        for addr in to_fetch:
            try:
                payload = fetch_address_balances(addr)
            except Exception:
                payload = {}
            stx_balance_ustx = 0
            stx = payload.get("stx") if isinstance(payload, dict) else None
            if isinstance(stx, dict):
                bal_str = stx.get("balance") or stx.get("locked") or 0
                try:
                    stx_balance_ustx = int(bal_str)
                except Exception:
                    stx_balance_ustx = 0
            stx_balance = stx_balance_ustx / MICROSTX_PER_STX
            funded_map[addr] = bool(stx_balance >= thresholds.funded_stx_min)

    # Active in 30d: tx_count >= threshold in window 30
    w30 = (
        windows_agg[windows_agg["window_days"] == 30]
        if not windows_agg.empty
        else pd.DataFrame()
    )
    tx_count_map = (
        w30.set_index("address")["tx_count"].to_dict() if not w30.empty else {}
    )
    fee_sum_map = (
        w30.set_index("address")["fee_stx_sum"].to_dict() if not w30.empty else {}
    )

    rows: list[dict[str, object]] = []
    for row in activation.itertuples(index=False):
        addr = str(row.address)
        rows.append(
            {
                "address": addr,
                "activation_date": row.activation_date,
                "funded": bool(funded_map.get(addr, False)),
                "active_30d": bool(
                    tx_count_map.get(addr, 0) >= thresholds.active_min_tx_30d
                ),
                "value_30d": bool(
                    fee_sum_map.get(addr, 0.0) >= thresholds.value_min_fee_stx_30d
                ),
            }
        )
    return pd.DataFrame(rows)


def compute_value_pipeline(
    *,
    max_days: int,
    windows: Sequence[int] = (15, 30, 60, 90),
    force_refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    """End-to-end pipeline to compute wallet value analytics for dashboards.

    Returns a dict with keys:
      - activity: enriched activity (NV per tx)
      - windows: per-wallet window aggregates
      - classification: funded/active/value flags per wallet
    """
    # Ensure transaction history exists and load
    wallet_metrics.ensure_transaction_history(
        max_days=max_days, force_refresh=force_refresh
    )
    activity = wallet_metrics.load_recent_wallet_activity(max_days=max_days)
    first_seen = wallet_metrics.update_first_seen_cache(activity)

    # Load prices and compute aggregates
    price_panel = load_price_panel_for_activity(activity, force_refresh=force_refresh)
    windows_agg = compute_wallet_windows(
        activity, first_seen, price_panel, windows=windows
    )
    cls = classify_wallets(
        first_seen=first_seen,
        activity=activity,
        windows_agg=windows_agg,
    )

    return {
        "activity": _enrich_activity_with_prices(activity, price_panel),
        "windows": windows_agg,
        "classification": cls,
    }
