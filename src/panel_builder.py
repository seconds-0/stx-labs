"""Utilities for constructing the tenure-level analysis panel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import warnings

import pandas as pd

from . import cycle_utils
from . import pox_yields


@dataclass
class PanelConfig:
    coinbase_stx: float = 1_000.0
    rho_clip_min: float = 0.0
    rho_clip_max: float = 2.0


def build_tenure_panel(
    fees: pd.DataFrame,
    rewards: pd.DataFrame,
    anchors: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    config: PanelConfig | None = None,
) -> pd.DataFrame:
    """Join component datasets and compute derived metrics."""
    cfg = config or PanelConfig()

    for frame, name in ((fees, "fees"), (rewards, "rewards"), (anchors, "anchors")):
        if "burn_block_height" not in frame:
            raise ValueError(f"{name} dataframe missing burn_block_height")

    panel = (
        anchors.merge(fees, on="burn_block_height", how="left")
        .merge(rewards, on="burn_block_height", how="left")
        .sort_values("burn_block_height")
        .reset_index(drop=True)
    )

    panel["fees_stx_sum"] = panel["fees_stx_sum"].fillna(0.0)
    panel["reward_recipients"] = panel["reward_recipients"].fillna(0).astype(int)
    panel["reward_amount_sats_sum"] = panel["reward_amount_sats_sum"].astype("Float64")
    panel["burn_block_time_iso"] = pd.to_datetime(panel["burn_block_time_iso"])

    panel["coinbase_stx"] = cfg.coinbase_stx
    panel["reward_stx_total"] = panel["coinbase_stx"] + panel["fees_stx_sum"]
    panel["coinbase_estimate"] = panel["reward_stx_total"] - panel["fees_stx_sum"]

    price_series = prices.copy()
    price_series["ts"] = pd.to_datetime(price_series["ts"])
    price_series = price_series.sort_values("ts")

    panel = pd.merge_asof(
        panel.sort_values("burn_block_time_iso"),
        price_series.sort_values("ts"),
        left_on="burn_block_time_iso",
        right_on="ts",
        direction="nearest",
    )
    panel = panel.rename(columns={"ts": "price_ts"})

    panel["reward_value_sats"] = (panel["reward_stx_total"] * panel["stx_btc"] * 1e8).fillna(0.0)
    denominator = panel["reward_value_sats"].replace({0: pd.NA})
    panel["rho"] = panel["reward_amount_sats_sum"] / denominator
    panel["rho"] = panel["rho"].clip(cfg.rho_clip_min, cfg.rho_clip_max)

    panel["rho_flag_div0"] = panel["reward_value_sats"] == 0
    panel["rho_flag_missing"] = panel["reward_amount_sats_sum"].isna()
    panel.loc[panel["rho_flag_missing"], "rho"] = pd.NA
    panel["rho"] = panel["rho"].astype("Float64")
    panel["coinbase_flag"] = (panel["coinbase_estimate"] - cfg.coinbase_stx).abs() > 1e-6
    return panel


def merge_cycle_metadata(panel: pd.DataFrame, cycles: pd.DataFrame) -> pd.DataFrame:
    """Annotate panel with PoX cycle identifiers."""
    if cycles.empty:
        panel["cycle_id"] = pd.NA
        return panel
    required_columns = {"start_burn_block_height", "end_burn_block_height"}
    if not required_columns.issubset(cycles.columns):
        warnings.warn(
            "Cycle metadata missing start/end burn heights; skipping cycle annotation.",
            RuntimeWarning,
        )
        panel = panel.copy()
        panel["cycle_id"] = pd.NA
        return panel
    cycles = cycles.rename(
        columns={
            "id": "cycle_id",
            "start_burn_block_height": "cycle_start_burn",
            "end_burn_block_height": "cycle_end_burn",
        }
    )
    panel = panel.copy()
    panel["cycle_id"] = pd.NA
    for _, row in cycles.iterrows():
        mask = (panel["burn_block_height"] >= row["cycle_start_burn"]) & (
            panel["burn_block_height"] <= row["cycle_end_burn"]
        )
        panel.loc[mask, "cycle_id"] = row["cycle_id"]
    return panel


def annotate_panel_with_yields(
    panel: pd.DataFrame,
    *,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Annotate tenure panel with PoX yield metrics.

    Adds columns:
    - cycle_number: PoX cycle number (mapped from burn_block_height)
    - apy_btc: BTC-denominated annual percentage yield
    - apy_usd: USD-denominated APY (if price data available)
    - participation_rate_pct: Stacking participation as % of supply
    - total_stacked_ustx: Total STX stacked in the cycle (microSTX)
    - total_btc_sats: Total BTC rewards in the cycle (satoshis)

    Args:
        panel: Tenure panel DataFrame (must have burn_block_height column)
        force_refresh: If True, bypass cache and fetch fresh data

    Returns:
        Panel with yield metrics added via left join on cycle_number
    """
    if "burn_block_height" not in panel.columns:
        raise ValueError("Panel must have burn_block_height column")

    # Fetch PoX cycle data
    cycles_df = pox_yields.fetch_pox_cycles_data(force_refresh=force_refresh)

    if cycles_df.empty:
        # No cycle data available, add empty columns
        panel = panel.copy()
        panel["cycle_number"] = pd.NA
        panel["apy_btc"] = pd.NA
        panel["apy_usd"] = pd.NA
        panel["participation_rate_pct"] = pd.NA
        panel["total_stacked_ustx"] = pd.NA
        panel["total_btc_sats"] = pd.NA
        return panel

    # Fetch rewards aggregated by cycle
    rewards_df = pox_yields.aggregate_rewards_by_cycle(force_refresh=force_refresh)

    # Calculate APY metrics
    # Note: We pass None for prices_df here since we'll use the panel's existing prices
    apy_df = pox_yields.calculate_cycle_apy(cycles_df, rewards_df, prices_df=None)

    # Map burn_block_heights to PoX cycles
    panel = cycle_utils.map_burn_heights_to_cycles(
        panel, cycles_df, "burn_block_height"
    )

    # Merge yield metrics onto panel
    panel = panel.merge(
        apy_df[[
            "cycle_number",
            "apy_btc",
            "apy_usd",
            "participation_rate_pct",
            "total_stacked_ustx",
            "total_btc_sats"
        ]],
        on="cycle_number",
        how="left"
    )

    return panel
