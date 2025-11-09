from __future__ import annotations

import pandas as pd
import pytest

from src import competitiveness
from src.competitiveness import RiskLevel, YieldProduct


def test_get_benchmark_yields_returns_dataframe():
    """Test that get_benchmark_yields returns properly structured DataFrame."""
    df = competitiveness.get_benchmark_yields()

    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0

    # Check expected columns
    expected_columns = {
        "product",
        "apy_min",
        "apy_max",
        "apy_mean",
        "apy_median",
        "apy_std",
        "technical_risk",
        "counterparty_risk",
        "regulatory_risk",
        "notes",
    }
    assert expected_columns.issubset(df.columns)

    # Check PoX is included
    assert "PoX Stacking" in df["product"].values


def test_calculate_yield_advantage():
    """Test yield advantage calculation."""
    # PoX at 12% vs wBTC Aave median at 1.5% = +10.5pp advantage
    advantage = competitiveness.calculate_yield_advantage(
        pox_apy=12.0, alternative_product=YieldProduct.WBTC_AAVE, use_median=True
    )

    assert advantage > 0  # PoX should have positive advantage
    assert 9.0 < advantage < 12.0  # Reasonable range


def test_calculate_yield_advantage_ratio():
    """Test yield ratio calculation."""
    ratio = competitiveness.calculate_yield_advantage_ratio(
        pox_apy=12.0, alternative_product=YieldProduct.WBTC_AAVE, use_median=True
    )

    assert ratio > 1.0  # PoX should yield more
    assert 5.0 < ratio < 15.0  # PoX ~8x wBTC based on benchmarks


def test_calculate_volatility_ratio():
    """Test volatility ratio calculation."""
    # PoX std ~4.5%, wBTC Aave std ~1.0%
    vol_ratio = competitiveness.calculate_volatility_ratio(
        pox_apy_std=4.5, alternative_product=YieldProduct.WBTC_AAVE
    )

    assert vol_ratio > 1.0  # PoX should be more volatile
    assert 3.0 < vol_ratio < 6.0  # PoX ~4.5x more volatile


def test_calculate_sharpe_ratio():
    """Test Sharpe ratio calculation."""
    # Mean 12%, std 4% -> Sharpe = 12/4 = 3.0
    sharpe = competitiveness.calculate_sharpe_ratio(mean_apy=12.0, std_apy=4.0)

    assert sharpe == 3.0

    # Edge case: zero volatility
    sharpe_zero_vol = competitiveness.calculate_sharpe_ratio(mean_apy=5.0, std_apy=0.0)
    assert sharpe_zero_vol == float("inf")


def test_calculate_risk_adjusted_advantage():
    """Test risk-adjusted yield advantage."""
    # PoX at 12% with 4.5% std vs wBTC Aave
    risk_adj_adv = competitiveness.calculate_risk_adjusted_advantage(
        pox_apy=12.0, pox_apy_std=4.5, alternative_product=YieldProduct.WBTC_AAVE
    )

    # PoX Sharpe should be higher despite volatility
    assert risk_adj_adv > 0


def test_calculate_risk_score():
    """Test composite risk score calculation."""
    # All low risk -> score near 1.0
    score_low = competitiveness.calculate_risk_score(
        technical_risk=RiskLevel.LOW,
        counterparty_risk=RiskLevel.LOW,
        regulatory_risk=RiskLevel.LOW,
    )
    assert score_low == 1.0

    # All very high risk -> score near 4.0
    score_high = competitiveness.calculate_risk_score(
        technical_risk=RiskLevel.VERY_HIGH,
        counterparty_risk=RiskLevel.VERY_HIGH,
        regulatory_risk=RiskLevel.VERY_HIGH,
    )
    assert score_high == 4.0

    # Mixed risk
    score_mixed = competitiveness.calculate_risk_score(
        technical_risk=RiskLevel.MEDIUM,
        counterparty_risk=RiskLevel.LOW,
        regulatory_risk=RiskLevel.MEDIUM,
    )
    assert 1.0 < score_mixed < 4.0


def test_get_product_risk_score():
    """Test getting risk score for specific products."""
    pox_risk = competitiveness.get_product_risk_score(YieldProduct.POX)
    assert 1.0 <= pox_risk <= 4.0

    wbtc_risk = competitiveness.get_product_risk_score(YieldProduct.WBTC_AAVE)
    assert 1.0 <= wbtc_risk <= 4.0

    # CeFi products that failed should have very high risk
    blockfi_risk = competitiveness.get_product_risk_score(YieldProduct.CEFI_BLOCKFI)
    assert blockfi_risk > 2.5  # Should reflect very high counterparty/regulatory risk


def test_compare_yields_across_products():
    """Test comparison across all alternative products."""
    df = competitiveness.compare_yields_across_products(pox_apy=12.0, pox_apy_std=4.5)

    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0  # Should have multiple alternatives

    # Check expected columns
    expected_columns = {
        "product",
        "alt_apy_median",
        "yield_advantage_pp",
        "yield_ratio",
        "pox_sharpe",
        "alt_sharpe",
        "sharpe_advantage",
        "risk_score",
    }
    assert expected_columns.issubset(df.columns)

    # All alternatives should show positive yield advantage for PoX at 12%
    assert (df["yield_advantage_pp"] > 0).all()

    # Results should be sorted by yield advantage descending
    assert df["yield_advantage_pp"].is_monotonic_decreasing


def test_calculate_equilibrium_yield():
    """Test equilibrium yield calculation."""
    # wBTC Aave median + 2% risk premium
    equilibrium = competitiveness.calculate_equilibrium_yield(
        alternative_product=YieldProduct.WBTC_AAVE, risk_premium=2.0
    )

    assert equilibrium > 0
    # Should be slightly above wBTC Aave median
    wbtc_median = competitiveness.BENCHMARK_YIELDS[YieldProduct.WBTC_AAVE].apy_median
    assert equilibrium == wbtc_median + 2.0


def test_get_competitive_positioning():
    """Test comprehensive competitive positioning summary."""
    positioning = competitiveness.get_competitive_positioning(
        pox_apy=12.0, pox_apy_std=4.5
    )

    assert isinstance(positioning, dict)

    # Check key fields present
    expected_keys = {
        "current_pox_apy",
        "pox_sharpe",
        "pox_risk_score",
        "best_alternative",
        "best_alternative_apy",
        "yield_advantage_vs_best",
        "yield_ratio_vs_best",
        "avg_yield_advantage",
        "competitive_rank",
        "total_products",
    }
    assert expected_keys.issubset(positioning.keys())

    # PoX at 12% should rank #1
    assert positioning["competitive_rank"] == 1

    # Should have positive advantage vs best alternative
    assert positioning["yield_advantage_vs_best"] > 0

    # Best alternative should be identified
    assert positioning["best_alternative"] is not None


def test_yield_advantage_with_unknown_product():
    """Test that unknown product raises ValueError."""
    with pytest.raises(ValueError, match="Unknown product"):
        # This will fail because we're passing a string instead of YieldProduct enum
        # We need to construct a scenario where the product is not in BENCHMARK_YIELDS
        class FakeProduct:
            pass

        # Monkeypatch to inject unknown product temporarily
        competitiveness.calculate_yield_advantage(
            pox_apy=12.0, alternative_product=None  # type: ignore
        )


def test_benchmark_yields_consistency():
    """Test that benchmark data is internally consistent."""
    for product, benchmark in competitiveness.BENCHMARK_YIELDS.items():
        # Min should be <= median <= max
        assert benchmark.apy_min <= benchmark.apy_median <= benchmark.apy_max

        # Mean should be between min and max
        assert benchmark.apy_min <= benchmark.apy_mean <= benchmark.apy_max

        # Std should be non-negative
        assert benchmark.apy_std >= 0

        # Risk levels should be valid enums
        assert isinstance(benchmark.technical_risk, RiskLevel)
        assert isinstance(benchmark.counterparty_risk, RiskLevel)
        assert isinstance(benchmark.regulatory_risk, RiskLevel)


def test_compare_yields_excludes_pox():
    """Test that compare_yields_across_products doesn't compare PoX to itself."""
    df = competitiveness.compare_yields_across_products(pox_apy=12.0, pox_apy_std=4.5)

    # PoX should not appear in the comparison results
    assert "PoX Stacking" not in df["product"].values


def test_sharpe_ratio_with_risk_free_rate():
    """Test Sharpe ratio calculation with non-zero risk-free rate."""
    # Mean 10%, std 5%, risk-free 2% -> Sharpe = (10-2)/5 = 1.6
    sharpe = competitiveness.calculate_sharpe_ratio(
        mean_apy=10.0, std_apy=5.0, risk_free_rate=2.0
    )

    assert sharpe == 1.6


def test_yield_advantage_with_mean():
    """Test yield advantage using mean instead of median."""
    advantage_median = competitiveness.calculate_yield_advantage(
        pox_apy=12.0, alternative_product=YieldProduct.WBTC_AAVE, use_median=True
    )

    advantage_mean = competitiveness.calculate_yield_advantage(
        pox_apy=12.0, alternative_product=YieldProduct.WBTC_AAVE, use_median=False
    )

    # Both should be positive, but may differ
    assert advantage_median > 0
    assert advantage_mean > 0


def test_competitive_positioning_at_different_apy_levels():
    """Test competitive positioning changes based on PoX APY."""
    # Low PoX APY
    positioning_low = competitiveness.get_competitive_positioning(
        pox_apy=3.0, pox_apy_std=2.0
    )

    # High PoX APY
    positioning_high = competitiveness.get_competitive_positioning(
        pox_apy=20.0, pox_apy_std=5.0
    )

    # High APY should have better competitive rank or equal rank #1
    assert positioning_high["competitive_rank"] <= positioning_low["competitive_rank"]

    # High APY should have higher average advantage
    assert (
        positioning_high["avg_yield_advantage"] > positioning_low["avg_yield_advantage"]
    )


def test_risk_score_weights():
    """Test that risk score respects custom weights."""
    # Weight technical risk heavily (100%)
    score_tech_weighted = competitiveness.calculate_risk_score(
        technical_risk=RiskLevel.VERY_HIGH,
        counterparty_risk=RiskLevel.LOW,
        regulatory_risk=RiskLevel.LOW,
        weights=(1.0, 0.0, 0.0),
    )

    # Should be ~4.0 (only technical risk matters)
    assert score_tech_weighted == 4.0

    # Weight counterparty risk heavily
    score_counter_weighted = competitiveness.calculate_risk_score(
        technical_risk=RiskLevel.LOW,
        counterparty_risk=RiskLevel.VERY_HIGH,
        regulatory_risk=RiskLevel.LOW,
        weights=(0.0, 1.0, 0.0),
    )

    assert score_counter_weighted == 4.0
