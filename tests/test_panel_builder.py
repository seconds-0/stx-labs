from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
import pytest

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
                datetime(2024, 1, 1, tzinfo=timezone.utc),
                datetime(2024, 1, 2, tzinfo=timezone.utc),
            ],
        }
    )
    prices = pd.DataFrame(
        {
            "ts": [
                datetime(2024, 1, 1, tzinfo=timezone.utc),
                datetime(2024, 1, 2, tzinfo=timezone.utc),
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


def test_annotate_panel_with_yields_adds_yield_columns():
    """Test that annotate_panel_with_yields adds all expected yield columns."""
    # Create a minimal panel
    panel = pd.DataFrame(
        {
            "burn_block_height": [100, 101, 102],
            "fees_stx_sum": [10.0, 15.0, 20.0],
        }
    )

    # Mock the pox_yields functions
    mock_cycles = pd.DataFrame(
        {
            "cycle_number": [1],
            "block_height": [100],
            "total_stacked_amount": [400_000_000_000_000],  # 400M STX in microSTX
        }
    )

    mock_rewards = pd.DataFrame(
        {
            "cycle_number": [1],
            "total_btc_sats": [50_000_000],  # 0.5 BTC
            "total_blocks": [100],
        }
    )

    mock_apy = pd.DataFrame(
        {
            "cycle_number": [1],
            "apy_btc": [12.50],
            "apy_usd": [15.00],
            "participation_rate_pct": [30.0],
            "total_stacked_ustx": [400_000_000_000_000],
            "total_btc_sats": [50_000_000],
        }
    )

    with (
        patch("src.pox_yields.fetch_pox_cycles_data", return_value=mock_cycles),
        patch("src.pox_yields.aggregate_rewards_by_cycle", return_value=mock_rewards),
        patch("src.pox_yields.calculate_cycle_apy", return_value=mock_apy),
    ):

        result = panel_builder.annotate_panel_with_yields(panel, force_refresh=False)

    # Check that all expected columns are present
    expected_columns = {
        "cycle_number",
        "apy_btc",
        "apy_usd",
        "participation_rate_pct",
        "total_stacked_ustx",
        "total_btc_sats",
    }
    assert expected_columns.issubset(result.columns)

    # Original columns should be preserved
    assert "burn_block_height" in result.columns
    assert "fees_stx_sum" in result.columns


def test_annotate_panel_with_yields_maps_burn_heights_to_cycles():
    """Test that burn_block_heights are correctly mapped to cycle_numbers."""
    panel = pd.DataFrame(
        {
            "burn_block_height": [100, 150, 200, 250],
            "fees_stx_sum": [10.0, 15.0, 20.0, 25.0],
        }
    )

    # Two cycles: cycle 1 starts at 100, cycle 2 starts at 200
    mock_cycles = pd.DataFrame(
        {
            "cycle_number": [1, 2],
            "block_height": [100, 200],
            "total_stacked_amount": [400_000_000_000_000, 450_000_000_000_000],
        }
    )

    mock_rewards = pd.DataFrame(
        {
            "cycle_number": [1, 2],
            "total_btc_sats": [50_000_000, 60_000_000],
            "total_blocks": [100, 100],
        }
    )

    mock_apy = pd.DataFrame(
        {
            "cycle_number": [1, 2],
            "apy_btc": [12.50, 13.33],
            "apy_usd": [15.00, 16.00],
            "participation_rate_pct": [30.0, 32.0],
            "total_stacked_ustx": [400_000_000_000_000, 450_000_000_000_000],
            "total_btc_sats": [50_000_000, 60_000_000],
        }
    )

    with (
        patch("src.pox_yields.fetch_pox_cycles_data", return_value=mock_cycles),
        patch("src.pox_yields.aggregate_rewards_by_cycle", return_value=mock_rewards),
        patch("src.pox_yields.calculate_cycle_apy", return_value=mock_apy),
    ):

        result = panel_builder.annotate_panel_with_yields(panel, force_refresh=False)

    # Heights 100 and 150 should be in cycle 1
    assert result.loc[result["burn_block_height"] == 100, "cycle_number"].iloc[0] == 1
    assert result.loc[result["burn_block_height"] == 150, "cycle_number"].iloc[0] == 1

    # Heights 200 and 250 should be in cycle 2
    assert result.loc[result["burn_block_height"] == 200, "cycle_number"].iloc[0] == 2
    assert result.loc[result["burn_block_height"] == 250, "cycle_number"].iloc[0] == 2


def test_annotate_panel_with_yields_handles_empty_cycles():
    """Test graceful handling when no cycle data is available."""
    panel = pd.DataFrame(
        {
            "burn_block_height": [100, 101, 102],
            "fees_stx_sum": [10.0, 15.0, 20.0],
        }
    )

    # Empty cycles DataFrame
    mock_empty_cycles = pd.DataFrame()

    with patch("src.pox_yields.fetch_pox_cycles_data", return_value=mock_empty_cycles):
        result = panel_builder.annotate_panel_with_yields(panel, force_refresh=False)

    # Should add columns with NA values
    assert "cycle_number" in result.columns
    assert "apy_btc" in result.columns
    assert "apy_usd" in result.columns

    # All values should be NA
    assert result["cycle_number"].isna().all()
    assert result["apy_btc"].isna().all()


def test_annotate_panel_with_yields_passes_force_refresh():
    """Test that force_refresh parameter is passed to underlying functions."""
    panel = pd.DataFrame(
        {
            "burn_block_height": [100],
            "fees_stx_sum": [10.0],
        }
    )

    mock_cycles = pd.DataFrame(
        {
            "cycle_number": [1],
            "block_height": [100],
            "total_stacked_amount": [400_000_000_000_000],
        }
    )

    mock_rewards = pd.DataFrame(
        {
            "cycle_number": [1],
            "total_btc_sats": [50_000_000],
            "total_blocks": [100],
        }
    )

    mock_apy = pd.DataFrame(
        {
            "cycle_number": [1],
            "apy_btc": [12.50],
            "apy_usd": [15.00],
            "participation_rate_pct": [30.0],
            "total_stacked_ustx": [400_000_000_000_000],
            "total_btc_sats": [50_000_000],
        }
    )

    with (
        patch(
            "src.pox_yields.fetch_pox_cycles_data", return_value=mock_cycles
        ) as mock_fetch_cycles,
        patch(
            "src.pox_yields.aggregate_rewards_by_cycle", return_value=mock_rewards
        ) as mock_agg_rewards,
        patch("src.pox_yields.calculate_cycle_apy", return_value=mock_apy),
    ):

        panel_builder.annotate_panel_with_yields(panel, force_refresh=True)

    # Verify force_refresh=True was passed through
    mock_fetch_cycles.assert_called_once_with(force_refresh=True)
    mock_agg_rewards.assert_called_once_with(force_refresh=True)


def test_annotate_panel_with_yields_requires_burn_block_height():
    """Test that function raises ValueError if burn_block_height column is missing."""
    panel = pd.DataFrame(
        {
            "fees_stx_sum": [10.0, 15.0],
        }
    )

    with pytest.raises(ValueError, match="burn_block_height"):
        panel_builder.annotate_panel_with_yields(panel)


def test_annotate_panel_with_yields_preserves_original_data():
    """Test that original panel data is not modified."""
    original_panel = pd.DataFrame(
        {
            "burn_block_height": [100, 101],
            "fees_stx_sum": [10.0, 15.0],
            "custom_column": ["a", "b"],
        }
    )

    mock_cycles = pd.DataFrame(
        {
            "cycle_number": [1],
            "block_height": [100],
            "total_stacked_amount": [400_000_000_000_000],
        }
    )

    mock_rewards = pd.DataFrame(
        {
            "cycle_number": [1],
            "total_btc_sats": [50_000_000],
            "total_blocks": [100],
        }
    )

    mock_apy = pd.DataFrame(
        {
            "cycle_number": [1],
            "apy_btc": [12.50],
            "apy_usd": [15.00],
            "participation_rate_pct": [30.0],
            "total_stacked_ustx": [400_000_000_000_000],
            "total_btc_sats": [50_000_000],
        }
    )

    with (
        patch("src.pox_yields.fetch_pox_cycles_data", return_value=mock_cycles),
        patch("src.pox_yields.aggregate_rewards_by_cycle", return_value=mock_rewards),
        patch("src.pox_yields.calculate_cycle_apy", return_value=mock_apy),
    ):

        result = panel_builder.annotate_panel_with_yields(
            original_panel, force_refresh=False
        )

    # Original columns and data should be preserved
    assert "custom_column" in result.columns
    assert result["custom_column"].tolist() == ["a", "b"]
    assert result["fees_stx_sum"].tolist() == [10.0, 15.0]
    assert len(result) == len(original_panel)
