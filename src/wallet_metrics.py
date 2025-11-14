"""Wallet growth metrics powered by the Hiro Stacks API and cached via DuckDB."""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

import duckdb
import pandas as pd
import shutil
import time
import logging

from . import config as cfg
from .cache_utils import read_parquet, write_parquet
from .hiro import fetch_transactions_page, fetch_address_balances

LOGGER = logging.getLogger(__name__)
WALLET_CACHE_DIR = cfg.CACHE_DIR / "wallet_metrics"
WALLET_CACHE_DIR.mkdir(parents=True, exist_ok=True)

FIRST_SEEN_CACHE_PATH = WALLET_CACHE_DIR / "first_seen_wallets.parquet"
FUNDED_D0_CACHE_PATH = WALLET_CACHE_DIR / "wallet_funded_d0.parquet"
SEGMENTED_RETENTION_PATH = WALLET_CACHE_DIR / "retention_segmented.parquet"
METRICS_DATA_START = pd.Timestamp("2024-12-23T00:00:00Z")
MICROSTX_PER_STX = 1_000_000
TRANSACTION_PAGE_LIMIT = 50
DEFAULT_MAX_PAGES = 10_000
DUCKDB_PATH = cfg.DUCKDB_PATH
FUNDED_D0_COLUMNS = [
    "address",
    "activation_date",
    "funded_d0",
    "balance_ustx",
    "snapshot_version",
    "has_snapshot",
    "ingested_at",
    "updated_at",
]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _resolve_db_path(db_path: Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    return DUCKDB_PATH


def _connect(
    read_only: bool = False, *, db_path: Path | None = None
) -> duckdb.DuckDBPyConnection:
    path = str(_resolve_db_path(db_path))
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wallet_balances (
            address VARCHAR,
            as_of_date DATE,
            balance_ustx BIGINT,
            funded BOOLEAN,
            ingested_at TIMESTAMP,
            PRIMARY KEY (address, as_of_date)
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS retention_segmented (
            window_days INTEGER,
            segment VARCHAR,
            retained_users BIGINT,
            eligible_users BIGINT,
            retention_pct DOUBLE,
            anchor_window_days INTEGER,
            updated_at TIMESTAMP,
            PRIMARY KEY (window_days, segment)
        );
        """
    )
    try:
        conn.execute(
            "ALTER TABLE retention_segmented ADD COLUMN anchor_window_days INTEGER"
        )
    except duckdb.CatalogException:
        pass


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


def _insert_wallet_balances(conn: duckdb.DuckDBPyConnection, frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    store_df = frame.copy()
    store_df["ingested_at"] = (
        store_df["ingested_at"].dt.tz_convert("UTC").dt.tz_localize(None)
    )
    conn.register("incoming_wallet_balances", store_df)
    conn.execute(
        """
        INSERT OR REPLACE INTO wallet_balances BY NAME
        SELECT * FROM incoming_wallet_balances;
        """
    )
    conn.unregister("incoming_wallet_balances")
    return len(store_df)


def _extract_stx_balance(payload: dict[str, Any] | None) -> int:
    if not payload or not isinstance(payload, dict):
        return 0
    stx = payload.get("stx")
    if not isinstance(stx, dict):
        return 0
    balance_raw = stx.get("balance")
    if balance_raw is None:
        balance_raw = stx.get("locked")
    try:
        return int(balance_raw)
    except (TypeError, ValueError):
        return 0


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


def _select_existing_balance_addresses(
    conn: duckdb.DuckDBPyConnection,
    snapshot_date: date,
    addresses: list[str],
) -> set[str]:
    if not addresses:
        return set()
    result = conn.execute(
        """
        SELECT address
        FROM wallet_balances
        WHERE as_of_date = ?
          AND address IN (SELECT * FROM UNNEST(?))
        """,
        [snapshot_date, addresses],
    ).fetchdf()
    if result.empty:
        return set()
    return set(result["address"].astype(str).tolist())


def ensure_wallet_balances(
    addresses: Sequence[str],
    *,
    as_of_date: date | None = None,
    funded_threshold_stx: float = 10.0,
    fetcher: Callable[..., dict[str, Any]] = fetch_address_balances,
    db_path: Path | None = None,
    delay_seconds: float = 0.1,
    batch_size: int | None = None,
    max_workers: int = 10,
) -> int:
    """Ensure a balance snapshot exists for all addresses on the given date.
    
    Args:
        addresses: List of wallet addresses to fetch balances for
        as_of_date: Date for the snapshot (defaults to today)
        funded_threshold_stx: Minimum STX balance to consider "funded"
        fetcher: Function to fetch balance data
        db_path: Optional path to DuckDB file
        delay_seconds: Delay between batches to avoid rate limits (default: 0.1s)
        batch_size: Process addresses in batches with concurrent requests within batches
        max_workers: Number of concurrent requests per batch (default: 10)
    """
    deduped = sorted({str(addr) for addr in addresses if addr})
    if not deduped:
        return 0
    snapshot_date = as_of_date or _utc_now().date()
    with _connect(db_path=db_path) as conn:
        _ensure_schema(conn)
        existing = _select_existing_balance_addresses(conn, snapshot_date, deduped)
    missing = [addr for addr in deduped if addr not in existing]
    if not missing:
        return 0
    
    rows: list[dict[str, Any]] = []
    funded_threshold_ustx = int(funded_threshold_stx * MICROSTX_PER_STX)
    
    def fetch_single_balance(addr: str) -> dict[str, Any] | None:
        """Fetch balance for a single address, return row dict or None if failed."""
        try:
            payload = fetcher(addr)
            balance_ustx = _extract_stx_balance(payload)
            balance_stx = balance_ustx / MICROSTX_PER_STX
            funded = bool(balance_ustx >= funded_threshold_ustx)
            LOGGER.info(
                "✓ Fetched balance for %s: %.6f STX (funded: %s)",
                addr,
                balance_stx,
                funded,
            )
            return {
                "address": addr,
                "as_of_date": snapshot_date,
                "balance_ustx": balance_ustx,
                "funded": funded,
                "ingested_at": pd.Timestamp(_utc_now()),
            }
        except Exception as exc:  # pragma: no cover - network failure path
            LOGGER.warning("✗ Failed to fetch balance for %s: %s", addr, exc)
            # Don't insert failed addresses - they'll be retried on next run
            # This allows the script to be resumable
            return None
    
    # Process in batches if specified, otherwise process all sequentially
    if batch_size and batch_size > 0:
        batches = [missing[i:i + batch_size] for i in range(0, len(missing), batch_size)]
        LOGGER.info(
            "Processing %d addresses in %d batches of %d (max %d concurrent requests per batch)",
            len(missing), len(batches), batch_size, max_workers
        )
    else:
        batches = [[addr] for addr in missing]
        max_workers = 1  # Sequential if no batching
    
    for batch_idx, batch in enumerate(batches):
        # Process batch with concurrent requests
        batch_rows = []
        with ThreadPoolExecutor(max_workers=min(max_workers, len(batch))) as executor:
            future_to_addr = {executor.submit(fetch_single_balance, addr): addr for addr in batch}
            for future in as_completed(future_to_addr):
                addr = future_to_addr[future]
                try:
                    row = future.result()
                    if row:
                        batch_rows.append(row)
                except Exception as exc:
                    LOGGER.warning("✗ Exception fetching balance for %s: %s", addr, exc)
        
        rows.extend(batch_rows)
        
        # Delay between batches to respect rate limits
        if batch_idx < len(batches) - 1:
            time.sleep(delay_seconds)
            LOGGER.info("Completed batch %d/%d, processed %d/%d addresses", 
                       batch_idx + 1, len(batches), len(rows), len(missing))
    
    # Insert all rows, including failed ones (marked as unfunded)
    with _connect(db_path=db_path) as conn:
        _ensure_schema(conn)
        inserted = _insert_wallet_balances(conn, pd.DataFrame(rows))
    return inserted


def load_wallet_balances(
    addresses: Sequence[str],
    *,
    as_of_date: date | None = None,
    max_age_days: int | None = 7,
    db_path: Path | None = None,
) -> pd.DataFrame:
    """Load the most recent balance snapshot per address."""
    deduped = sorted({str(addr) for addr in addresses if addr})
    if not deduped:
        return pd.DataFrame(
            columns=["address", "as_of_date", "balance_ustx", "funded", "ingested_at"]
        )
    with _connect(read_only=True, db_path=db_path) as conn:
        try:
            df = conn.execute(
                """
                SELECT address, as_of_date, balance_ustx, funded, ingested_at
                FROM wallet_balances
                WHERE address IN (SELECT * FROM UNNEST(?))
                """,
                [deduped],
            ).fetchdf()
        except duckdb.CatalogException:
            return pd.DataFrame(
                columns=["address", "as_of_date", "balance_ustx", "funded", "ingested_at"]
            )
    if df.empty:
        return df
    df["as_of_date"] = pd.to_datetime(df["as_of_date"])
    target_date = pd.to_datetime(as_of_date or _utc_now().date())
    df = df[df["as_of_date"] <= target_date]
    if max_age_days is not None:
        min_date = target_date - pd.Timedelta(days=max_age_days)
        df = df[df["as_of_date"] >= min_date]
    df = df.sort_values("as_of_date").drop_duplicates("address", keep="last")
    return df.reset_index(drop=True)


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
    db_path: Path | None = None,
) -> pd.DataFrame:
    if max_days <= 0:
        raise ValueError("max_days must be positive")
    start_cutoff = _utc_now() - timedelta(days=max_days)
    cutoff_naive = start_cutoff.astimezone(UTC).replace(tzinfo=None)
    with _connect(read_only=True, db_path=db_path) as conn:
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
    coverage_cutoff = METRICS_DATA_START.floor("D")
    df = df[df["activity_date"] >= coverage_cutoff]
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


def create_db_snapshot(destination: Path | None = None) -> Path:
    """Copy the DuckDB wallet metrics database for read-only use."""

    source = _resolve_db_path()
    if not source.exists():
        raise FileNotFoundError(f"Wallet metrics DB not found at {source}")
    target = destination
    if target is None:
        timestamp = int(time.time())
        target = cfg.CACHE_DIR / f"wallet_metrics_snapshot_{timestamp}.duckdb"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def load_first_seen_cache() -> pd.DataFrame:
    cached = read_parquet(FIRST_SEEN_CACHE_PATH)
    if cached is None:
        return pd.DataFrame(columns=["address", "first_seen"])
    cached["first_seen"] = pd.to_datetime(cached["first_seen"], utc=True)
    cached["address"] = cached["address"].astype(str)
    cached = cached[cached["first_seen"] >= METRICS_DATA_START]
    return cached.reset_index(drop=True)


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
    combined["first_seen"] = pd.to_datetime(combined["first_seen"], utc=True)
    combined = combined[combined["first_seen"] >= METRICS_DATA_START]
    write_parquet(FIRST_SEEN_CACHE_PATH, combined)
    return combined


def _load_funded_d0_cache() -> pd.DataFrame:
    cached = read_parquet(FUNDED_D0_CACHE_PATH)
    if cached is None:
        return pd.DataFrame(columns=FUNDED_D0_COLUMNS)
    frame = cached.copy()
    frame["activation_date"] = pd.to_datetime(frame["activation_date"], utc=True)
    frame["snapshot_version"] = pd.to_datetime(frame["snapshot_version"], utc=True)
    if "ingested_at" in frame.columns:
        frame["ingested_at"] = pd.to_datetime(frame["ingested_at"], utc=True)
    if "updated_at" in frame.columns:
        frame["updated_at"] = pd.to_datetime(frame["updated_at"], utc=True)
    frame["address"] = frame["address"].astype(str)
    return frame


def _activation_frame(first_seen: pd.DataFrame) -> pd.DataFrame:
    if first_seen.empty:
        return pd.DataFrame(columns=["address", "first_seen", "activation_date"])
    frame = first_seen.copy()
    frame["first_seen"] = pd.to_datetime(frame["first_seen"], utc=True)
    frame["address"] = frame["address"].astype(str)
    frame = frame[frame["first_seen"] >= METRICS_DATA_START]
    frame["activation_date"] = frame["first_seen"].dt.floor("D")
    return frame[["address", "first_seen", "activation_date"]]


def ensure_activation_day_funded_snapshots(
    first_seen: pd.DataFrame,
    *,
    lookback_days: int = 3,
    batch_size: int = 200,
    concurrency: int = 8,
    delay_seconds: float = 0.5,
    funded_threshold_stx: float = 10.0,
    db_path: Path | None = None,
) -> int:
    """Ensure funded snapshots exist for wallets activated in the recent window."""

    if first_seen.empty or lookback_days <= 0:
        return 0

    activation = _activation_frame(first_seen)
    if activation.empty:
        return 0

    today = pd.Timestamp(_utc_now()).tz_convert("UTC").floor("D")
    cutoff = today - pd.Timedelta(days=max(lookback_days - 1, 0))
    scoped = activation[activation["activation_date"] >= cutoff]
    if scoped.empty:
        return 0

    inserted = 0
    for activation_date, rows in scoped.groupby("activation_date"):
        addresses = rows["address"].astype(str).tolist()
        inserted += ensure_wallet_balances(
            addresses,
            as_of_date=activation_date.date(),
            funded_threshold_stx=funded_threshold_stx,
            batch_size=batch_size,
            max_workers=concurrency,
            delay_seconds=delay_seconds,
            db_path=db_path,
        )
    return inserted


def collect_activation_day_funding(
    first_seen: pd.DataFrame,
    *,
    db_path: Path | None = None,
    fallback_db_path: Path | None = None,
    persist: bool = True,
) -> pd.DataFrame:
    """Return funded-on-D0 snapshots for all known wallets.

    The helper loads cached funded snapshots when available and only fetches
    balances for activation dates (address, D0) that do not yet have a persisted
    entry. Optional fallback_db_path allows reading from a secondary DuckDB
    (e.g., the canonical DB) when the primary path is a read-only snapshot.
    """

    activation = _activation_frame(first_seen)
    if activation.empty:
        empty = pd.DataFrame(columns=FUNDED_D0_COLUMNS)
        if persist:
            write_parquet(FUNDED_D0_CACHE_PATH, empty)
        return empty

    cached = _load_funded_d0_cache()
    merged = activation.merge(
        cached,
        on=["address", "activation_date"],
        how="left",
        suffixes=("", "_cached"),
    )
    needs_refresh = ~merged["has_snapshot"].fillna(False)
    pending = merged.loc[needs_refresh, ["address", "activation_date"]].copy()
    pending["address"] = pending["address"].astype(str)
    pending["activation_date"] = pd.to_datetime(pending["activation_date"], utc=True)

    def _fetch_from_db(requests: pd.DataFrame, path: Path | None) -> pd.DataFrame:
        if path is None or requests.empty:
            return pd.DataFrame(
                columns=["address", "as_of_date", "balance_ustx", "funded", "ingested_at"]
            )
        records: list[pd.DataFrame] = []
        with _connect(read_only=True, db_path=path) as conn:
            for activation_date, group in requests.groupby("activation_date"):
                addr_batch = group["address"].tolist()
                try:
                    df = conn.execute(
                        """
                        SELECT address, as_of_date, balance_ustx, funded, ingested_at
                        FROM wallet_balances
                        WHERE as_of_date = ?
                          AND address IN (SELECT * FROM UNNEST(?))
                        """,
                        [activation_date.date(), addr_batch],
                    ).fetchdf()
                except duckdb.CatalogException:
                    continue
                if df.empty:
                    continue
                df["address"] = df["address"].astype(str)
                df["as_of_date"] = pd.to_datetime(df["as_of_date"], utc=True).dt.floor("D")
                df["ingested_at"] = pd.to_datetime(df["ingested_at"], utc=True)
                records.append(df)
        if not records:
            return pd.DataFrame(
                columns=["address", "as_of_date", "balance_ustx", "funded", "ingested_at"]
            )
        return pd.concat(records, ignore_index=True)

    pending_remaining = pending.copy()
    lookup_paths: list[Path | None] = [db_path, fallback_db_path]
    fetched_frames: list[pd.DataFrame] = []
    for path in lookup_paths:
        if pending_remaining.empty:
            break
        fetched = _fetch_from_db(pending_remaining, path)
        if fetched.empty:
            continue
        fetched_frames.append(fetched)
        found_keys = set(zip(fetched["address"], fetched["as_of_date"]))
        mask = pending_remaining.apply(
            lambda row: (row["address"], row["activation_date"].floor("D")) not in found_keys,
            axis=1,
        )
        pending_remaining = pending_remaining[mask]

    new_rows: list[pd.DataFrame] = []
    if fetched_frames:
        fetched_all = pd.concat(fetched_frames, ignore_index=True)
        fetched_all = fetched_all.rename(columns={"as_of_date": "snapshot_version"})
        fetched_all["funded_d0"] = fetched_all["funded"].astype(bool)
        fetched_all["has_snapshot"] = True
        fetched_all["updated_at"] = pd.Timestamp(_utc_now()).tz_convert("UTC")
        fetched_all["activation_date"] = fetched_all["snapshot_version"]
        new_rows.append(
            fetched_all[
                [
                    "address",
                    "activation_date",
                    "snapshot_version",
                    "funded_d0",
                    "balance_ustx",
                    "has_snapshot",
                    "ingested_at",
                    "updated_at",
                ]
            ]
        )

    if not pending_remaining.empty:
        placeholders = pending_remaining.copy()
        placeholders = placeholders.rename(columns={"activation_date": "snapshot_version"})
        placeholders["funded_d0"] = False
        placeholders["balance_ustx"] = pd.NA
        placeholders["has_snapshot"] = False
        placeholders["ingested_at"] = pd.NaT
        placeholders["updated_at"] = pd.Timestamp(_utc_now()).tz_convert("UTC")
        placeholders["activation_date"] = placeholders["snapshot_version"]
        new_rows.append(
            placeholders[
                [
                    "address",
                    "activation_date",
                    "snapshot_version",
                    "funded_d0",
                    "balance_ustx",
                    "has_snapshot",
                    "ingested_at",
                    "updated_at",
                ]
            ]
        )

    base = cached if not cached.empty else pd.DataFrame(columns=FUNDED_D0_COLUMNS)
    if new_rows:
        updates = pd.concat(new_rows, ignore_index=True)
        updates = updates[FUNDED_D0_COLUMNS]
        if not updates.empty:
            base = pd.concat([base, updates], ignore_index=True)
        base = base.sort_values("updated_at").drop_duplicates(
            subset=["address", "activation_date"], keep="last"
        )

    result = activation.merge(
        base,
        on=["address", "activation_date"],
        how="left",
    )
    result["has_snapshot"] = result["has_snapshot"].fillna(False)
    result["funded_d0"] = result["funded_d0"].fillna(False)
    result["balance_ustx"] = result["balance_ustx"].where(result["has_snapshot"], pd.NA)
    result["snapshot_version"] = result["snapshot_version"].where(
        result["has_snapshot"], pd.NaT
    )
    result["ingested_at"] = result["ingested_at"].where(result["has_snapshot"], pd.NaT)
    result["updated_at"] = result["updated_at"].where(
        result["updated_at"].notna(),
        pd.Timestamp(_utc_now()).tz_convert("UTC"),
    )

    if persist:
        write_parquet(FUNDED_D0_CACHE_PATH, result[FUNDED_D0_COLUMNS])
    return result[FUNDED_D0_COLUMNS]


def compute_value_flags(
    activity: pd.DataFrame,
    first_seen: pd.DataFrame,
    *,
    window_days: int = 30,
    min_fee_stx: float = 1.0,
) -> pd.DataFrame:
    """Return value_30d flags derived from cached fee totals."""

    columns = ["address", "activation_date", "value_30d"]
    if activity.empty or first_seen.empty:
        return pd.DataFrame(columns=columns)

    activation = _activation_frame(first_seen)
    if activation.empty:
        return pd.DataFrame(columns=columns)

    merged = activity.merge(
        activation[["address", "activation_date"]],
        on="address",
        how="inner",
    )
    if merged.empty:
        result = activation[["address", "activation_date"]].copy()
        result["value_30d"] = False
        return result

    merged["days_since_activation"] = (
        merged["activity_date"] - merged["activation_date"]
    ).dt.days
    merged = merged[
        (merged["days_since_activation"] >= 0)
        & (merged["days_since_activation"] <= window_days)
    ].copy()
    merged["fee_ustx"] = merged["fee_ustx"].fillna(0)

    if merged.empty:
        fee_totals = {}
    else:
        merged["fee_stx"] = merged["fee_ustx"].astype(float) / MICROSTX_PER_STX
        fee_totals = merged.groupby("address")["fee_stx"].sum().to_dict()

    result = activation[["address", "activation_date"]].copy()
    result["value_30d"] = (
        result["address"].map(fee_totals).fillna(0.0) >= min_fee_stx
    )
    return result


def _persist_retention_segmented(
    panel: pd.DataFrame, *, db_path: Path | None = None
) -> None:
    write_parquet(SEGMENTED_RETENTION_PATH, panel)
    with _connect(db_path=db_path) as conn:
        _ensure_schema(conn)
        conn.execute("DELETE FROM retention_segmented")
        if panel.empty:
            return
        store_df = panel.copy()
        store_df["updated_at"] = (
            pd.to_datetime(store_df["updated_at"])
            .dt.tz_convert("UTC")
            .dt.tz_localize(None)
        )
        if "anchor_window_days" not in store_df.columns:
            store_df["anchor_window_days"] = pd.NA
        conn.register("incoming_retention_segmented", store_df)
        conn.execute(
            "INSERT OR REPLACE INTO retention_segmented BY NAME "
            "SELECT * FROM incoming_retention_segmented"
        )
        conn.unregister("incoming_retention_segmented")


def compute_segmented_retention_panel(
    activity: pd.DataFrame,
    first_seen: pd.DataFrame,
    windows: Sequence[int],
    *,
    funded_activation: pd.DataFrame,
    value_flags: pd.DataFrame,
    today: pd.Timestamp | None = None,
    persist: bool = True,
    db_path: Path | None = None,
) -> pd.DataFrame:
    """Aggregate retention for All / Value / Non-value segments."""

    columns = [
        "window_days",
        "segment",
        "retained_users",
        "eligible_users",
        "retention_pct",
        "anchor_window_days",
        "updated_at",
    ]
    if (
        activity.empty
        or first_seen.empty
        or funded_activation.empty
        or not windows
    ):
        panel = pd.DataFrame(columns=columns)
        if persist:
            _persist_retention_segmented(panel, db_path=db_path)
        return panel

    activation = _activation_frame(first_seen)
    scoped = activation.merge(
        funded_activation[
            ["address", "activation_date", "funded_d0", "has_snapshot"]
        ],
        on=["address", "activation_date"],
        how="left",
    )
    scoped["funded_d0"] = scoped["funded_d0"].fillna(False)
    scoped["has_snapshot"] = scoped["has_snapshot"].fillna(False)
    qualified = scoped[(scoped["funded_d0"]) & (scoped["has_snapshot"])]
    if qualified.empty:
        panel = pd.DataFrame(columns=columns)
        if persist:
            _persist_retention_segmented(panel, db_path=db_path)
        return panel

    qualified = qualified.merge(
        value_flags[["address", "activation_date", "value_30d"]],
        on=["address", "activation_date"],
        how="left",
    )
    qualified["value_30d"] = qualified["value_30d"].fillna(False)

    membership_frames: list[pd.DataFrame] = [
        qualified[["address", "first_seen", "activation_date"]].assign(segment="All")
    ]
    value_subset = qualified[qualified["value_30d"]]
    if not value_subset.empty:
        membership_frames.append(
            value_subset[["address", "first_seen", "activation_date"]].assign(segment="Value")
        )
    non_value_subset = qualified[~qualified["value_30d"]]
    if not non_value_subset.empty:
        membership_frames.append(
            non_value_subset[["address", "first_seen", "activation_date"]].assign(
                segment="Non-value"
            )
        )
    membership = pd.concat(membership_frames, ignore_index=True)
    if membership.empty:
        panel = pd.DataFrame(columns=columns)
        if persist:
            _persist_retention_segmented(panel, db_path=db_path)
        return panel

    membership["activation_date"] = membership["activation_date"].dt.floor("D")
    membership["first_seen"] = pd.to_datetime(membership["first_seen"], utc=True)
    membership["address"] = membership["address"].astype(str)
    membership = membership.drop_duplicates(subset=["address", "segment"])

    segment_activity = activity.merge(
        membership[["address", "segment", "activation_date", "first_seen"]],
        on="address",
        how="inner",
    )
    if segment_activity.empty:
        panel = pd.DataFrame(columns=columns)
        if persist:
            _persist_retention_segmented(panel, db_path=db_path)
        return panel

    segment_activity["days_since_activation"] = (
        segment_activity["activity_date"] - segment_activity["activation_date"]
    ).dt.days
    segment_activity = segment_activity[segment_activity["days_since_activation"] >= 0]

    windows = sorted(set(int(w) for w in windows if int(w) > 0))
    if not windows:
        panel = pd.DataFrame(columns=columns)
        if persist:
            _persist_retention_segmented(panel, db_path=db_path)
        return panel

    if today is None:
        today = pd.Timestamp(_utc_now()).tz_convert("UTC").floor("D")
    else:
        today = (
            today.tz_convert("UTC").floor("D")
            if today.tzinfo
            else pd.Timestamp(today).tz_localize("UTC").floor("D")
        )

    cohort_sizes = (
        membership.groupby(["segment", "activation_date"])["address"]
        .nunique()
        .rename("cohort_size")
    )
    if cohort_sizes.empty:
        panel = pd.DataFrame(columns=columns)
        if persist:
            _persist_retention_segmented(panel, db_path=db_path)
        return panel

    anchor_window: int | None = None
    maturity_anchor: pd.Timestamp | None = None
    eligible_anchor: pd.Series | None = None
    for candidate in sorted(windows, reverse=True):
        maturity_cutoff = today - pd.Timedelta(days=candidate)
        eligible = cohort_sizes[
            cohort_sizes.index.get_level_values("activation_date") <= maturity_cutoff
        ]
        if eligible.empty:
            continue
        anchor_window = candidate
        maturity_anchor = maturity_cutoff
        eligible_anchor = eligible
        break
    if anchor_window is None or eligible_anchor is None or maturity_anchor is None:
        panel = pd.DataFrame(columns=columns)
        if persist:
            _persist_retention_segmented(panel, db_path=db_path)
        return panel

    usable_windows = [w for w in windows if w <= anchor_window]
    if not usable_windows:
        panel = pd.DataFrame(columns=columns)
        if persist:
            _persist_retention_segmented(panel, db_path=db_path)
        return panel

    eligible_totals = eligible_anchor.reset_index().groupby("segment")["cohort_size"].sum()
    segments = sorted(eligible_totals.index.tolist())

    results: list[dict[str, object]] = []
    for window in usable_windows:
        engaged_mask = (segment_activity["days_since_activation"] > 0) & (
            segment_activity["days_since_activation"] <= window
        )
        engaged = (
            segment_activity[engaged_mask]
            .drop_duplicates(subset=["segment", "activation_date", "address"])
            .groupby(["segment", "activation_date"])["address"]
            .nunique()
            .rename("retained_users")
        )
        if not engaged.empty:
            engaged = engaged[
                engaged.index.get_level_values("activation_date") <= maturity_anchor
            ]
        retained_totals = (
            engaged.reset_index().groupby("segment")["retained_users"].sum()
            if not engaged.empty
            else pd.Series(dtype=float)
        )
        for segment in segments:
            eligible_total = int(eligible_totals.get(segment, 0))
            if eligible_total == 0:
                continue
            retained_total = int(retained_totals.get(segment, 0))
            pct = retained_total / eligible_total * 100 if eligible_total else 0.0
            results.append(
                {
                    "window_days": int(window),
                    "segment": segment,
                    "retained_users": retained_total,
                    "eligible_users": eligible_total,
                    "retention_pct": pct,
                    "anchor_window_days": int(anchor_window),
                    "updated_at": pd.Timestamp(_utc_now()).tz_convert("UTC"),
                }
            )

    panel = pd.DataFrame(results, columns=columns) if results else pd.DataFrame(columns=columns)
    if not panel.empty:
        panel = panel[columns]
    if persist:
        _persist_retention_segmented(panel, db_path=db_path)
    return panel


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


def _resolve_retention_band(window: int, band_days: Mapping[int, int] | None) -> int:
    """Return the trailing band (days) to use for an activation window."""
    if band_days and window in band_days:
        band = int(band_days[window])
    else:
        band = 15 if window <= 15 else 30
    if band <= 0:
        raise ValueError("band_days must be positive")
    return min(window, band)


def compute_retention(
    activity: pd.DataFrame,
    first_seen: pd.DataFrame,
    windows: Sequence[int],
    *,
    today: pd.Timestamp | None = None,
    mode: str = "cumulative",
    band_days: Mapping[int, int] | None = None,
) -> pd.DataFrame:
    """Compute activation-aligned retention.

    Args:
        activity: Transaction activity with `activity_date` column.
        first_seen: First successful canonical transaction per address.
        windows: Iterable of activation windows in days.
        today: Optional anchor date for maturity checks.
        mode: "cumulative" (default) counts wallets with any activity in (0, H].
              "active_band" counts wallets with activity in the trailing band
              (H - band_days[H], H].
        band_days: Optional mapping window_days -> trailing band size. Defaults
              to 15 days for the 15-day window and 30 days for >=30-day windows.
    """
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

    sanitized_first_seen = first_seen.copy()
    sanitized_first_seen["first_seen"] = pd.to_datetime(
        sanitized_first_seen["first_seen"], utc=True
    )
    sanitized_first_seen = sanitized_first_seen[
        sanitized_first_seen["first_seen"] >= METRICS_DATA_START
    ]
    if sanitized_first_seen.empty:
        return pd.DataFrame(
            columns=[
                "activation_date",
                "window_days",
                "cohort_size",
                "retained_wallets",
                "retention_rate",
            ]
        )

    merged = activity.merge(sanitized_first_seen, on="address", how="left")
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

    mode = mode.lower()
    if mode not in {"cumulative", "active_band"}:
        raise ValueError("mode must be 'cumulative' or 'active_band'")

    results: list[dict[str, object]] = []
    for window in windows:
        eligible_dates = cohort_sizes.index[
            cohort_sizes.index <= today - pd.Timedelta(days=window)
        ]
        if eligible_dates.empty:
            continue

        if mode == "cumulative":
            lower = 0
        else:
            band = _resolve_retention_band(window, band_days)
            lower = max(window - band, 0)

        engaged_mask = (merged["days_since_activation"] > lower) & (
            merged["days_since_activation"] <= window
        )
        engaged = (
            merged[engaged_mask]
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
def load_retention_segmented() -> pd.DataFrame:
    cached = read_parquet(SEGMENTED_RETENTION_PATH)
    if cached is None:
        return pd.DataFrame(
            columns=[
                "window_days",
                "segment",
                "retained_users",
                "eligible_users",
                "retention_pct",
                "anchor_window_days",
                "updated_at",
            ]
        )
    cached["updated_at"] = pd.to_datetime(cached["updated_at"], utc=True, errors="coerce")
    cached["window_days"] = pd.to_numeric(cached["window_days"], errors="coerce").astype("Int64")
    cached["segment"] = cached["segment"].astype(str)
    if "anchor_window_days" not in cached.columns:
        cached["anchor_window_days"] = pd.NA
    return cached
