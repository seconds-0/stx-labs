"""Signal21 SQL utilities for transaction fee analytics with caching."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from . import config as cfg
from .cache_utils import read_parquet, write_parquet
from .signal21 import run_sql_query


logger = logging.getLogger(__name__)


def _fee_chunk_sql(start_epoch: int, end_epoch: int) -> str:
    return f"""
        SELECT
            b.burn_block_height,
            SUM(t.fee_rate)::numeric / 1e6 AS fees_stx_sum,
            COUNT(t.tx_hash) AS tx_count
        FROM stx.txs AS t
        JOIN stx.blocks AS b
          ON b.block_hash = t.block_hash
        WHERE t.canonical = TRUE
          AND t.burn_block_time >= {start_epoch}
          AND t.burn_block_time < {end_epoch}
        GROUP BY b.burn_block_height
        ORDER BY b.burn_block_height;
    """

SIGNAL21_CACHE_DIR = cfg.CACHE_DIR / "signal21"
SIGNAL21_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _fees_cache_path(label: str) -> Path:
    return SIGNAL21_CACHE_DIR / f"{label}.parquet"


def _fee_day_sql(day_start_epoch: int, day_end_epoch: int) -> str:
    return f"""
        SELECT
            TO_TIMESTAMP({day_start_epoch})::date AS fee_day,
            AVG(fee_stx) AS avg_fee_stx,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY fee_stx) AS median_fee_stx,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY fee_stx) AS p25_fee_stx,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY fee_stx) AS p75_fee_stx
        FROM (
            SELECT
                (t.fee_rate * COALESCE(octet_length(t.raw_tx), 0))::numeric / 1e6 AS fee_stx
            FROM stx.txs AS t
            WHERE t.canonical = TRUE
              AND t.burn_block_time >= {day_start_epoch}
              AND t.burn_block_time < {day_end_epoch}
        ) AS fees;
    """


def fetch_fees_by_tenure(
    *,
    start_epoch: int | None = None,
    end_epoch: int | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Fetch summed STX fees per burn block height."""
    now_epoch = int(datetime.now(UTC).timestamp())
    if end_epoch is None:
        end_epoch = now_epoch
    if start_epoch is None:
        start_epoch = int(
            (datetime.now(UTC) - timedelta(days=cfg.default_date_horizon_days())).timestamp()
        )
    if start_epoch > end_epoch:
        raise ValueError("start_epoch must be <= end_epoch")
    logger.info(
        "Summing fees by tenure from %s to %s (epoch seconds)",
        start_epoch,
        end_epoch,
    )
    label = f"fees_by_tenure_{start_epoch or 'min'}_{end_epoch or 'max'}"
    cache_path = _fees_cache_path(label)
    if not force_refresh:
        cached = read_parquet(cache_path)
        if cached is not None:
            cached["burn_block_height"] = cached["burn_block_height"].astype(int)
            cached["fees_stx_sum"] = cached["fees_stx_sum"].astype(float)
            cached["tx_count"] = cached["tx_count"].astype(int)
            return cached.sort_values("burn_block_height")

    try:
        frames: list[pd.DataFrame] = []
        full_window = max(end_epoch - start_epoch, 0)
        minimal_chunk = 12 * 3600
        chunk_seconds = max(full_window, minimal_chunk) or minimal_chunk
        cursor = start_epoch
        logger.debug("Initial fee chunk size: %s seconds", chunk_seconds)
        while cursor < end_epoch:
            chunk_end = min(cursor + chunk_seconds, end_epoch)
            try:
                df_chunk = run_sql_query(
                    _fee_chunk_sql(cursor, chunk_end),
                    force_refresh=force_refresh,
                )
            except Exception as exc:
                if chunk_seconds <= minimal_chunk:
                    logger.error(
                        "Fee chunk [%s, %s) failed and cannot reduce further: %s",
                        cursor,
                        chunk_end,
                        exc,
                    )
                    raise
                chunk_seconds = max(minimal_chunk, chunk_seconds // 2)
                logger.warning(
                    "Fee chunk [%s, %s) failed (%s); reducing chunk size to %s seconds",
                    cursor,
                    chunk_end,
                    exc,
                    chunk_seconds,
                )
                continue
            if not df_chunk.empty:
                logger.debug(
                    "Fetched %s fee rows for chunk [%s, %s)",
                    len(df_chunk),
                    cursor,
                    chunk_end,
                )
                frames.append(df_chunk)
            cursor = chunk_end
        if not frames:
            df = pd.DataFrame(columns=["burn_block_height", "fees_stx_sum", "tx_count"])
        else:
            df = (
                pd.concat(frames, ignore_index=True)
                .groupby("burn_block_height", as_index=False)
                .agg({"fees_stx_sum": "sum", "tx_count": "sum"})
            )
    except Exception as exc:
        cached = read_parquet(cache_path)
        if cached is not None:
            return cached.sort_values("burn_block_height")
        import warnings

        warnings.warn(
            f"Signal21 fee query failed ({exc}); returning empty fee table.",
            RuntimeWarning,
        )
        return pd.DataFrame(
            columns=["burn_block_height", "fees_stx_sum", "tx_count"], dtype=float
        )

    if df.empty:
        return df
    df["burn_block_height"] = df["burn_block_height"].astype(int)
    df["fees_stx_sum"] = df["fees_stx_sum"].astype(float)
    df["tx_count"] = df["tx_count"].astype(int)
    df = df.sort_values("burn_block_height")
    write_parquet(cache_path, df)
    logger.info("Fee aggregation produced %s burn blocks", len(df))
    return df


def fetch_fee_per_tx_summary(window_days: int, *, force_refresh: bool = False) -> pd.DataFrame:
    """Fetch per-transaction fee statistics for a trailing window."""
    cache_path = _fees_cache_path(f"fee_per_tx_{window_days}d")
    if not force_refresh:
        cached = read_parquet(cache_path)
        if cached is not None:
            cached["fee_day"] = pd.to_datetime(cached["fee_day"])
            return cached.sort_values("fee_day")

    end_epoch = int(datetime.now(UTC).timestamp())
    start_epoch = end_epoch - window_days * 24 * 3600
    day_cursor = datetime.fromtimestamp(start_epoch, tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = datetime.fromtimestamp(end_epoch, tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    frames: list[pd.DataFrame] = []
    while day_cursor <= end_day:
        day_start_epoch = int(day_cursor.timestamp())
        day_end_epoch = int((day_cursor + timedelta(days=1)).timestamp())
        try:
            df_day = run_sql_query(_fee_day_sql(day_start_epoch, day_end_epoch), force_refresh=force_refresh)
        except Exception as exc:
            logger.warning(
                "Fee-per-tx query failed for day %s (%s); recording NaNs",
                day_cursor.date(),
                exc,
            )
            df_day = pd.DataFrame({
                "fee_day": [day_cursor.date()],
                "avg_fee_stx": [None],
                "median_fee_stx": [None],
                "p25_fee_stx": [None],
                "p75_fee_stx": [None],
            })
        else:
            logger.debug("Fetched fee-per-tx stats for %s", day_cursor.date())
        frames.append(df_day)
        day_cursor += timedelta(days=1)

    df = pd.concat(frames, ignore_index=True)
    df["fee_day"] = pd.to_datetime(df["fee_day"])
    df = df.sort_values("fee_day")
    write_parquet(cache_path, df)
    return df
