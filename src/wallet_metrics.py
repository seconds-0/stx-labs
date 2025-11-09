"""Wallet growth metrics powered by the Hiro Stacks API and cached via DuckDB."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import duckdb
import pandas as pd

from . import config as cfg
from .cache_utils import read_parquet, write_parquet
from .hiro import fetch_transactions_page

WALLET_CACHE_DIR = cfg.CACHE_DIR / "wallet_metrics"
WALLET_CACHE_DIR.mkdir(parents=True, exist_ok=True)

FIRST_SEEN_CACHE_PATH = WALLET_CACHE_DIR / "first_seen_wallets.parquet"
MICROSTX_PER_STX = 1_000_000
TRANSACTION_PAGE_LIMIT = 50
DEFAULT_MAX_PAGES = 10_000
DUCKDB_PATH = cfg.DUCKDB_PATH


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path = str(DUCKDB_PATH)
    return duckdb.connect(path, read_only=read_only)


def _ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            tx_id VARCHAR PRIMARY KEY,
            block_time TIMESTAMP,
            block_height BIGINT,
            sender_address VARCHAR,
            fee_ustx BIGINT,
            tx_type VARCHAR,
            canonical BOOLEAN,
            tx_status VARCHAR,
            burn_block_time TIMESTAMP,
            burn_block_height BIGINT,
            microblock_sequence BIGINT,
            ingested_at TIMESTAMP
        );
        """
    )


def _prepare_transactions(results: list[dict[str, Any]]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for tx in results:
        sender = tx.get("sender_address")
        canonical = tx.get("canonical", False)
        status = tx.get("tx_status")
        block_time = tx.get("block_time")
        if not sender or not canonical or status != "success" or block_time is None:
            continue
        fee_raw = tx.get("fee")
        if fee_raw is None:
            fee_raw = tx.get("fee_rate")
        try:
            fee_ustx = int(fee_raw)
        except (TypeError, ValueError):
            fee_ustx = 0
        records.append(
            {
                "tx_id": tx.get("tx_id"),
                "block_time": pd.to_datetime(block_time, unit="s", utc=True),
                "block_height": tx.get("block_height"),
                "sender_address": sender,
                "fee_ustx": fee_ustx,
                "tx_type": tx.get("tx_type"),
                "canonical": canonical,
                "tx_status": status,
                "burn_block_time": (
                    pd.to_datetime(tx.get("burn_block_time"), unit="s", utc=True)
                    if tx.get("burn_block_time") is not None
                    else pd.NaT
                ),
                "burn_block_height": tx.get("burn_block_height"),
                "microblock_sequence": tx.get("microblock_sequence"),
                "ingested_at": pd.Timestamp(_utc_now()),
            }
        )
    if not records:
        return pd.DataFrame(
            columns=[
                "tx_id",
                "block_time",
                "block_height",
                "sender_address",
                "fee_ustx",
                "tx_type",
                "canonical",
                "tx_status",
                "burn_block_time",
                "burn_block_height",
                "microblock_sequence",
                "ingested_at",
            ]
        )
    df = pd.DataFrame.from_records(records)
    return df


def _insert_transactions(conn: duckdb.DuckDBPyConnection, frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    store_df = frame.copy()
    store_df["block_time"] = (
        store_df["block_time"].dt.tz_convert("UTC").dt.tz_localize(None)
    )
    if store_df["burn_block_time"].notna().any():
        store_df["burn_block_time"] = (
            store_df["burn_block_time"].dt.tz_convert("UTC").dt.tz_localize(None)
        )
    store_df["ingested_at"] = (
        store_df["ingested_at"].dt.tz_convert("UTC").dt.tz_localize(None)
    )
    conn.register("incoming_transactions", store_df)
    conn.execute(
        """
        INSERT OR REPLACE INTO transactions BY NAME
        SELECT * FROM incoming_transactions;
        """
    )
    conn.unregister("incoming_transactions")
    return len(store_df)


def _page_cursor(results: list[dict[str, Any]]) -> int | None:
    timestamps: list[int] = []
    for tx in results:
        cursor_candidate = tx.get("burn_block_time")
        if cursor_candidate is None:
            cursor_candidate = tx.get("block_time")
        if cursor_candidate is None:
            continue
        try:
            timestamps.append(int(cursor_candidate))
        except (TypeError, ValueError):
            continue
    if not timestamps:
        return None
    return min(timestamps) - 1


def _sync_latest_transactions(
    conn: duckdb.DuckDBPyConnection,
    *,
    max_pages: int,
) -> None:
    max_row = conn.execute("SELECT MAX(block_time) FROM transactions").fetchone()
    max_time = (
        pd.Timestamp(max_row[0]).tz_localize("UTC") if max_row and max_row[0] else None
    )
    cursor_to: int | None = None
    pages = 0
    while pages < max_pages:
        pages += 1
        print(f"  Fetching latest page {pages}/{max_pages}...", flush=True)
        payload = fetch_transactions_page(
            limit=TRANSACTION_PAGE_LIMIT,
            offset=0,
            include_unanchored=False,
            force_refresh=cursor_to is None,
            ttl_seconds=300 if cursor_to is None else 1800,
            end_time=cursor_to,
        )
        results = payload.get("results", [])
        if not results:
            break
        frame = _prepare_transactions(results)
        if not frame.empty:
            _insert_transactions(conn, frame)
            newest_to_consider = frame["block_time"].min()
        else:
            newest_to_consider = None
        cursor_candidate = _page_cursor(results)
        if cursor_candidate is None:
            break
        cursor_to = cursor_candidate
        if max_time is not None and newest_to_consider is not None:
            if newest_to_consider <= max_time:
                break


def _sync_historical_transactions(
    conn: duckdb.DuckDBPyConnection,
    *,
    cutoff: datetime,
    max_pages: int,
) -> None:
    min_row = conn.execute(
        "SELECT MIN(block_time), MIN(burn_block_time) FROM transactions"
    ).fetchone()
    target_time = cutoff.astimezone(UTC)
    min_time = (
        pd.Timestamp(min_row[0]).tz_localize("UTC") if min_row and min_row[0] else None
    )
    min_burn_time = (
        pd.Timestamp(min_row[1]).tz_localize("UTC") if min_row and min_row[1] else None
    )
    if min_time is not None and min_time <= target_time:
        return
    cursor_source = min_burn_time or min_time
    cursor_to = (
        int(cursor_source.timestamp()) - 1
        if cursor_source is not None
        else int(_utc_now().timestamp())
    )
    pages = 0
    while pages < max_pages and cursor_to is not None:
        pages += 1
        print(f"  Fetching historical page {pages}/{max_pages}...", flush=True)
        payload = fetch_transactions_page(
            limit=TRANSACTION_PAGE_LIMIT,
            offset=0,
            include_unanchored=False,
            force_refresh=False,
            ttl_seconds=1800,
            end_time=cursor_to,
        )
        results = payload.get("results", [])
        if not results:
            break
        frame = _prepare_transactions(results)
        if not frame.empty:
            _insert_transactions(conn, frame)
            min_time = (
                frame["block_time"].min()
                if min_time is None
                else min(min_time, frame["block_time"].min())
            )
            if min_time <= target_time:
                break
        next_cursor = _page_cursor(results)
        if next_cursor is None or next_cursor >= cursor_to:
            break
        cursor_to = next_cursor


def ensure_transaction_history(
    *,
    max_days: int,
    force_refresh: bool,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> None:
    if max_days <= 0:
        raise ValueError("max_days must be positive")
    with _connect() as conn:
        _ensure_schema(conn)
        if force_refresh:
            conn.execute("DELETE FROM transactions")
        _sync_latest_transactions(conn, max_pages=max_pages)
        cutoff = _utc_now() - timedelta(days=max_days)
        _sync_historical_transactions(
            conn,
            cutoff=cutoff,
            max_pages=max_pages,
        )


@dataclass(slots=True)
class WalletMetricsBundle:
    """Container for wallet-related metric tables."""

    activity: pd.DataFrame
    first_seen: pd.DataFrame
    new_wallets: pd.DataFrame
    active_wallets: pd.DataFrame
    retention: pd.DataFrame
    fee_per_wallet: pd.DataFrame


def build_wallet_metrics(
    *,
    max_days: int,
    windows: Sequence[int] = (15, 30, 60, 90),
    force_refresh: bool = False,
) -> WalletMetricsBundle:
    """Collect wallet activity and compute cohort analytics."""
    ensure_transaction_history(
        max_days=max_days,
        force_refresh=force_refresh,
    )
    activity = load_recent_wallet_activity(
        max_days=max_days,
    )
    first_seen = update_first_seen_cache(activity)
    cutoff = _utc_now() - timedelta(days=max_days)
    start_ts = pd.Timestamp(cutoff).floor("D")

    new_wallets = compute_new_wallets(first_seen, start_ts)
    active_wallets = compute_active_wallets(activity, start_ts)
    retention = compute_retention(activity, first_seen, windows)
    fee_per_wallet = compute_fee_per_wallet(activity, first_seen, windows)

    return WalletMetricsBundle(
        activity=activity,
        first_seen=first_seen,
        new_wallets=new_wallets,
        active_wallets=active_wallets,
        retention=retention,
        fee_per_wallet=fee_per_wallet,
    )


def load_recent_wallet_activity(
    *,
    max_days: int,
) -> pd.DataFrame:
    if max_days <= 0:
        raise ValueError("max_days must be positive")
    start_cutoff = _utc_now() - timedelta(days=max_days)
    cutoff_naive = start_cutoff.astimezone(UTC).replace(tzinfo=None)
    with _connect(read_only=True) as conn:
        df = conn.execute(
            """
            SELECT
                tx_id,
                sender_address AS address,
                block_time,
                fee_ustx,
                tx_type
            FROM transactions
            WHERE block_time >= ?
            ORDER BY block_time DESC;
            """,
            [cutoff_naive],
        ).df()
    if df.empty:
        return pd.DataFrame(
            columns=[
                "tx_id",
                "address",
                "block_time",
                "activity_date",
                "fee_ustx",
                "tx_type",
            ]
        )
    df["block_time"] = pd.to_datetime(df["block_time"], utc=True)
    df["address"] = df["address"].astype(str)
    df = df[df["address"].notna()]
    df["activity_date"] = df["block_time"].dt.floor("D")
    df = df[
        [
            "tx_id",
            "address",
            "block_time",
            "activity_date",
            "fee_ustx",
            "tx_type",
        ]
    ].copy()
    return df


def load_first_seen_cache() -> pd.DataFrame:
    cached = read_parquet(FIRST_SEEN_CACHE_PATH)
    if cached is None:
        return pd.DataFrame(columns=["address", "first_seen"])
    cached["first_seen"] = pd.to_datetime(cached["first_seen"], utc=True)
    cached["address"] = cached["address"].astype(str)
    return cached


def update_first_seen_cache(activity: pd.DataFrame) -> pd.DataFrame:
    """Persist earliest known transaction timestamp per wallet."""
    cached = load_first_seen_cache()
    if activity.empty:
        return cached

    current = (
        activity.groupby("address", as_index=False)["block_time"]
        .min()
        .rename(columns={"block_time": "first_seen"})
    )
    combined = pd.concat([cached, current], ignore_index=True)
    combined = combined.sort_values("first_seen").drop_duplicates(
        subset=["address"], keep="first"
    )
    write_parquet(FIRST_SEEN_CACHE_PATH, combined)
    return combined


def compute_new_wallets(
    first_seen: pd.DataFrame, start_ts: pd.Timestamp
) -> pd.DataFrame:
    if first_seen.empty:
        return pd.DataFrame(columns=["activation_date", "new_wallets"])

    data = first_seen[first_seen["first_seen"] >= start_ts].copy()
    if data.empty:
        return pd.DataFrame(columns=["activation_date", "new_wallets"])

    data["activation_date"] = data["first_seen"].dt.floor("D")
    summary = (
        data.groupby("activation_date")["address"]
        .nunique()
        .rename("new_wallets")
        .reset_index()
        .sort_values("activation_date")
    )
    return summary


def compute_active_wallets(
    activity: pd.DataFrame, start_ts: pd.Timestamp
) -> pd.DataFrame:
    if activity.empty:
        return pd.DataFrame(
            columns=["activity_date", "active_wallets", "rolling_7d", "rolling_30d"]
        )

    data = activity[activity["block_time"] >= start_ts].copy()
    if data.empty:
        return pd.DataFrame(
            columns=["activity_date", "active_wallets", "rolling_7d", "rolling_30d"]
        )

    summary = (
        data.groupby("activity_date")["address"]
        .nunique()
        .rename("active_wallets")
        .reset_index()
        .sort_values("activity_date")
    )
    summary["rolling_7d"] = (
        summary["active_wallets"].rolling(window=7, min_periods=1).mean()
    )
    summary["rolling_30d"] = (
        summary["active_wallets"].rolling(window=30, min_periods=1).mean()
    )
    return summary


def compute_retention(
    activity: pd.DataFrame,
    first_seen: pd.DataFrame,
    windows: Sequence[int],
    *,
    today: pd.Timestamp | None = None,
) -> pd.DataFrame:
    if activity.empty or first_seen.empty:
        return pd.DataFrame(
            columns=[
                "activation_date",
                "window_days",
                "cohort_size",
                "retained_wallets",
                "retention_rate",
            ]
        )

    windows = sorted(set(int(w) for w in windows if w > 0))
    if not windows:
        return pd.DataFrame(
            columns=[
                "activation_date",
                "window_days",
                "cohort_size",
                "retained_wallets",
                "retention_rate",
            ]
        )

    merged = activity.merge(first_seen, on="address", how="left")
    merged = merged.dropna(subset=["first_seen"])
    if merged.empty:
        return pd.DataFrame(
            columns=[
                "activation_date",
                "window_days",
                "cohort_size",
                "retained_wallets",
                "retention_rate",
            ]
        )

    merged["activation_date"] = merged["first_seen"].dt.floor("D")
    merged["days_since_activation"] = (
        merged["activity_date"] - merged["activation_date"]
    ).dt.days
    merged = merged[merged["days_since_activation"] >= 0]
    if merged.empty:
        return pd.DataFrame(
            columns=[
                "activation_date",
                "window_days",
                "cohort_size",
                "retained_wallets",
                "retention_rate",
            ]
        )

    cohort_sizes = (
        merged[merged["days_since_activation"] == 0]
        .groupby("activation_date")["address"]
        .nunique()
        .rename("cohort_size")
    )

    if today is None:
        today = pd.Timestamp(_utc_now()).floor("D")
    else:
        today = (
            today.tz_convert("UTC").floor("D")
            if today.tzinfo
            else pd.Timestamp(today).tz_localize("UTC").floor("D")
        )

    results: list[dict[str, object]] = []
    for window in windows:
        eligible_dates = cohort_sizes.index[
            cohort_sizes.index <= today - pd.Timedelta(days=window)
        ]
        if eligible_dates.empty:
            continue

        engaged = (
            merged[
                (merged["days_since_activation"] > 0)
                & (merged["days_since_activation"] <= window)
            ]
            .drop_duplicates(subset=["activation_date", "address"])
            .groupby("activation_date")["address"]
            .nunique()
            .rename("retained_wallets")
        )

        for activation_date in eligible_dates:
            cohort_size = int(cohort_sizes.loc[activation_date])
            retained = int(engaged.get(activation_date, 0))
            rate = retained / cohort_size if cohort_size else 0.0
            results.append(
                {
                    "activation_date": activation_date,
                    "window_days": window,
                    "cohort_size": cohort_size,
                    "retained_wallets": retained,
                    "retention_rate": rate,
                }
            )

    if not results:
        return pd.DataFrame(
            columns=[
                "activation_date",
                "window_days",
                "cohort_size",
                "retained_wallets",
                "retention_rate",
            ]
        )

    return pd.DataFrame(results).sort_values(["window_days", "activation_date"])


def compute_fee_per_wallet(
    activity: pd.DataFrame,
    first_seen: pd.DataFrame,
    windows: Sequence[int],
    *,
    today: pd.Timestamp | None = None,
) -> pd.DataFrame:
    if activity.empty or first_seen.empty:
        return pd.DataFrame(
            columns=[
                "activation_date",
                "window_days",
                "avg_fee_stx",
                "median_fee_stx",
                "wallets_observed",
            ]
        )

    windows = sorted(set(int(w) for w in windows if w > 0))
    if not windows:
        return pd.DataFrame(
            columns=[
                "activation_date",
                "window_days",
                "avg_fee_stx",
                "median_fee_stx",
                "wallets_observed",
            ]
        )

    merged = activity.merge(first_seen, on="address", how="left")
    merged = merged.dropna(subset=["first_seen"])
    if merged.empty:
        return pd.DataFrame(
            columns=[
                "activation_date",
                "window_days",
                "avg_fee_stx",
                "median_fee_stx",
                "wallets_observed",
            ]
        )

    merged["activation_date"] = merged["first_seen"].dt.floor("D")
    merged["days_since_activation"] = (
        merged["activity_date"] - merged["activation_date"]
    ).dt.days
    merged = merged[merged["days_since_activation"] >= 0]

    if today is None:
        today = pd.Timestamp(_utc_now()).floor("D")
    else:
        today = (
            today.tz_convert("UTC").floor("D")
            if today.tzinfo
            else pd.Timestamp(today).tz_localize("UTC").floor("D")
        )

    results: list[dict[str, object]] = []
    for window in windows:
        eligible_mask = merged["activation_date"] <= today - pd.Timedelta(days=window)
        eligible = merged[eligible_mask]
        if eligible.empty:
            continue

        window_activity = eligible[
            (eligible["days_since_activation"] >= 0)
            & (eligible["days_since_activation"] < window)
        ]
        if window_activity.empty:
            continue

        wallet_fee = (
            window_activity.groupby(["activation_date", "address"])["fee_ustx"]
            .sum()
            .reset_index()
        )
        wallet_fee["fee_stx"] = wallet_fee["fee_ustx"] / MICROSTX_PER_STX

        aggregated = wallet_fee.groupby("activation_date")["fee_stx"].agg(
            avg_fee_stx="mean",
            median_fee_stx="median",
            wallets_observed="count",
        )

        for activation_date, row in aggregated.iterrows():
            results.append(
                {
                    "activation_date": activation_date,
                    "window_days": window,
                    "avg_fee_stx": float(row["avg_fee_stx"]),
                    "median_fee_stx": float(row["median_fee_stx"]),
                    "wallets_observed": int(row["wallets_observed"]),
                }
            )

    if not results:
        return pd.DataFrame(
            columns=[
                "activation_date",
                "window_days",
                "avg_fee_stx",
                "median_fee_stx",
                "wallets_observed",
            ]
        )

    return pd.DataFrame(results).sort_values(["window_days", "activation_date"])
