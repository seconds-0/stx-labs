"""Tests for yield-focused scenario functions in src/scenarios.py."""

from __future__ import annotations

import pandas as pd
import pytest

from src import scenarios


def test_build_yield_sensitivity_scenarios_basic():
    """Test basic yield sensitivity matrix generation."""
    result = scenarios.build_yield_sensitivity_scenarios(
        baseline_participation_rate=75.0,
        baseline_apy_btc=12.0,
        baseline_total_stacked_ustx=1_035_000_000_000_000,
        baseline_total_btc_sats=15_000_000_000,
        participation_deltas=[-10, 0, +10],
        btc_deltas=[-25, 0, +25],
    )

    assert isinstance(result, pd.DataFrame)
    assert len(result) == 9  # 3 participation × 3 btc = 9 combinations

    # Check expected columns
    expected_columns = {
        "participation_delta",
        "btc_delta",
        "new_participation_rate",
        "new_total_stacked_ustx",
        "new_total_btc_sats",
        "new_apy_btc",
        "apy_delta",
        "apy_pct_change",
    }
    assert expected_columns.issubset(result.columns)


def test_build_yield_sensitivity_scenarios_baseline_row():
    """Test that baseline scenario (0,0) preserves input values."""
    result = scenarios.build_yield_sensitivity_scenarios(
        baseline_participation_rate=75.0,
        baseline_apy_btc=12.0,
        baseline_total_stacked_ustx=1_035_000_000_000_000,
        baseline_total_btc_sats=15_000_000_000,
        participation_deltas=[0],
        btc_deltas=[0],
    )

    # Baseline scenario should preserve input values
    assert len(result) == 1
    row = result.iloc[0]

    assert row["participation_delta"] == 0
    assert row["btc_delta"] == 0
    assert row["new_participation_rate"] == 75.0
    assert row["new_total_stacked_ustx"] == 1_035_000_000_000_000
    assert row["new_total_btc_sats"] == 15_000_000_000
    # APY is recalculated from inputs, so apy_delta shows difference from baseline_apy_btc parameter
    # (This tests that the calculation runs, not that baseline_apy_btc matches the inputs)


def test_build_yield_sensitivity_scenarios_participation_increase():
    """Test that increased participation decreases APY (more stackers, same BTC)."""
    result = scenarios.build_yield_sensitivity_scenarios(
        baseline_participation_rate=75.0,
        baseline_apy_btc=12.0,
        baseline_total_stacked_ustx=1_035_000_000_000_000,
        baseline_total_btc_sats=15_000_000_000,
        participation_deltas=[0, +10],
        btc_deltas=[0],
    )

    baseline = result[result["participation_delta"] == 0].iloc[0]
    increased = result[result["participation_delta"] == 10].iloc[0]

    # More participation = lower APY per stacker
    assert increased["new_apy_btc"] < baseline["new_apy_btc"]
    # Note: apy_delta is relative to baseline_apy_btc parameter, not to each other


def test_build_yield_sensitivity_scenarios_btc_increase():
    """Test that increased BTC commitments increase APY."""
    result = scenarios.build_yield_sensitivity_scenarios(
        baseline_participation_rate=75.0,
        baseline_apy_btc=12.0,
        baseline_total_stacked_ustx=1_035_000_000_000_000,
        baseline_total_btc_sats=15_000_000_000,
        participation_deltas=[0],
        btc_deltas=[0, +25],
    )

    baseline = result[result["btc_delta"] == 0].iloc[0]
    increased = result[result["btc_delta"] == 25].iloc[0]

    # More BTC = higher APY
    assert increased["new_apy_btc"] > baseline["new_apy_btc"]
    assert increased["new_total_btc_sats"] > baseline["new_total_btc_sats"]


def test_build_yield_sensitivity_scenarios_participation_bounds():
    """Test that participation rate is clamped between 0-100%."""
    result = scenarios.build_yield_sensitivity_scenarios(
        baseline_participation_rate=95.0,
        baseline_apy_btc=10.0,
        baseline_total_stacked_ustx=1_311_000_000_000_000,
        baseline_total_btc_sats=12_000_000_000,
        participation_deltas=[-100, -50, +10],
        btc_deltas=[0],
    )

    # Check all participation rates are within bounds
    assert (result["new_participation_rate"] >= 0).all()
    assert (result["new_participation_rate"] <= 100).all()


def test_build_yield_sensitivity_scenarios_zero_participation():
    """Test handling of zero participation (edge case)."""
    result = scenarios.build_yield_sensitivity_scenarios(
        baseline_participation_rate=10.0,
        baseline_apy_btc=8.0,
        baseline_total_stacked_ustx=138_000_000_000_000,
        baseline_total_btc_sats=5_000_000_000,
        participation_deltas=[-10],  # Will clamp to 0
        btc_deltas=[0],
    )

    assert len(result) == 1
    row = result.iloc[0]

    assert row["new_participation_rate"] == 0.0
    assert row["new_total_stacked_ustx"] == 0
    assert row["new_apy_btc"] == 0.0  # Zero stacked = zero APY


def test_calculate_competitive_thresholds_basic():
    """Test basic threshold calculation."""
    result = scenarios.calculate_competitive_thresholds(
        target_apy_btc=15.0,
        current_total_stacked_ustx=1_035_000_000_000_000,
        current_total_btc_sats=12_000_000_000,
    )

    assert isinstance(result, dict)

    # Check expected keys
    expected_keys = {
        "target_apy_btc",
        "min_btc_sats_needed",
        "btc_increase_pct",
        "max_participation_rate_pct",
        "participation_decrease_pct",
        "feasibility",
    }
    assert expected_keys == set(result.keys())

    # Target should be preserved
    assert result["target_apy_btc"] == 15.0

    # Feasibility should be a valid category
    assert result["feasibility"] in [
        "achievable_btc",
        "achievable_participation",
        "both",
        "challenging",
    ]


def test_calculate_competitive_thresholds_btc_increase():
    """Test that higher target APY requires more BTC."""
    low_target = scenarios.calculate_competitive_thresholds(
        target_apy_btc=10.0,
        current_total_stacked_ustx=1_035_000_000_000_000,
        current_total_btc_sats=12_000_000_000,
    )

    high_target = scenarios.calculate_competitive_thresholds(
        target_apy_btc=20.0,
        current_total_stacked_ustx=1_035_000_000_000_000,
        current_total_btc_sats=12_000_000_000,
    )

    # Higher target APY requires more BTC
    assert high_target["min_btc_sats_needed"] > low_target["min_btc_sats_needed"]
    assert high_target["btc_increase_pct"] > low_target["btc_increase_pct"]


def test_calculate_competitive_thresholds_participation_decrease():
    """Test that higher target APY allows lower participation."""
    low_target = scenarios.calculate_competitive_thresholds(
        target_apy_btc=10.0,
        current_total_stacked_ustx=1_035_000_000_000_000,
        current_total_btc_sats=12_000_000_000,
    )

    high_target = scenarios.calculate_competitive_thresholds(
        target_apy_btc=20.0,
        current_total_stacked_ustx=1_035_000_000_000_000,
        current_total_btc_sats=12_000_000_000,
    )

    # Higher target APY means less stackers can participate (to keep APY high)
    assert (
        high_target["max_participation_rate_pct"]
        < low_target["max_participation_rate_pct"]
    )


def test_calculate_competitive_thresholds_feasibility_achievable_btc():
    """Test feasibility = achievable_btc when BTC increase < 50%."""
    result = scenarios.calculate_competitive_thresholds(
        target_apy_btc=13.0,  # Modest increase from typical 12%
        current_total_stacked_ustx=1_035_000_000_000_000,
        current_total_btc_sats=12_000_000_000,
    )

    # Small APY increase should be achievable via moderate BTC increase
    assert result["btc_increase_pct"] < 50
    assert result["feasibility"] in ["achievable_btc", "both"]


def test_build_sustainability_scenarios_basic():
    """Test basic sustainability scenario generation."""
    result = scenarios.build_sustainability_scenarios(
        baseline_fees_stx=50.0,
        baseline_tx_count=625.0,
        baseline_apy_btc=12.0,
        baseline_total_stacked_ustx=1_035_000_000_000_000,
        fee_growth_rates=[0.0, 0.10],
        tx_growth_rates=[0.0, 0.25],
        years_forward=3,
    )

    assert isinstance(result, pd.DataFrame)
    assert len(result) == 12  # 2 fee rates × 2 tx rates × 3 years = 12 rows

    # Check expected columns
    expected_columns = {
        "fee_growth_rate",
        "tx_growth_rate",
        "year",
        "projected_fee_per_tx",
        "projected_tx_count",
        "projected_fees_stx",
        "projected_reward_stx",
        "projected_btc_per_cycle",
        "projected_apy_btc",
        "apy_delta_from_baseline",
    }
    assert expected_columns.issubset(result.columns)


def test_build_sustainability_scenarios_zero_growth():
    """Test that zero growth preserves baseline values."""
    result = scenarios.build_sustainability_scenarios(
        baseline_fees_stx=50.0,
        baseline_tx_count=625.0,
        baseline_apy_btc=12.0,
        baseline_total_stacked_ustx=1_035_000_000_000_000,
        fee_growth_rates=[0.0],
        tx_growth_rates=[0.0],
        years_forward=5,
    )

    # With zero growth, all years should have identical metrics
    assert len(result) == 5

    # Fee per tx should remain constant
    baseline_fee_per_tx = 50.0 / 625.0
    for _, row in result.iterrows():
        assert abs(row["projected_fee_per_tx"] - baseline_fee_per_tx) < 0.001
        assert abs(row["projected_tx_count"] - 625.0) < 0.1
        assert abs(row["projected_fees_stx"] - 50.0) < 0.1


def test_build_sustainability_scenarios_fee_growth():
    """Test that fee growth increases fees and revenue over time."""
    result = scenarios.build_sustainability_scenarios(
        baseline_fees_stx=50.0,
        baseline_tx_count=625.0,
        baseline_apy_btc=12.0,
        baseline_total_stacked_ustx=1_035_000_000_000_000,
        fee_growth_rates=[0.10],  # 10% annual fee growth
        tx_growth_rates=[0.0],  # Constant tx volume
        years_forward=5,
    )

    # Fee per tx should increase each year with 10% growth
    year1 = result[result["year"] == 1].iloc[0]
    year5 = result[result["year"] == 5].iloc[0]

    assert year5["projected_fee_per_tx"] > year1["projected_fee_per_tx"]
    assert year5["projected_fees_stx"] > year1["projected_fees_stx"]
    assert year5["projected_reward_stx"] > year1["projected_reward_stx"]


def test_build_sustainability_scenarios_tx_growth():
    """Test that transaction growth increases fees and revenue over time."""
    result = scenarios.build_sustainability_scenarios(
        baseline_fees_stx=50.0,
        baseline_tx_count=625.0,
        baseline_apy_btc=12.0,
        baseline_total_stacked_ustx=1_035_000_000_000_000,
        fee_growth_rates=[0.0],  # Constant fees/tx
        tx_growth_rates=[0.25],  # 25% annual tx growth
        years_forward=5,
    )

    # Transaction count should increase each year
    year1 = result[result["year"] == 1].iloc[0]
    year5 = result[result["year"] == 5].iloc[0]

    assert year5["projected_tx_count"] > year1["projected_tx_count"]
    assert year5["projected_fees_stx"] > year1["projected_fees_stx"]
    assert year5["projected_reward_stx"] > year1["projected_reward_stx"]


def test_build_sustainability_scenarios_compound_growth():
    """Test that combined fee + tx growth compounds correctly."""
    result = scenarios.build_sustainability_scenarios(
        baseline_fees_stx=50.0,
        baseline_tx_count=625.0,
        baseline_apy_btc=12.0,
        baseline_total_stacked_ustx=1_035_000_000_000_000,
        fee_growth_rates=[0.10],
        tx_growth_rates=[0.25],
        years_forward=5,
    )

    year1 = result[result["year"] == 1].iloc[0]
    year2 = result[result["year"] == 2].iloc[0]

    # Year 1: fees should be baseline * 1.10 * 1.25 = 1.375x
    # Year 2: fees should be baseline * (1.10^2) * (1.25^2) = 1.890625x

    baseline_fees = 50.0
    expected_year1_fees = baseline_fees * 1.10 * 1.25
    expected_year2_fees = baseline_fees * (1.10**2) * (1.25**2)

    assert abs(year1["projected_fees_stx"] - expected_year1_fees) < 1.0
    assert abs(year2["projected_fees_stx"] - expected_year2_fees) < 1.0


def test_build_sustainability_scenarios_all_years_present():
    """Test that all projection years are included."""
    result = scenarios.build_sustainability_scenarios(
        baseline_fees_stx=50.0,
        baseline_tx_count=625.0,
        baseline_apy_btc=12.0,
        baseline_total_stacked_ustx=1_035_000_000_000_000,
        fee_growth_rates=[0.05, 0.10],
        tx_growth_rates=[0.10],
        years_forward=10,
    )

    # Should have data for years 1-10 for each combination
    assert len(result) == 20  # 2 fee rates × 1 tx rate × 10 years

    years = sorted(result["year"].unique())
    assert years == list(range(1, 11))


def test_build_sustainability_scenarios_zero_transactions():
    """Test handling of zero baseline transactions (edge case)."""
    result = scenarios.build_sustainability_scenarios(
        baseline_fees_stx=0.0,
        baseline_tx_count=0.0,
        baseline_apy_btc=12.0,
        baseline_total_stacked_ustx=1_035_000_000_000_000,
        fee_growth_rates=[0.10],
        tx_growth_rates=[0.25],
        years_forward=3,
    )

    # With zero baseline, growth still results in zero
    assert len(result) == 3
    for _, row in result.iterrows():
        assert row["projected_fees_stx"] == 0.0
        assert row["projected_fee_per_tx"] == 0.0
        assert row["projected_tx_count"] == 0.0


def test_build_sustainability_scenarios_different_rho_values():
    """Test that different rho (commitment ratio) values affect projections."""
    low_rho = scenarios.build_sustainability_scenarios(
        baseline_fees_stx=50.0,
        baseline_tx_count=625.0,
        baseline_apy_btc=12.0,
        baseline_total_stacked_ustx=1_035_000_000_000_000,
        fee_growth_rates=[0.10],
        tx_growth_rates=[0.10],
        years_forward=3,
        rho=0.3,  # Lower commitment ratio
    )

    high_rho = scenarios.build_sustainability_scenarios(
        baseline_fees_stx=50.0,
        baseline_tx_count=625.0,
        baseline_apy_btc=12.0,
        baseline_total_stacked_ustx=1_035_000_000_000_000,
        fee_growth_rates=[0.10],
        tx_growth_rates=[0.10],
        years_forward=3,
        rho=0.7,  # Higher commitment ratio
    )

    # Higher rho should lead to higher BTC commitments
    for year in [1, 2, 3]:
        low_year = low_rho[low_rho["year"] == year].iloc[0]
        high_year = high_rho[high_rho["year"] == year].iloc[0]

        assert (
            high_year["projected_btc_per_cycle"] > low_year["projected_btc_per_cycle"]
        )
