"""Utilities for constructing the tenure-level analysis panel."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


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
    panel["reward_amount_sats_sum"] = panel["reward_amount_sats_sum"].fillna(0)
    panel["reward_recipients"] = panel["reward_recipients"].fillna(0).astype(int)
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

    panel["reward_value_sats"] = (
        panel["reward_stx_total"] * panel["stx_btc"] * 1e8
    ).fillna(0.0)
    panel["rho"] = panel["reward_amount_sats_sum"] / panel["reward_value_sats"].replace(
        {0: pd.NA}
    )
    panel["rho"] = panel["rho"].clip(cfg.rho_clip_min, cfg.rho_clip_max)
    panel["rho"] = panel["rho"].fillna(0.0)

    panel["rho_flag_div0"] = panel["reward_value_sats"] == 0
    panel["coinbase_flag"] = (
        panel["coinbase_estimate"] - cfg.coinbase_stx
    ).abs() > 1e-6
    return panel


def merge_cycle_metadata(panel: pd.DataFrame, cycles: pd.DataFrame) -> pd.DataFrame:
    """Annotate panel with PoX cycle identifiers."""
    if cycles.empty:
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
