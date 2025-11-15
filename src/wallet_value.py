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
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import pandas as pd

from . import prices
from . import wallet_metrics

MICROSTX_PER_STX = 1_000_000
MIN_WALTV_COHORT = 3  # Minimum wallets required for ROI panels


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


def _ensure_ns_timestamp(series: pd.Series) -> pd.Series:
    """Coerce datetime64 series to timezone-aware nanosecond resolution."""
    if not pd.api.types.is_datetime64_any_dtype(series):
        series = pd.to_datetime(series, utc=True)
    else:
        if getattr(series.dtype, "tz", None) is None:
            series = pd.to_datetime(series, utc=True)
    # Convert to nanosecond precision while preserving the actual datetime value
    return series.dt.as_unit("ns")


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
    df["block_time"] = _ensure_ns_timestamp(df["block_time"])
    price_panel = price_panel.copy()
    if "stx_btc" not in price_panel.columns:
        if {"stx_usd", "btc_usd"}.issubset(price_panel.columns):
            price_panel["stx_btc"] = price_panel["stx_usd"].astype(float) / price_panel[
                "btc_usd"
            ].astype(float)
        else:
            price_panel["stx_btc"] = pd.NA
    price_panel["ts"] = _ensure_ns_timestamp(price_panel["ts"])
    df = pd.merge_asof(
        df.sort_values("block_time"),
        price_panel.sort_values("ts"),
        left_on="block_time",
        right_on="ts",
        direction="nearest",
    )
    df = df.drop(columns=["ts"]) if "ts" in df else df
    if "stx_btc" not in df.columns:
        df["stx_btc"] = 0.0
    df["fee_stx"] = df["fee_ustx"].astype(float) / MICROSTX_PER_STX
    # If price is missing, NV contribution is unknown; treat as 0 and flag could be added
    df["stx_btc"] = df["stx_btc"].astype(float)
    df["nv_btc"] = (df["fee_stx"] * df["stx_btc"]).fillna(0.0)
    return df


def _resolve_window_band(window: int, band_days: Mapping[int, int] | None) -> int:
    if band_days and window in band_days:
        band = int(band_days[window])
    else:
        band = 15 if window <= 15 else 30
    if band <= 0:
        raise ValueError("window band must be positive")
    return min(window, band)


def compute_wallet_windows(
    activity: pd.DataFrame,
    first_seen: pd.DataFrame,
    price_panel: pd.DataFrame,
    *,
    windows: Sequence[int] = (15, 30, 60, 90, 180),
    band_days: Mapping[int, int] | None = None,
) -> pd.DataFrame:
    """Aggregate per-wallet metrics over windows from activation.

    Returns a DataFrame with one row per (address, window_days):
      - activation_date
      - tx_count
      - fee_stx_sum
      - nv_btc_sum
      - band_tx_count (transactions inside the trailing activity band)
      - active_in_window (bool indicating >=1 tx in the trailing band)
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
                "band_tx_count",
                "active_in_window",
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
                "band_tx_count",
                "active_in_window",
            ]
        )

    band_lookup = {int(w): _resolve_window_band(int(w), band_days) for w in windows}

    window_values = sorted(set(int(x) for x in windows if int(x) > 0))
    if not window_values:
        return pd.DataFrame(
            columns=[
                "address",
                "activation_date",
                "window_days",
                "tx_count",
                "fee_stx_sum",
                "nv_btc_sum",
                "band_tx_count",
                "active_in_window",
            ]
        )

    band_lookup = {w: _resolve_window_band(w, band_days) for w in window_values}

    results: list[pd.DataFrame] = []
    for w in window_values:
        window_slice = merged[merged["days_since_activation"] < w]
        if window_slice.empty:
            continue
        band = band_lookup.get(w, _resolve_window_band(w, band_days))
        band_lower = max(w - band, 0)
        band_slice = window_slice[
            (window_slice["days_since_activation"] >= band_lower)
            & (window_slice["days_since_activation"] < w)
        ]
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
        if not band_slice.empty:
            band_counts = (
                band_slice.groupby(["address", "activation_date"])["tx_id"]
                .count()
                .rename("band_tx_count")
                .reset_index()
            )
        else:
            band_counts = pd.DataFrame(
                columns=["address", "activation_date", "band_tx_count"]
            )
        agg = agg.merge(
            band_counts,
            on=["address", "activation_date"],
            how="left",
        )
        agg["band_tx_count"] = agg["band_tx_count"].fillna(0).astype(int)
        agg["active_in_window"] = agg["band_tx_count"] > 0
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
                "band_tx_count",
                "active_in_window",
            ]
        )
    out = pd.concat(results, ignore_index=True)
    # Ensure types
    out["tx_count"] = out["tx_count"].astype(int)
    out["fee_stx_sum"] = out["fee_stx_sum"].astype(float)
    out["nv_btc_sum"] = out["nv_btc_sum"].astype(float)
    out["window_days"] = out["window_days"].astype(int)
    return out


def compute_trailing_wallet_windows(
    activity: pd.DataFrame,
    price_panel: pd.DataFrame,
    *,
    windows: Sequence[int] = (30, 60, 90),
    as_of: datetime | None = None,
) -> pd.DataFrame:
    """Compute trailing per-wallet value over the last N days (calendar-anchored).

    This differs from activation windows, which measure the first N days after
    activation. Trailing windows reflect the most recent activity regardless of
    activation date.

    Returns rows per (address, window_days):
      - tx_count, fee_stx_sum, nv_btc_sum
    """
    if activity.empty:
        return pd.DataFrame(
            columns=[
                "address",
                "window_days",
                "tx_count",
                "fee_stx_sum",
                "nv_btc_sum",
            ]
        )

    # Normalize timestamps and join prices once
    enriched = _enrich_activity_with_prices(activity, price_panel)
    enriched = enriched.copy()
    enriched["block_time"] = pd.to_datetime(enriched["block_time"], utc=True)

    if as_of is None:
        as_of = datetime.now(UTC)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)

    results: list[pd.DataFrame] = []
    for w in sorted(set(int(x) for x in windows if x > 0)):
        start = as_of - timedelta(days=w)
        window_slice = enriched[(enriched["block_time"] >= start) & (enriched["block_time"] < as_of)]
        if window_slice.empty:
            continue
        agg = (
            window_slice.groupby(["address"])[["tx_id", "fee_stx", "nv_btc"]]
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
                "window_days",
                "tx_count",
                "fee_stx_sum",
                "nv_btc_sum",
            ]
        )

    out = pd.concat(results, ignore_index=True)
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
    wallet_db_path: Path | None = None,
) -> pd.DataFrame:
    """Classify wallets into funded/active/value using the provided thresholds.

    balance_lookup allows injecting known balances in STX for testing; when not
    provided, balances are loaded from the persisted wallet_balances table with a
    fallback to live Hiro API fetches for any missing addresses.
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
        snapshot_date = datetime.now(UTC).date()
        threshold_ustx = int(thresholds.funded_stx_min * MICROSTX_PER_STX)
        stored_balances = wallet_metrics.load_wallet_balances(
            addresses,
            as_of_date=snapshot_date,
            db_path=wallet_db_path,
        )
        if not stored_balances.empty:
            for row in stored_balances.itertuples():
                balance_ustx = int(row.balance_ustx) if pd.notna(row.balance_ustx) else 0
                funded_map[str(row.address)] = bool(balance_ustx >= threshold_ustx)
        missing_addresses = [addr for addr in addresses if addr not in funded_map]
        if missing_addresses:
            wallet_metrics.ensure_wallet_balances(
                missing_addresses,
                as_of_date=snapshot_date,
                funded_threshold_stx=thresholds.funded_stx_min,
                db_path=wallet_db_path,
            )
            refreshed = wallet_metrics.load_wallet_balances(
                missing_addresses,
                as_of_date=snapshot_date,
                max_age_days=None,
                db_path=wallet_db_path,
            )
            if not refreshed.empty:
                for row in refreshed.itertuples():
                    balance_ustx = (
                        int(row.balance_ustx) if pd.notna(row.balance_ustx) else 0
                    )
                    funded_map[str(row.address)] = bool(
                        balance_ustx >= threshold_ustx
                    )

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
    wallet_db_path: Path | None = None,
    skip_history_sync: bool = False,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict[str, pd.DataFrame]:
    """End-to-end pipeline to compute wallet value analytics for dashboards.

    Returns a dict with keys:
      - activity: enriched activity (NV per tx)
      - windows: per-wallet window aggregates
      - classification: funded/active/value flags per wallet
    """
    def pulse(fraction: float, detail: str) -> None:
        if progress_callback is None:
            return
        bounded = min(max(fraction, 0.0), 0.99)
        progress_callback(bounded, detail)

    # Ensure transaction history exists and load
    if not skip_history_sync:
        pulse(0.05, "Ensuring transaction history")
        wallet_metrics.ensure_transaction_history(
            max_days=max_days, force_refresh=force_refresh
        )
    pulse(0.15, "Loading wallet activity")
    activity = wallet_metrics.load_recent_wallet_activity(
        max_days=max_days, db_path=wallet_db_path
    )
    first_seen = wallet_metrics.update_first_seen_cache(activity)
    pulse(0.3, "Updating activation cache")
    thresholds = ClassificationThresholds()
    if not first_seen.empty:
        activation = compute_activation(first_seen)
        recent_window_days = min(max_days, 30)
        cutoff_ts = datetime.now(UTC) - timedelta(days=recent_window_days)
        recent_addresses = activation[
            activation["activation_time"] >= cutoff_ts
        ]["address"].astype(str)
        pulse(0.45, "Ensuring funded wallet balances")
        def balances_progress(
            completed_batches: int,
            total_batches: int,
            processed_addresses: int,
            total_addresses: int,
        ) -> None:
            if progress_callback is None:
                return
            total = max(total_batches, 1)
            portion = min(max(completed_batches / total, 0.0), 1.0)
            detail = (
                f"Ensuring funded wallet balances ({processed_addresses}/{total_addresses})"
                if total_addresses
                else "Ensuring funded wallet balances"
            )
            pulse(0.4 + 0.15 * portion, detail)

        wallet_metrics.ensure_wallet_balances(
            recent_addresses.tolist(),
            as_of_date=datetime.now(UTC).date(),
            funded_threshold_stx=thresholds.funded_stx_min,
            db_path=wallet_db_path,
            batch_size=25,
            max_workers=5,
            delay_seconds=0.5,
            progress_callback=balances_progress if progress_callback else None,
        )

    # Load prices and compute aggregates
    pulse(0.55, "Loading STX/BTC price panel")
    price_panel = load_price_panel_for_activity(activity, force_refresh=force_refresh)
    pulse(0.7, "Computing WALTV windows")
    windows_agg = compute_wallet_windows(
        activity, first_seen, price_panel, windows=windows
    )
    pulse(0.85, "Classifying funded/active/value wallets")
    cls = classify_wallets(
        first_seen=first_seen,
        activity=activity,
        windows_agg=windows_agg,
        thresholds=thresholds,
        wallet_db_path=wallet_db_path,
    )

    return {
        "activity": _enrich_activity_with_prices(activity, price_panel),
        "windows": windows_agg,
        "classification": cls,
    }


def compute_network_daily(activity: pd.DataFrame) -> pd.DataFrame:
    """Aggregate fees/NV per calendar day."""
    if activity.empty:
        return pd.DataFrame(
            columns=["activity_date", "tx_count", "wallets", "fee_stx_sum", "nv_btc_sum"]
        )
    df = activity.copy()
    df["activity_date"] = pd.to_datetime(df["block_time"], utc=True).dt.floor("D")
    grouped = (
        df.groupby("activity_date")
        .agg(
            tx_count=("tx_id", "count"),
            wallets=("address", "nunique"),
            fee_stx_sum=("fee_stx", "sum"),
            nv_btc_sum=("nv_btc", "sum"),
        )
        .reset_index()
    )
    return grouped.sort_values("activity_date")


def summarize_value_kpis(
    *,
    daily_activity: pd.DataFrame,
    windows_agg: pd.DataFrame,
    classification: pd.DataFrame,
    lookback_days: int = 30,
    window_days: int = 30,
) -> dict[str, float]:
    """Return headline KPIs for dashboards."""
    today = pd.Timestamp.now(tz=UTC).floor("D")
    start = today - pd.Timedelta(days=max(lookback_days - 1, 0))

    recent_daily = (
        daily_activity[daily_activity["activity_date"] >= start]
        if not daily_activity.empty
        else pd.DataFrame()
    )
    w = windows_agg[windows_agg["window_days"] == window_days]
    recent_cls = (
        classification[
            pd.to_datetime(classification["activation_date"], utc=True) >= start
        ]
        if not classification.empty
        else pd.DataFrame()
    )

    total_nv_btc = (
        float(recent_daily["nv_btc_sum"].sum()) if not recent_daily.empty else 0.0
    )
    total_fee_stx = (
        float(recent_daily["fee_stx_sum"].sum()) if not recent_daily.empty else 0.0
    )
    avg_waltv = float(w["fee_stx_sum"].mean()) if not w.empty else 0.0
    median_waltv = float(w["fee_stx_sum"].median()) if not w.empty else 0.0

    funded = int(recent_cls["funded"].sum()) if not recent_cls.empty else 0
    active = int(recent_cls["active_30d"].sum()) if not recent_cls.empty else 0
    value = int(recent_cls["value_30d"].sum()) if not recent_cls.empty else 0

    active_pct = (active / funded * 100) if funded else 0.0
    value_pct = (value / funded * 100) if funded else 0.0

    return {
        "total_nv_btc": total_nv_btc,
        "total_fee_stx": total_fee_stx,
        "avg_waltv_stx": avg_waltv,
        "median_waltv_stx": median_waltv,
        "funded_wallets": funded,
        "active_wallets": active,
        "value_wallets": value,
        "active_pct": active_pct,
        "value_pct": value_pct,
    }


def summarize_window_stats(
    windows_agg: pd.DataFrame,
    *,
    window_days: int,
) -> dict[str, float | int]:
    """Return aggregate WALTV stats for a specific window."""
    if windows_agg.empty:
        return {
            "window_days": window_days,
            "wallets": 0,
            "avg_waltv_stx": 0.0,
            "median_waltv_stx": 0.0,
            "nv_btc_sum": 0.0,
            "fee_stx_sum": 0.0,
        }
    window_df = windows_agg[windows_agg["window_days"] == window_days]
    if window_df.empty:
        return {
            "window_days": window_days,
            "wallets": 0,
            "avg_waltv_stx": 0.0,
            "median_waltv_stx": 0.0,
            "nv_btc_sum": 0.0,
            "fee_stx_sum": 0.0,
        }
    avg = float(window_df["fee_stx_sum"].mean())
    median = float(window_df["fee_stx_sum"].median())
    wallets = int(len(window_df))
    nv_btc = float(window_df["nv_btc_sum"].mean()) if "nv_btc_sum" in window_df else 0.0
    fee_sum = float(window_df["fee_stx_sum"].sum())
    return {
        "window_days": window_days,
        "wallets": wallets,
        "avg_waltv_stx": avg,
        "median_waltv_stx": median,
        "nv_btc_sum": nv_btc,
        "fee_stx_sum": fee_sum,
    }


def summarize_trailing_window_stats(
    trailing_agg: pd.DataFrame,
    *,
    window_days: int,
) -> dict[str, float | int]:
    """Return aggregate stats for trailing window data (calendar-anchored)."""
    if trailing_agg.empty:
        return {
            "window_days": window_days,
            "wallets": 0,
            "avg_last_stx": 0.0,
            "median_last_stx": 0.0,
            "nv_btc_sum": 0.0,
            "fee_stx_sum": 0.0,
        }
    df = trailing_agg[trailing_agg["window_days"] == window_days]
    if df.empty:
        return {
            "window_days": window_days,
            "wallets": 0,
            "avg_last_stx": 0.0,
            "median_last_stx": 0.0,
            "nv_btc_sum": 0.0,
            "fee_stx_sum": 0.0,
        }
    avg = float(df["fee_stx_sum"].mean())
    median = float(df["fee_stx_sum"].median())
    wallets = int(len(df))
    nv_btc = float(df["nv_btc_sum"].mean()) if "nv_btc_sum" in df else 0.0
    fee_sum = float(df["fee_stx_sum"].sum())
    return {
        "window_days": window_days,
        "wallets": wallets,
        "avg_last_stx": avg,
        "median_last_stx": median,
        "nv_btc_sum": nv_btc,
        "fee_stx_sum": fee_sum,
    }


def compute_cpa_panel(
    windows_agg: pd.DataFrame,
    *,
    window_days: int = 30,
    cpa_target_stx: float = 5.0,
    min_wallets: int = MIN_WALTV_COHORT,
) -> pd.DataFrame:
    """Aggregate WALTV by activation cohort with CPA comparison."""
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    if cpa_target_stx <= 0:
        raise ValueError("cpa_target_stx must be positive")
    if min_wallets < 1:
        raise ValueError("min_wallets must be >= 1")
    if windows_agg.empty:
        return pd.DataFrame(
            columns=[
                "activation_date",
                "avg_waltv_stx",
                "median_waltv_stx",
                "wallets",
                "payback_multiple",
                "above_target",
            ]
        )

    window_df = windows_agg[windows_agg["window_days"] == window_days].copy()
    if window_df.empty:
        return pd.DataFrame(
            columns=[
                "activation_date",
                "avg_waltv_stx",
                "median_waltv_stx",
                "wallets",
                "payback_multiple",
                "above_target",
            ]
        )

    window_df = window_df.copy()
    if not pd.api.types.is_datetime64_any_dtype(window_df["activation_date"]):
        window_df["activation_date"] = pd.to_datetime(
            window_df["activation_date"], utc=True
        )
    grouped = (
        window_df.groupby("activation_date")
        .agg(
            avg_waltv_stx=("fee_stx_sum", "mean"),
            median_waltv_stx=("fee_stx_sum", "median"),
            wallets=("address", "count"),
        )
        .reset_index()
        .sort_values("activation_date")
    )
    grouped = grouped[grouped["wallets"] >= max(min_wallets, 1)]

    if grouped.empty:
        return grouped

    grouped["payback_multiple"] = grouped["avg_waltv_stx"] / cpa_target_stx
    grouped["above_target"] = grouped["avg_waltv_stx"] >= cpa_target_stx
    grouped["activation_date"] = grouped["activation_date"].dt.tz_convert(UTC)
    return grouped.reset_index(drop=True)


def compute_cpa_panel_by_channel(
    windows_agg: pd.DataFrame,
    address_channel_map: pd.DataFrame,
    *,
    window_days: int = 180,
    cac_by_channel: Mapping[str, float] | None = None,
    min_wallets: int = MIN_WALTV_COHORT,
) -> pd.DataFrame:
    """Aggregate WALTV and payback multiples per (activation_date, channel)."""
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    if min_wallets < 1:
        raise ValueError("min_wallets must be >= 1")
    if windows_agg.empty or address_channel_map.empty:
        return pd.DataFrame(
            columns=[
                "activation_date",
                "channel",
                "avg_waltv_stx",
                "median_waltv_stx",
                "wallets",
                "cac_stx",
                "payback_multiple",
            ]
        )

    df = windows_agg[windows_agg["window_days"] == window_days].copy()
    if df.empty:
        return pd.DataFrame(
            columns=[
                "activation_date",
                "channel",
                "avg_waltv_stx",
                "median_waltv_stx",
                "wallets",
                "cac_stx",
                "payback_multiple",
            ]
        )

    if not pd.api.types.is_datetime64_any_dtype(df["activation_date"]):
        df["activation_date"] = pd.to_datetime(df["activation_date"], utc=True)
    else:
        df["activation_date"] = df["activation_date"].dt.tz_convert(UTC)

    channel_df = address_channel_map.copy()
    channel_df["address"] = channel_df["address"].astype(str)
    if "activation_date" in channel_df.columns:
        channel_df["activation_date"] = pd.to_datetime(
            channel_df["activation_date"], utc=True
        ).dt.floor("D")
    else:
        raise ValueError("address_channel_map must include activation_date")
    if "channel" not in channel_df.columns:
        raise ValueError("address_channel_map must include channel column")
    channel_df["channel"] = channel_df["channel"].fillna("Unknown").astype(str)

    merged = df.merge(
        channel_df,
        on=["address", "activation_date"],
        how="left",
    )
    merged["channel"] = merged["channel"].fillna("Unknown")

    grouped = (
        merged.groupby(["activation_date", "channel"])
        .agg(
            avg_waltv_stx=("fee_stx_sum", "mean"),
            median_waltv_stx=("fee_stx_sum", "median"),
            wallets=("address", "count"),
        )
        .reset_index()
    )
    grouped = grouped[grouped["wallets"] >= max(min_wallets, 1)]
    if grouped.empty:
        return grouped

    grouped = grouped.sort_values(["activation_date", "channel"]).reset_index(drop=True)

    if cac_by_channel:
        grouped["cac_stx"] = grouped["channel"].map(cac_by_channel)
        grouped["payback_multiple"] = grouped.apply(
            lambda row: (
                row["avg_waltv_stx"] / row["cac_stx"]
                if pd.notna(row["cac_stx"]) and row["cac_stx"]
                else pd.NA
            ),
            axis=1,
        )
    else:
        grouped["cac_stx"] = pd.NA
        grouped["payback_multiple"] = pd.NA
    return grouped
