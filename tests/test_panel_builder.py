from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from src import panel_builder


def _make_panel_inputs():
    fees = pd.DataFrame(
        {
            "burn_block_height": [100, 101],
            "fees_stx_sum": [12.5, 15.0],
            "tx_count": [30, 40],
        }
    )
    rewards = pd.DataFrame(
        {
            "burn_block_height": [100, 101],
            "reward_amount_sats_sum": [500_000, 600_000],
            "reward_recipients": [2, 2],
        }
    )
    anchors = pd.DataFrame(
        {
            "burn_block_height": [100, 101],
            "stacks_block_hash": ["0xabc", "0xdef"],
            "stacks_block_height": [2000, 2001],
            "miner_txid": ["0x01", "0x02"],
            "burn_block_time_iso": [
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 1, 2, tzinfo=UTC),
            ],
        }
    )
    prices = pd.DataFrame(
        {
            "ts": [
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 1, 2, tzinfo=UTC),
            ],
            "stx_usd": [1.0, 1.1],
            "btc_usd": [40_000.0, 42_000.0],
            "stx_btc": [1.0 / 40_000.0, 1.1 / 42_000.0],
        }
    )
    return fees, rewards, anchors, prices


def test_build_tenure_panel_computes_rho_and_flags():
    fees, rewards, anchors, prices = _make_panel_inputs()
    panel = panel_builder.build_tenure_panel(
        fees=fees,
        rewards=rewards,
        anchors=anchors,
        prices=prices,
    )

    assert set(panel.columns) >= {
        "burn_block_height",
        "reward_stx_total",
        "reward_value_sats",
        "rho",
        "coinbase_flag",
    }
    # Coinbase defaults to 1000, so reward total equals 1012.5 etc.
    assert (panel["reward_stx_total"] == 1_000 + panel["fees_stx_sum"]).all()
    # reward_value_sats should be positive given non-zero price inputs.
    assert (panel["reward_value_sats"] > 0).all()
    # Rho should be between 0 and 2 according to config clip.
    assert ((panel["rho"] >= 0) & (panel["rho"] <= 2)).all()
    # Coinbase flag should stay False with constant coinbase.
    assert not panel["coinbase_flag"].any()


def test_merge_cycle_metadata_assigns_ids():
    fees, rewards, anchors, prices = _make_panel_inputs()
    panel = panel_builder.build_tenure_panel(fees, rewards, anchors, prices)
    cycles = pd.DataFrame(
        {
            "id": [1],
            "start_burn_block_height": [99],
            "end_burn_block_height": [100],
        }
    )
    annotated = panel_builder.merge_cycle_metadata(panel, cycles)
    assert "cycle_id" in annotated
    assert annotated.loc[annotated["burn_block_height"] == 100, "cycle_id"].iloc[0] == 1
