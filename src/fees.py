"""Signal21 SQL utilities for transaction fee analytics."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from .signal21 import run_sql_query

FEES_PER_TENURE_SQL = """
SELECT
  b.burn_block_height AS burn_block_height,
  SUM(t.fee_ustx) / 1e6 AS fees_stx_sum,
  COUNT(DISTINCT t.tx_hash) AS tx_count
FROM core.txs t
JOIN core.blocks b USING (block_height)
WHERE t.canonical = TRUE
  AND b.canonical = TRUE
GROUP BY b.burn_block_height
ORDER BY b.burn_block_height;
"""


def fetch_fees_by_tenure(*, force_refresh: bool = False) -> pd.DataFrame:
    """Fetch summed STX fees per burn block height."""
    df = run_sql_query(FEES_PER_TENURE_SQL, force_refresh=force_refresh)
    if df.empty:
        return df
    df["burn_block_height"] = df["burn_block_height"].astype(int)
    df["fees_stx_sum"] = df["fees_stx_sum"].astype(float)
    df["tx_count"] = df["tx_count"].astype(int)
    return df.sort_values("burn_block_height")


def fee_per_tx_stats_sql(window_days: int) -> str:
    return f"""
WITH recent_blocks AS (
    SELECT block_height
    FROM core.blocks
    WHERE canonical = TRUE
      AND burn_block_time >= DATEADD('day', -{window_days}, CURRENT_TIMESTAMP)
)
SELECT
    DATE_TRUNC('day', FROM_UNIXTIME(t.burn_block_time)) AS fee_day,
    AVG(t.fee_ustx) / 1e6 AS avg_fee_stx,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY t.fee_ustx / 1e6) AS median_fee_stx,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY t.fee_ustx / 1e6) AS p25_fee_stx,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY t.fee_ustx / 1e6) AS p75_fee_stx
FROM core.txs t
JOIN core.blocks b USING (block_height)
WHERE t.canonical = TRUE
  AND b.block_height IN (SELECT block_height FROM recent_blocks)
GROUP BY 1
ORDER BY 1;
"""


def fetch_fee_per_tx_summary(window_days: int, *, force_refresh: bool = False) -> pd.DataFrame:
    """Fetch per-transaction fee statistics for a trailing window."""
    df = run_sql_query(fee_per_tx_stats_sql(window_days), force_refresh=force_refresh)
    if df.empty:
        return df
    df["fee_day"] = pd.to_datetime(df["fee_day"])
    return df.sort_values("fee_day")
