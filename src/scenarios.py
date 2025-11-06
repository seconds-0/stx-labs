"""Scenario analysis utilities for the PoX flywheel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import pandas as pd

from . import pox_constants as const
from .pox_yields import calculate_apy_btc


@dataclass(frozen=True)
class ScenarioConfig:
    fee_per_tx_stx: float = const.DEFAULT_FEE_PER_TX_STX
    rho_candidates: Sequence[float] = (0.92, const.DEFAULT_COMMITMENT_RATIO, 1.10)
    coinbase_stx: float = const.DEFAULT_COINBASE_STX
    reward_cycles_blocks: int = const.POX_CYCLE_BLOCKS
    stacked_supply_stx: float = 1_350_000_000.0  # placeholder, will be overwritten at runtime


def summarize_miner_rewards(
    rho: float,
    *,
    stx_btc_price: float,
    fees_stx: float,
    coinbase_stx: float | None = None,
    btc_usd_price: float | None = None,
    stx_usd_price: float | None = None,
    stacked_supply_stx: float | None = None,
    cycle_blocks: int | None = None,
) -> dict[str, float | None]:
    """Summarise miner BTC commitments and stacker yields for a given reward setup."""
    coinbase_value = coinbase_stx if coinbase_stx is not None else const.DEFAULT_COINBASE_STX
    blocks_per_cycle = cycle_blocks if cycle_blocks is not None else const.POX_CYCLE_BLOCKS

    reward_stx_total = coinbase_value + fees_stx
    reward_value_btc = reward_stx_total * stx_btc_price
    miner_btc_per_tenure = rho * reward_value_btc
    miner_btc_per_cycle = miner_btc_per_tenure * blocks_per_cycle
    cycles_per_year = const.DAYS_PER_YEAR / const.POX_CYCLE_DAYS
    miner_btc_per_year = miner_btc_per_cycle * cycles_per_year

    reward_value_usd = None
    miner_btc_per_tenure_usd = None
    miner_btc_per_cycle_usd = None
    miner_btc_per_year_usd = None
    if stx_usd_price is not None:
        reward_value_usd = reward_stx_total * stx_usd_price
    if btc_usd_price is not None:
        miner_btc_per_tenure_usd = miner_btc_per_tenure * btc_usd_price
        miner_btc_per_cycle_usd = miner_btc_per_cycle * btc_usd_price
        miner_btc_per_year_usd = miner_btc_per_year * btc_usd_price

    stacker_apy_pct = None
    if stacked_supply_stx:
        total_btc_sats = miner_btc_per_cycle * const.SATS_PER_BTC
        total_stacked_ustx = stacked_supply_stx * const.USTX_PER_STX
        stacker_apy_pct = calculate_apy_btc(
            total_btc_sats=total_btc_sats,
            total_stacked_ustx=total_stacked_ustx,
        )

    return {
        "rho_effective": rho,
        "reward_stx_total": reward_stx_total,
        "reward_value_btc": reward_value_btc,
        "reward_value_usd": reward_value_usd,
        "miner_btc_per_tenure": miner_btc_per_tenure,
        "miner_btc_per_tenure_usd": miner_btc_per_tenure_usd,
        "miner_btc_per_cycle": miner_btc_per_cycle,
        "miner_btc_per_cycle_usd": miner_btc_per_cycle_usd,
        "miner_btc_per_year": miner_btc_per_year,
        "miner_btc_per_year_usd": miner_btc_per_year_usd,
        "stacker_apy_pct": stacker_apy_pct,
    }


def build_scenarios(
    uplift_rates: Iterable[float],
    mean_fee_stx: float,
    mean_stx_btc: float,
    *,
    config: ScenarioConfig | None = None,
) -> pd.DataFrame:
    """Generate scenario table with delta fees, tx counts, and PoX impacts."""
    cfg = config or ScenarioConfig()

    records = []
    for uplift in uplift_rates:
        multiplier = 1 + uplift
        target_reward = multiplier * (cfg.coinbase_stx + mean_fee_stx)
        delta_fee = target_reward - (cfg.coinbase_stx + mean_fee_stx)
        extra_txs = delta_fee / cfg.fee_per_tx_stx if cfg.fee_per_tx_stx else 0.0
        reward_value_sats = target_reward * mean_stx_btc * 1e8
        for rho in cfg.rho_candidates:
            commit_sats = rho * reward_value_sats
            per_cycle_btc = commit_sats * cfg.reward_cycles_blocks
            apy_shift = (
                (per_cycle_btc / 1e8) / cfg.stacked_supply_stx * 365 / 14
                if cfg.stacked_supply_stx
                else 0.0
            )
            records.append(
                {
                    "uplift": uplift,
                    "reward_multiplier": multiplier,
                    "target_reward_stx": target_reward,
                    "delta_fee_stx": delta_fee,
                    "delta_tx_count": extra_txs,
                    "rho": rho,
                    "commit_sats": commit_sats,
                    "cycle_commit_sats": per_cycle_btc,
                    "apy_shift_pct": apy_shift * 100,
                }
            )
    return pd.DataFrame(records)


def build_replacement_roadmap(
    baseline_fees_stx: float,
    baseline_tx_count: float,
    coinbase_stx: float,
    target_increases: Iterable[float],
) -> pd.DataFrame:
    """
    Generate roadmap showing paths to replace coinbase with fee increases.

    For each target revenue increase, calculates two pure strategies:
    - Strategy A: Fee multiplier needed (keeping tx count constant)
    - Strategy B: Additional transactions needed (keeping fee/tx constant)

    Args:
        baseline_fees_stx: Current median/mean fee revenue per tenure
        baseline_tx_count: Current median/mean transaction count per tenure
        coinbase_stx: Current coinbase subsidy per tenure
        target_increases: Revenue increase targets (e.g., [100, 500, 1000])

    Returns:
        DataFrame with columns:
        - target_increase_stx: Target revenue increase
        - strategy: "fee_multiplier" or "tx_volume"
        - fee_multiplier: Multiplier applied to fees (strategy A)
        - new_fee_per_tx: Resulting fee/tx after multiplier
        - additional_txs: Extra transactions needed (strategy B)
        - new_tx_count: Resulting transaction count
        - new_total_revenue: Total miner revenue after change
        - pct_to_coinbase_replacement: % progress toward replacing coinbase
    """
    baseline_fee_per_tx = baseline_fees_stx / baseline_tx_count if baseline_tx_count else 0.0
    baseline_total_revenue = coinbase_stx + baseline_fees_stx

    records = []
    for target_increase in target_increases:
        new_total_revenue = baseline_total_revenue + target_increase
        new_fees_needed = baseline_fees_stx + target_increase
        pct_to_replacement = (target_increase / coinbase_stx) * 100

        # Strategy A: Fee multiplier only (constant tx count)
        fee_multiplier = new_fees_needed / baseline_fees_stx if baseline_fees_stx else 0.0
        new_fee_per_tx_a = baseline_fee_per_tx * fee_multiplier

        records.append(
            {
                "target_increase_stx": target_increase,
                "strategy": "fee_multiplier",
                "fee_multiplier": fee_multiplier,
                "new_fee_per_tx": new_fee_per_tx_a,
                "additional_txs": 0.0,
                "new_tx_count": baseline_tx_count,
                "new_total_revenue": new_total_revenue,
                "pct_to_coinbase_replacement": pct_to_replacement,
            }
        )

        # Strategy B: Transaction volume only (constant fee/tx)
        additional_txs = target_increase / baseline_fee_per_tx if baseline_fee_per_tx else 0.0
        new_tx_count = baseline_tx_count + additional_txs

        records.append(
            {
                "target_increase_stx": target_increase,
                "strategy": "tx_volume",
                "fee_multiplier": 1.0,
                "new_fee_per_tx": baseline_fee_per_tx,
                "additional_txs": additional_txs,
                "new_tx_count": new_tx_count,
                "new_total_revenue": new_total_revenue,
                "pct_to_coinbase_replacement": pct_to_replacement,
            }
        )

    return pd.DataFrame(records)


def build_yield_sensitivity_scenarios(
    baseline_participation_rate: float,
    baseline_apy_btc: float,
    baseline_total_stacked_ustx: float,
    baseline_total_btc_sats: int,
    participation_deltas: Iterable[float],
    btc_deltas: Iterable[float],
    *,
    circulating_supply_ustx: float = const.DEFAULT_CIRCULATING_SUPPLY_USTX,
    pox_cycle_days: int = const.POX_CYCLE_DAYS,
) -> pd.DataFrame:
    """Model how PoX APY changes with participation rate and BTC commitment variations.

    Generates sensitivity matrix showing APY impact from:
    - Changes in stacking participation (% of supply)
    - Changes in BTC commitments from miners

    Args:
        baseline_participation_rate: Current participation rate (%)
        baseline_apy_btc: Current BTC-denominated APY (%)
        baseline_total_stacked_ustx: Current total STX stacked (microSTX)
        baseline_total_btc_sats: Current total BTC rewards per cycle (satoshis)
        participation_deltas: Participation rate changes to model (e.g., [-10, -5, 0, +5, +10])
        btc_deltas: BTC commitment changes to model (e.g., [-25, -10, 0, +10, +25, +50])
        circulating_supply_ustx: Total STX circulating supply (microSTX)
        pox_cycle_days: PoX cycle duration in days (default 14)

    Returns:
        DataFrame with columns:
        - participation_delta: Change in participation rate (percentage points)
        - btc_delta: Change in BTC commitments (%)
        - new_participation_rate: Resulting participation rate (%)
        - new_total_stacked_ustx: Resulting total stacked (microSTX)
        - new_total_btc_sats: Resulting BTC rewards per cycle (satoshis)
        - new_apy_btc: Resulting BTC-denominated APY (%)
        - apy_delta: Change in APY (percentage points)
        - apy_pct_change: APY change as % of baseline

    Example:
        >>> build_yield_sensitivity_scenarios(
        ...     baseline_participation_rate=75.0,
        ...     baseline_apy_btc=12.5,
        ...     baseline_total_stacked_ustx=1_035_000_000_000_000,
        ...     baseline_total_btc_sats=15_000_000_000,
        ...     participation_deltas=[-10, 0, +10],
        ...     btc_deltas=[-25, 0, +25]
        ... )
    """
    # Input validation
    if not (const.MIN_PARTICIPATION_RATE_PCT <= baseline_participation_rate <= const.MAX_PARTICIPATION_RATE_PCT):
        raise ValueError(
            f"baseline_participation_rate must be in [0, 100], got {baseline_participation_rate}"
        )
    if baseline_apy_btc < 0:
        raise ValueError(f"baseline_apy_btc must be non-negative, got {baseline_apy_btc}")
    if baseline_total_stacked_ustx <= 0:
        raise ValueError(
            f"baseline_total_stacked_ustx must be positive, got {baseline_total_stacked_ustx}"
        )
    if baseline_total_btc_sats <= 0:
        raise ValueError(
            f"baseline_total_btc_sats must be positive, got {baseline_total_btc_sats}"
        )
    if pox_cycle_days <= 0:
        raise ValueError(f"pox_cycle_days must be positive, got {pox_cycle_days}")

    records = []

    for participation_delta in participation_deltas:
        new_participation_rate = baseline_participation_rate + participation_delta
        new_participation_rate = max(
            const.MIN_PARTICIPATION_RATE_PCT,
            min(const.MAX_PARTICIPATION_RATE_PCT, new_participation_rate)
        )

        # Calculate new stacked amount based on participation rate
        new_total_stacked_ustx = int(
            (new_participation_rate / 100.0) * circulating_supply_ustx
        )

        for btc_delta in btc_deltas:
            btc_multiplier = 1 + (btc_delta / 100.0)
            new_total_btc_sats = int(baseline_total_btc_sats * btc_multiplier)

            # Calculate new APY using centralized helper
            new_apy_btc = calculate_apy_btc(
                new_total_btc_sats, new_total_stacked_ustx, pox_cycle_days=pox_cycle_days
            )

            apy_delta = new_apy_btc - baseline_apy_btc
            apy_pct_change = (
                (apy_delta / baseline_apy_btc) * 100 if baseline_apy_btc > 0 else 0.0
            )

            records.append(
                {
                    "participation_delta": participation_delta,
                    "btc_delta": btc_delta,
                    "new_participation_rate": round(new_participation_rate, 2),
                    "new_total_stacked_ustx": new_total_stacked_ustx,
                    "new_total_btc_sats": new_total_btc_sats,
                    "new_apy_btc": round(new_apy_btc, 2),
                    "apy_delta": round(apy_delta, 2),
                    "apy_pct_change": round(apy_pct_change, 2),
                }
            )

    return pd.DataFrame(records)


def calculate_competitive_thresholds(
    target_apy_btc: float,
    current_total_stacked_ustx: float,
    current_total_btc_sats: int,
    *,
    pox_cycle_days: int = const.POX_CYCLE_DAYS,
) -> dict:
    """Calculate minimum participation/BTC thresholds to maintain competitive APY.

    Determines what changes are needed to reach a target APY level:
    - Minimum BTC commitments (holding participation constant)
    - Maximum participation (holding BTC commitments constant)

    Args:
        target_apy_btc: Target BTC-denominated APY (%)
        current_total_stacked_ustx: Current total STX stacked (microSTX)
        current_total_btc_sats: Current total BTC rewards per cycle (satoshis)
        pox_cycle_days: PoX cycle duration in days (default 14)

    Returns:
        Dictionary with:
        - target_apy_btc: Target APY
        - min_btc_sats_needed: Minimum BTC to reach target (constant participation)
        - btc_increase_pct: % increase in BTC needed
        - max_participation_rate_pct: Maximum participation to reach target (constant BTC)
        - participation_decrease_pct: % decrease in participation needed
        - feasibility: "achievable_btc", "achievable_participation", "both", or "challenging"

    Example:
        >>> calculate_competitive_thresholds(
        ...     target_apy_btc=15.0,
        ...     current_total_stacked_ustx=1_035_000_000_000_000,
        ...     current_total_btc_sats=12_000_000_000
        ... )
    """
    # Input validation
    if target_apy_btc <= 0:
        raise ValueError(f"target_apy_btc must be positive, got {target_apy_btc}")
    if current_total_stacked_ustx <= 0:
        raise ValueError(
            f"current_total_stacked_ustx must be positive, got {current_total_stacked_ustx}"
        )
    if current_total_btc_sats <= 0:
        raise ValueError(
            f"current_total_btc_sats must be positive, got {current_total_btc_sats}"
        )
    if pox_cycle_days <= 0:
        raise ValueError(f"pox_cycle_days must be positive, got {pox_cycle_days}")

    # Calculate minimum BTC needed (holding participation constant)
    # APY = (total_btc_sats / total_stx_stacked_ustx) * (365 / cycle_days) * 100 * 1_000_000
    # Solve for total_btc_sats:
    # total_btc_sats = (APY * total_stx_stacked_ustx) / ((365 / cycle_days) * 100 * 1_000_000)

    min_btc_sats_needed = int(
        (target_apy_btc * current_total_stacked_ustx)
        / ((const.DAYS_PER_YEAR / pox_cycle_days) * 100 * const.USTX_PER_STX)
    )

    btc_increase_pct = (
        ((min_btc_sats_needed - current_total_btc_sats) / current_total_btc_sats) * 100
        if current_total_btc_sats > 0
        else 0.0
    )

    # Calculate maximum participation (holding BTC constant)
    # Solve for total_stx_stacked_ustx:
    # total_stx_stacked_ustx = (total_btc_sats * (365 / cycle_days) * 100 * 1_000_000) / APY

    max_stacked_ustx = (
        (current_total_btc_sats * (const.DAYS_PER_YEAR / pox_cycle_days) * 100 * const.USTX_PER_STX)
        / target_apy_btc
        if target_apy_btc > 0
        else 0
    )

    # Convert to participation rate
    circulating_supply_ustx = const.DEFAULT_CIRCULATING_SUPPLY_USTX
    max_participation_rate_pct = (max_stacked_ustx / circulating_supply_ustx) * 100
    current_participation_rate_pct = (
        current_total_stacked_ustx / circulating_supply_ustx
    ) * 100

    participation_decrease_pct = (
        (
            (max_participation_rate_pct - current_participation_rate_pct)
            / current_participation_rate_pct
        )
        * 100
        if current_participation_rate_pct > 0
        else 0.0
    )

    # Assess feasibility using defined thresholds
    achievable_btc = btc_increase_pct < const.BTC_INCREASE_ACHIEVABLE_THRESHOLD_PCT
    achievable_participation = (
        max_participation_rate_pct > 0
        and participation_decrease_pct > const.PARTICIPATION_DECREASE_ACHIEVABLE_THRESHOLD_PCT
    )

    if achievable_btc and achievable_participation:
        feasibility = "both"
    elif achievable_btc:
        feasibility = "achievable_btc"
    elif achievable_participation:
        feasibility = "achievable_participation"
    else:
        feasibility = "challenging"

    return {
        "target_apy_btc": round(target_apy_btc, 2),
        "min_btc_sats_needed": min_btc_sats_needed,
        "btc_increase_pct": round(btc_increase_pct, 2),
        "max_participation_rate_pct": round(max_participation_rate_pct, 2),
        "participation_decrease_pct": round(participation_decrease_pct, 2),
        "feasibility": feasibility,
    }


def build_sustainability_scenarios(
    baseline_fees_stx: float,
    baseline_tx_count: float,
    baseline_apy_btc: float,
    baseline_total_stacked_ustx: float,
    fee_growth_rates: Iterable[float],
    tx_growth_rates: Iterable[float],
    years_forward: int = 5,
    *,
    coinbase_stx: float = const.DEFAULT_COINBASE_STX,
    mean_stx_btc: float = const.DEFAULT_STX_BTC_PRICE,
    pox_cycle_days: int = const.POX_CYCLE_DAYS,
    reward_cycles_blocks: int = const.POX_CYCLE_BLOCKS,
    rho: float = const.DEFAULT_COMMITMENT_RATIO,
) -> pd.DataFrame:
    """Model long-term PoX sustainability under fee and transaction growth scenarios.

    Projects how stacker yields evolve over multiple years under different growth assumptions:
    - Fee/tx growth (protocol improvements, market dynamics)
    - Transaction volume growth (adoption, usage)
    - Combined effects on miner revenues and BTC commitments

    Args:
        baseline_fees_stx: Current median/mean fee revenue per tenure
        baseline_tx_count: Current median/mean transaction count per tenure
        baseline_apy_btc: Current BTC-denominated APY (%)
        baseline_total_stacked_ustx: Current total STX stacked (microSTX)
        fee_growth_rates: Annual fee/tx growth rates to model (e.g., [0, 0.05, 0.10, 0.20])
        tx_growth_rates: Annual tx volume growth rates to model (e.g., [0, 0.10, 0.25, 0.50])
        years_forward: Number of years to project
        coinbase_stx: Coinbase subsidy per tenure (default 1000 STX)
        mean_stx_btc: Mean STX/BTC exchange rate
        pox_cycle_days: PoX cycle duration in days
        reward_cycles_blocks: Number of blocks per PoX cycle
        rho: BTC commitment ratio (fraction of reward value)

    Returns:
        DataFrame with columns:
        - fee_growth_rate: Annual fee/tx growth rate
        - tx_growth_rate: Annual transaction growth rate
        - year: Projection year (1 to years_forward)
        - projected_fee_per_tx: Fee per transaction
        - projected_tx_count: Transaction count per tenure
        - projected_fees_stx: Total fee revenue per tenure
        - projected_reward_stx: Total miner reward (coinbase + fees)
        - projected_btc_per_cycle: BTC committed per cycle
        - projected_apy_btc: Projected BTC-denominated APY (%)
        - apy_delta_from_baseline: Change from baseline APY (percentage points)

    Example:
        >>> build_sustainability_scenarios(
        ...     baseline_fees_stx=50.0,
        ...     baseline_tx_count=625.0,
        ...     baseline_apy_btc=12.0,
        ...     baseline_total_stacked_ustx=1_035_000_000_000_000,
        ...     fee_growth_rates=[0.0, 0.10, 0.20],
        ...     tx_growth_rates=[0.0, 0.25, 0.50],
        ...     years_forward=5
        ... )
    """
    # Input validation
    if baseline_fees_stx < 0:
        raise ValueError(f"baseline_fees_stx must be non-negative, got {baseline_fees_stx}")
    if baseline_tx_count < 0:
        raise ValueError(f"baseline_tx_count must be non-negative, got {baseline_tx_count}")
    if baseline_total_stacked_ustx <= 0:
        raise ValueError(
            f"baseline_total_stacked_ustx must be positive, got {baseline_total_stacked_ustx}"
        )
    if years_forward <= 0:
        raise ValueError(f"years_forward must be positive, got {years_forward}")
    if pox_cycle_days <= 0:
        raise ValueError(f"pox_cycle_days must be positive, got {pox_cycle_days}")
    if not (const.MIN_RHO <= rho <= const.MAX_RHO):
        raise ValueError(f"rho must be in [{const.MIN_RHO}, {const.MAX_RHO}], got {rho}")

    baseline_fee_per_tx = (
        baseline_fees_stx / baseline_tx_count if baseline_tx_count > 0 else 0.0
    )

    records = []

    for fee_growth_rate in fee_growth_rates:
        for tx_growth_rate in tx_growth_rates:
            for year in range(1, years_forward + 1):
                # Apply compound growth
                projected_fee_per_tx = baseline_fee_per_tx * (
                    (1 + fee_growth_rate) ** year
                )
                projected_tx_count = baseline_tx_count * ((1 + tx_growth_rate) ** year)

                # Calculate projected revenues
                projected_fees_stx = projected_fee_per_tx * projected_tx_count
                projected_reward_stx = coinbase_stx + projected_fees_stx

                # Calculate BTC commitments per cycle
                reward_value_sats = projected_reward_stx * mean_stx_btc * 1e8
                commit_sats_per_tenure = rho * reward_value_sats
                projected_btc_per_cycle = commit_sats_per_tenure * reward_cycles_blocks

                # Calculate projected APY using centralized helper
                # Convert BTC to satoshis and STX to microSTX for helper function
                projected_apy_btc = calculate_apy_btc(
                    int(projected_btc_per_cycle),
                    int(baseline_total_stacked_ustx),
                    pox_cycle_days=pox_cycle_days
                )

                apy_delta_from_baseline = projected_apy_btc - baseline_apy_btc

                records.append(
                    {
                        "fee_growth_rate": fee_growth_rate,
                        "tx_growth_rate": tx_growth_rate,
                        "year": year,
                        "projected_fee_per_tx": round(projected_fee_per_tx, 4),
                        "projected_tx_count": round(projected_tx_count, 2),
                        "projected_fees_stx": round(projected_fees_stx, 2),
                        "projected_reward_stx": round(projected_reward_stx, 2),
                        "projected_btc_per_cycle": round(projected_btc_per_cycle, 2),
                        "projected_apy_btc": round(projected_apy_btc, 2),
                        "apy_delta_from_baseline": round(apy_delta_from_baseline, 2),
                    }
                )

    return pd.DataFrame(records)
