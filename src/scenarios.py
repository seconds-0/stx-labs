"""Scenario analysis utilities for the PoX flywheel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import pandas as pd


@dataclass(frozen=True)
class ScenarioConfig:
    fee_per_tx_stx: float = 0.08
    rho_candidates: Sequence[float] = (0.3, 0.5, 0.7)
    coinbase_stx: float = 1_000.0
    reward_cycles_blocks: int = 2100
    stacked_supply_stx: float = 1_350_000_000.0  # placeholder, will be overwritten at runtime


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
