"""PoX stacking yield calculation module.

Provides functions to:
- Fetch PoX cycle data from Hiro API
- Aggregate BTC rewards per cycle
- Calculate stacker yields (APY in BTC and USD terms)
- Calculate participation rates

Ref: docs/yield_competitiveness_implementation_plan.md
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from . import config as cfg
from . import cycle_utils
from . import pox_constants as const
from . import prices
from .cache_utils import read_parquet, write_parquet
from .hiro import aggregate_rewards_by_burn_block, fetch_block_by_height, list_pox_cycles

# Legacy constants (kept for backwards compatibility, prefer pox_constants.*)
DEFAULT_CIRCULATING_SUPPLY_USTX = const.DEFAULT_CIRCULATING_SUPPLY_USTX
POX_CYCLE_DAYS = const.POX_CYCLE_DAYS
DAYS_PER_YEAR = const.DAYS_PER_YEAR


POX_YIELDS_CACHE_DIR = cfg.CACHE_DIR / "pox_yields"
POX_YIELDS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
CYCLE_BURN_HEIGHTS_CACHE = POX_YIELDS_CACHE_DIR / "cycle_burn_heights.parquet"

LOGGER = logging.getLogger(__name__)


def _pox_cycles_cache_path() -> Path:
    """Cache path for PoX cycles with metadata."""
    return POX_YIELDS_CACHE_DIR / "pox_cycles_with_rewards.parquet"


def _aggregate_rewards_by_cycle_cache_path(
    start_cycle: int | None, end_cycle: int | None
) -> Path:
    """Cache path for aggregated rewards by cycle."""
    label = "all"
    if start_cycle is not None or end_cycle is not None:
        label = f"{start_cycle or 'min'}_{end_cycle or 'max'}"
    return POX_YIELDS_CACHE_DIR / f"rewards_by_cycle_{label}.parquet"


def _load_cycle_burn_cache() -> pd.DataFrame:
    cached = read_parquet(CYCLE_BURN_HEIGHTS_CACHE)
    if cached is None:
        return pd.DataFrame(
            columns=["stack_block_height", "burn_block_height", "burn_block_time"],
        )
    if "burn_block_time" not in cached.columns:
        cached["burn_block_time"] = pd.NA
    cached["stack_block_height"] = cached["stack_block_height"].astype(int)
    cached["burn_block_height"] = cached["burn_block_height"].astype(int)
    cached["burn_block_time"] = pd.to_numeric(
        cached["burn_block_time"], errors="coerce"
    ).astype("Int64")
    return cached


def _persist_cycle_burn_cache(df: pd.DataFrame) -> None:
    if df.empty:
        CYCLE_BURN_HEIGHTS_CACHE.unlink(missing_ok=True)
        return
    write_parquet(CYCLE_BURN_HEIGHTS_CACHE, df)


def _attach_cycle_burn_heights(
    cycles_df: pd.DataFrame, *, force_refresh: bool
) -> pd.DataFrame:
    """Ensure each cycle row has a burn_block_height derived from Stack heights."""
    if "stack_block_height" not in cycles_df.columns:
        cycles_df = cycles_df.rename(columns={"block_height": "stack_block_height"})

    cache_df = pd.DataFrame(
        columns=["stack_block_height", "burn_block_height", "burn_block_time"]
    )
    if not force_refresh:
        cache_df = _load_cycle_burn_cache()

    known_heights = set(cache_df["stack_block_height"].tolist())
    requested_heights = {
        int(h)
        for h in cycles_df["stack_block_height"].dropna().astype(int).tolist()
        if int(h) not in known_heights
    }

    if requested_heights:
        new_records: list[dict[str, int]] = []
        for height in sorted(requested_heights):
            try:
                payload = fetch_block_by_height(height, force_refresh=force_refresh)
            except Exception as exc:  # pragma: no cover - defensive logging
                LOGGER.warning("Failed to fetch block metadata for height %s: %s", height, exc)
                continue
            burn_height = payload.get("burn_block_height")
            if burn_height is None:
                LOGGER.warning("Missing burn_block_height for stack height %s", height)
                continue
            new_records.append(
                {
                    "stack_block_height": int(height),
                    "burn_block_height": int(burn_height),
                    "burn_block_time": int(payload.get("burn_block_time", 0) or 0),
                }
            )
        if new_records:
            new_df = pd.DataFrame(new_records)
            cache_df = (
                pd.concat([cache_df, new_df], ignore_index=True)
                .drop_duplicates(subset=["stack_block_height"], keep="last")
                .sort_values("stack_block_height")
            )
            _persist_cycle_burn_cache(cache_df)

    merged = cycles_df.merge(
        cache_df,
        on="stack_block_height",
        how="left",
    )
    merged["burn_block_height"] = pd.to_numeric(
        merged["burn_block_height"], errors="coerce"
    )
    merged["burn_block_time"] = pd.to_numeric(
        merged["burn_block_time"], errors="coerce"
    )
    merged["block_height"] = merged["burn_block_height"].fillna(
        merged["stack_block_height"]
    )
    return merged


def compute_cycle_price_averages(
    cycles_df: pd.DataFrame,
    *,
    start_cycle: int | None = None,
    end_cycle: int | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Return average STX/USD, BTC/USD, and STX/BTC per cycle."""
    if "burn_block_time" not in cycles_df.columns:
        return pd.DataFrame(
            columns=["cycle_number", "stx_usd_avg", "btc_usd_avg", "stx_btc_avg"]
        )

    filtered = cycles_df.copy()
    if start_cycle is not None:
        filtered = filtered[filtered["cycle_number"] >= start_cycle]
    if end_cycle is not None:
        filtered = filtered[filtered["cycle_number"] <= end_cycle]

    if filtered.empty:
        return pd.DataFrame(
            columns=["cycle_number", "stx_usd_avg", "btc_usd_avg", "stx_btc_avg"]
        )

    filtered = filtered.sort_values("cycle_number").reset_index(drop=True)
    filtered["start_ts"] = pd.to_datetime(
        filtered["burn_block_time"], unit="s", utc=True
    )
    filtered["end_ts"] = filtered["start_ts"].shift(-1)
    filtered.loc[filtered.index[-1], "end_ts"] = filtered.loc[
        filtered.index[-1], "start_ts"
    ] + timedelta(days=POX_CYCLE_DAYS)

    price_start = filtered["start_ts"].min().to_pydatetime()
    price_end = filtered["end_ts"].max().to_pydatetime()

    price_panel = prices.load_price_panel(
        price_start,
        price_end,
        frequency="4h",
        force_refresh=force_refresh,
    )
    price_panel["ts"] = pd.to_datetime(price_panel["ts"], utc=True)

    records: list[dict[str, float | int]] = []
    for _, row in filtered.iterrows():
        start_ts = row["start_ts"]
        end_ts = row["end_ts"]
        mask = (price_panel["ts"] >= start_ts) & (price_panel["ts"] < end_ts)
        subset = price_panel.loc[mask]
        if subset.empty:
            continue
        records.append(
            {
                "cycle_number": int(row["cycle_number"]),
                "stx_usd_avg": float(subset["stx_usd"].mean()),
                "btc_usd_avg": float(subset["btc_usd"].mean()),
                "stx_btc_avg": float(subset["stx_btc"].mean()),
            }
        )
    return pd.DataFrame(records)


def calculate_apy_btc(
    total_btc_sats: int | float,
    total_stacked_ustx: int | float,
    *,
    pox_cycle_days: int = const.POX_CYCLE_DAYS,
) -> float:
    """Calculate BTC-denominated APY for PoX stacking.

    This is the canonical APY calculation used throughout the codebase.
    Centralizing this formula ensures consistency and simplifies maintenance.

    Formula:
        APY_BTC = (total_btc_sats / total_stacked_ustx) * (365 / cycle_days) * 100 * 1M

    Where:
        - total_btc_sats: Total BTC rewards committed in satoshis
        - total_stacked_ustx: Total STX stacked in microSTX
        - pox_cycle_days: Duration of PoX cycle in days (default 14)
        - 1M multiplier: Converts microSTX to STX for per-STX calculation

    Args:
        total_btc_sats: Total BTC rewards in satoshis
        total_stacked_ustx: Total STX stacked in microSTX
        pox_cycle_days: Days per PoX cycle (default from constants)

    Returns:
        APY as percentage (e.g., 12.5 for 12.5%)
        Returns 0.0 if total_stacked_ustx is zero

    Example:
        >>> calculate_apy_btc(15_000_000_000, 1_035_000_000_000_000)
        11.94  # 11.94% APY
    """
    if total_stacked_ustx == 0:
        return 0.0

    apy = (
        (total_btc_sats / total_stacked_ustx)
        * (const.DAYS_PER_YEAR / pox_cycle_days)
        * 100
        * const.USTX_PER_STX  # Convert microSTX to STX
    )

    return round(apy, 2)


def fetch_pox_cycles_data(*, force_refresh: bool = False) -> pd.DataFrame:
    """Fetch PoX cycle metadata from Hiro API.

    Retrieves cycle information including:
    - cycle_number
    - stack_block_height (Stacks chain height at cycle start)
    - block_height (burn block height at cycle start)
    - total_weight
    - total_stacked_amount (total STX stacked in microSTX)
    - total_signers

    Results are cached to: pox_yields/pox_cycles_with_rewards.parquet

    Args:
        force_refresh: If True, bypass cache and fetch fresh data

    Returns:
        DataFrame with PoX cycle metadata, sorted by cycle_number descending
    """
    cache_path = _pox_cycles_cache_path()

    if not force_refresh:
        cached = read_parquet(cache_path)
        if cached is not None and "stack_block_height" in cached.columns:
            return cached

    # Use existing hiro.list_pox_cycles() function
    cycles_df = list_pox_cycles(force_refresh=force_refresh)

    if cycles_df.empty:
        return pd.DataFrame(
            columns=[
                "cycle_number",
                "block_height",
                "total_weight",
                "total_stacked_amount",
                "total_signers",
                "stack_block_height",
            ]
        )

    # Preserve original Stacks block height and derive burn heights
    if "block_height" in cycles_df.columns:
        cycles_df = cycles_df.rename(columns={"block_height": "stack_block_height"})
        cycles_df["stack_block_height"] = pd.to_numeric(
            cycles_df["stack_block_height"], errors="coerce"
        )
    cycles_df = _attach_cycle_burn_heights(cycles_df, force_refresh=force_refresh)

    # Ensure numeric types
    if "total_stacked_amount" in cycles_df.columns:
        cycles_df["total_stacked_amount"] = pd.to_numeric(
            cycles_df["total_stacked_amount"], errors="coerce"
        )
    if "cycle_number" in cycles_df.columns:
        cycles_df["cycle_number"] = pd.to_numeric(
            cycles_df["cycle_number"], errors="coerce"
        )

    # Sort by cycle number descending (most recent first)
    cycles_df = cycles_df.sort_values("cycle_number", ascending=False)

    # Cache the result
    write_parquet(cache_path, cycles_df)

    return cycles_df


def aggregate_rewards_by_cycle(
    *,
    start_cycle: int | None = None,
    end_cycle: int | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Aggregate BTC rewards (miner commitments) per PoX cycle.

    Maps burn block heights to PoX cycles and sums total BTC committed
    per cycle by miners.

    Args:
        start_cycle: First PoX cycle to include (inclusive)
        end_cycle: Last PoX cycle to include (inclusive)
        force_refresh: If True, bypass cache and fetch fresh data

    Returns:
        DataFrame with columns:
        - cycle_number: PoX cycle number
        - total_btc_sats: Total BTC committed in cycle (satoshis)
        - total_blocks: Number of burn blocks in cycle
        - avg_btc_per_block_sats: Average BTC per block
    """
    cache_path = _aggregate_rewards_by_cycle_cache_path(start_cycle, end_cycle)

    if not force_refresh:
        cached = read_parquet(cache_path)
        if cached is not None:
            return cached

    # Get PoX cycle metadata
    cycles_df = fetch_pox_cycles_data(force_refresh=force_refresh)

    if cycles_df.empty:
        return pd.DataFrame(
            columns=[
                "cycle_number",
                "total_btc_sats",
                "total_blocks",
                "avg_btc_per_block_sats",
            ]
        )

    # Filter cycles if requested
    filtered_cycles = cycles_df.copy()
    if start_cycle is not None:
        filtered_cycles = filtered_cycles[
            filtered_cycles["cycle_number"] >= start_cycle
        ]
    if end_cycle is not None:
        filtered_cycles = filtered_cycles[filtered_cycles["cycle_number"] <= end_cycle]

    if filtered_cycles.empty:
        return pd.DataFrame(
            columns=[
                "cycle_number",
                "total_btc_sats",
                "total_blocks",
                "avg_btc_per_block_sats",
            ]
        )

    # Determine burn block height range
    # Note: Each cycle has block_height (start) but we need end too
    # For now, aggregate all rewards and map to cycles by burn_block_height

    # Determine burn height bounds for requested cycles to minimize API calls
    start_height = int(filtered_cycles["block_height"].min())
    next_cycle_mask = cycles_df["block_height"] > filtered_cycles["block_height"].max()
    next_cycle = (
        cycles_df[next_cycle_mask].sort_values("block_height").head(1)
    )
    end_height = None
    if not next_cycle.empty:
        end_height = int(next_cycle["block_height"].iloc[0] - 1)

    # Get rewards within the requested burn height range
    rewards_df = aggregate_rewards_by_burn_block(
        start_height=start_height,
        end_height=end_height,
        force_refresh=force_refresh,
    )

    if rewards_df.empty:
        return pd.DataFrame(
            columns=[
                "cycle_number",
                "total_btc_sats",
                "total_blocks",
                "avg_btc_per_block_sats",
            ]
        )

    # Map burn block heights to PoX cycles
    rewards_with_cycle = cycle_utils.map_burn_heights_to_cycles(
        rewards_df, cycles_df, "burn_block_height"
    )

    # Aggregate by cycle
    cycle_rewards = (
        rewards_with_cycle.dropna(subset=["cycle_number"])
        .groupby("cycle_number")
        .agg({"reward_amount_sats_sum": "sum", "burn_block_height": "count"})
        .reset_index()
    )

    cycle_rewards = cycle_rewards.rename(
        columns={
            "reward_amount_sats_sum": "total_btc_sats",
            "burn_block_height": "total_blocks",
        }
    )

    # Calculate average BTC per block
    cycle_rewards["avg_btc_per_block_sats"] = (
        cycle_rewards["total_btc_sats"] / cycle_rewards["total_blocks"]
    ).round(2)

    # Ensure correct types
    cycle_rewards["cycle_number"] = cycle_rewards["cycle_number"].astype(int)
    cycle_rewards["total_btc_sats"] = cycle_rewards["total_btc_sats"].astype(int)
    cycle_rewards["total_blocks"] = cycle_rewards["total_blocks"].astype(int)

    # Sort by cycle number descending
    cycle_rewards = cycle_rewards.sort_values("cycle_number", ascending=False)

    # Cache the result
    write_parquet(cache_path, cycle_rewards)

    return cycle_rewards


def calculate_cycle_apy(
    cycles_df: pd.DataFrame,
    rewards_df: pd.DataFrame,
    prices_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Calculate APY metrics for PoX cycles.

    Computes:
    - BTC-denominated APY: Annual yield in BTC terms
    - USD-denominated APY: Annual yield including STX price appreciation
    - Participation rate: % of STX supply stacked

    Formula for BTC APY:
        APY_BTC = (total_btc_sats / total_stx_stacked) * (365 / cycle_days) * 100

    Args:
        cycles_df: DataFrame from fetch_pox_cycles_data() with total_stacked_amount
        rewards_df: DataFrame from aggregate_rewards_by_cycle() with total_btc_sats
        prices_df: Optional DataFrame with STX/BTC prices for USD APY calculation
                   Expects columns: cycle_number, stx_usd_avg, btc_usd_avg

    Returns:
        DataFrame with columns:
        - cycle_number
        - total_stacked_ustx
        - total_btc_sats
        - participation_rate_pct
        - apy_btc: Annual percentage yield in BTC terms
        - apy_usd: Annual percentage yield in USD terms (if prices provided)
    """
    # Merge cycles and rewards
    merged = cycles_df.merge(rewards_df, on="cycle_number", how="inner")

    if merged.empty:
        return pd.DataFrame(
            columns=[
                "cycle_number",
                "total_stacked_ustx",
                "total_btc_sats",
                "participation_rate_pct",
                "apy_btc",
                "apy_usd",
            ]
        )

    # Calculate participation rate
    merged["participation_rate_pct"] = calculate_participation_rate(
        merged["total_stacked_amount"]
    )

    # Calculate BTC APY using centralized helper
    # Note: total_stacked_amount is in microSTX
    merged["apy_btc"] = merged.apply(
        lambda row: calculate_apy_btc(
            row["total_btc_sats"], row["total_stacked_amount"]
        ),
        axis=1,
    )

    # If prices provided, calculate USD APY
    if (
        prices_df is not None
        and "cycle_number" in prices_df.columns
    ):
        price_cols = ["stx_usd_avg", "btc_usd_avg", "stx_btc_avg"]
        missing_cols = [col for col in price_cols if col not in prices_df.columns]
        if missing_cols:
            raise ValueError(
                f"prices_df missing required columns: {', '.join(missing_cols)}"
            )
        merged = merged.merge(
            prices_df[["cycle_number", "stx_usd_avg", "btc_usd_avg", "stx_btc_avg"]],
            on="cycle_number",
            how="left",
        )

        denom = const.SATS_PER_BTC * merged["stx_btc_avg"]
        mask = denom.notna() & (denom > 0)
        merged.loc[mask, "apy_btc"] = (
            merged.loc[mask, "apy_btc"] / denom.loc[mask]
        )
        merged["apy_btc"] = merged["apy_btc"].round(2)
        merged["apy_usd"] = merged["apy_btc"]
    else:
        merged["apy_btc"] = merged["apy_btc"].round(2)
        merged["apy_usd"] = None

    # Rename for clarity
    result = merged.rename(columns={"total_stacked_amount": "total_stacked_ustx"})

    # Select and order columns
    output_cols = [
        "cycle_number",
        "total_stacked_ustx",
        "total_btc_sats",
        "participation_rate_pct",
        "apy_btc",
    ]
    if "apy_usd" in result.columns and result["apy_usd"].notna().any():
        output_cols.append("apy_usd")

    return result[output_cols].sort_values("cycle_number", ascending=False)


def calculate_participation_rate(
    total_stacked_ustx: pd.Series | int,
    circulating_supply_ustx: int = DEFAULT_CIRCULATING_SUPPLY_USTX,
) -> pd.Series | float:
    """Calculate stacking participation rate as percentage of circulating supply.

    Args:
        total_stacked_ustx: Total STX stacked in microSTX (can be Series or int)
        circulating_supply_ustx: Total circulating STX supply in microSTX

    Returns:
        Participation rate as percentage (0-100)
    """
    if isinstance(total_stacked_ustx, pd.Series):
        return ((total_stacked_ustx / circulating_supply_ustx) * 100).round(2)
    else:
        return round((total_stacked_ustx / circulating_supply_ustx) * 100, 2)


def get_cycle_yield_summary(
    *,
    last_n_cycles: int = 10,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Get summary statistics for PoX yields over recent cycles.

    Convenience function to get quick yield overview for last N cycles.

    Args:
        last_n_cycles: Number of most recent cycles to analyze
        force_refresh: If True, bypass cache

    Returns:
        Dictionary with summary statistics:
        - cycles_analyzed: Number of cycles
        - apy_btc_mean: Mean BTC APY
        - apy_btc_median: Median BTC APY
        - apy_btc_std: Standard deviation of BTC APY
        - apy_btc_min: Minimum BTC APY
        - apy_btc_max: Maximum BTC APY
        - participation_rate_mean: Average participation rate
    """
    # Fetch data
    cycles_df = fetch_pox_cycles_data(force_refresh=force_refresh)
    if cycles_df.empty:
        return {
            "cycles_analyzed": 0,
            "apy_btc_mean": None,
            "apy_btc_median": None,
            "apy_btc_std": None,
            "apy_btc_min": None,
            "apy_btc_max": None,
            "participation_rate_mean": None,
        }

    max_cycle = int(cycles_df["cycle_number"].max())
    min_cycle = max(
        int(cycles_df["cycle_number"].min()),
        max_cycle - (last_n_cycles * 2),
    )

    rewards_df = aggregate_rewards_by_cycle(
        start_cycle=min_cycle,
        end_cycle=max_cycle,
        force_refresh=force_refresh,
    )

    prices_df = compute_cycle_price_averages(
        cycles_df,
        start_cycle=min_cycle,
        end_cycle=max_cycle,
        force_refresh=force_refresh,
    )

    # Calculate APY
    apy_df = calculate_cycle_apy(cycles_df, rewards_df, prices_df=prices_df)

    # Take last N cycles
    recent = apy_df.sort_values("cycle_number", ascending=False).head(last_n_cycles)

    if recent.empty or "apy_btc" not in recent.columns:
        return {
            "cycles_analyzed": 0,
            "apy_btc_mean": None,
            "apy_btc_median": None,
            "apy_btc_std": None,
            "apy_btc_min": None,
            "apy_btc_max": None,
            "participation_rate_mean": None,
        }

    return {
        "cycles_analyzed": len(recent),
        "apy_btc_mean": round(recent["apy_btc"].mean(), 2),
        "apy_btc_median": round(recent["apy_btc"].median(), 2),
        "apy_btc_std": round(recent["apy_btc"].std(), 2),
        "apy_btc_min": round(recent["apy_btc"].min(), 2),
        "apy_btc_max": round(recent["apy_btc"].max(), 2),
        "participation_rate_mean": round(recent["participation_rate_pct"].mean(), 2),
    }
