"""PoX yield competitiveness analysis module.

Compares Stacks PoX stacking yields against alternative Bitcoin yield products:
- wBTC lending (Aave, Compound)
- CeFi lending platforms
- L2 staking products
- Bitcoin DeFi alternatives

Provides:
- Yield comparison metrics
- Risk-adjusted return calculations
- Competitive advantage quantification
- Risk scoring frameworks

Ref: docs/yield_competitiveness_implementation_plan.md
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List

import pandas as pd


class YieldProduct(Enum):
    """Alternative Bitcoin yield products for comparison."""

    POX = "PoX Stacking"
    WBTC_AAVE = "wBTC Lending (Aave)"
    WBTC_COMPOUND = "wBTC Lending (Compound)"
    CEFI_BLOCKFI = "CeFi (BlockFi)"
    CEFI_NEXO = "CeFi (Nexo)"
    CEFI_CELSIUS = "CeFi (Celsius)"
    L2_STAKING = "L2 Staking"


class RiskLevel(Enum):
    """Risk categorization for yield products."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    VERY_HIGH = 4


@dataclass
class YieldBenchmark:
    """Benchmark data for alternative yield products.

    Attributes:
        product: Product identifier
        apy_min: Minimum observed APY (%)
        apy_max: Maximum observed APY (%)
        apy_mean: Mean APY (%)
        apy_median: Median APY (%)
        apy_std: Standard deviation of APY
        technical_risk: Technical risk level
        counterparty_risk: Counterparty risk level
        regulatory_risk: Regulatory risk level
        notes: Additional context
    """

    product: YieldProduct
    apy_min: float
    apy_max: float
    apy_mean: float
    apy_median: float
    apy_std: float
    technical_risk: RiskLevel
    counterparty_risk: RiskLevel
    regulatory_risk: RiskLevel
    notes: str = ""


# Benchmark yield data for alternative products
# Based on historical data research (2022-2024)
# Note: These are representative values and should be updated with actual historical data
BENCHMARK_YIELDS: Dict[YieldProduct, YieldBenchmark] = {
    YieldProduct.POX: YieldBenchmark(
        product=YieldProduct.POX,
        apy_min=5.0,
        apy_max=25.0,
        apy_mean=12.5,
        apy_median=11.0,
        apy_std=4.5,
        technical_risk=RiskLevel.MEDIUM,
        counterparty_risk=RiskLevel.LOW,
        regulatory_risk=RiskLevel.MEDIUM,
        notes="BTC-denominated yield from miner commitments; volatility driven by participation and miner economics",
    ),
    YieldProduct.WBTC_AAVE: YieldBenchmark(
        product=YieldProduct.WBTC_AAVE,
        apy_min=0.1,
        apy_max=4.0,
        apy_mean=1.8,
        apy_median=1.5,
        apy_std=1.0,
        technical_risk=RiskLevel.MEDIUM,
        counterparty_risk=RiskLevel.MEDIUM,
        regulatory_risk=RiskLevel.MEDIUM,
        notes="DeFi lending on Ethereum; yields vary with utilization",
    ),
    YieldProduct.WBTC_COMPOUND: YieldBenchmark(
        product=YieldProduct.WBTC_COMPOUND,
        apy_min=0.05,
        apy_max=3.5,
        apy_mean=1.5,
        apy_median=1.2,
        apy_std=0.9,
        technical_risk=RiskLevel.MEDIUM,
        counterparty_risk=RiskLevel.MEDIUM,
        regulatory_risk=RiskLevel.MEDIUM,
        notes="DeFi lending on Ethereum; historically lower than Aave",
    ),
    YieldProduct.CEFI_BLOCKFI: YieldBenchmark(
        product=YieldProduct.CEFI_BLOCKFI,
        apy_min=0.0,
        apy_max=8.5,
        apy_mean=4.5,
        apy_median=4.0,
        apy_std=2.5,
        technical_risk=RiskLevel.LOW,
        counterparty_risk=RiskLevel.VERY_HIGH,
        regulatory_risk=RiskLevel.VERY_HIGH,
        notes="Ceased operations 2022; historical reference only",
    ),
    YieldProduct.CEFI_NEXO: YieldBenchmark(
        product=YieldProduct.CEFI_NEXO,
        apy_min=1.0,
        apy_max=8.0,
        apy_mean=4.0,
        apy_median=3.5,
        apy_std=2.0,
        technical_risk=RiskLevel.LOW,
        counterparty_risk=RiskLevel.HIGH,
        regulatory_risk=RiskLevel.HIGH,
        notes="Centralized custody; rates vary by tier and market conditions",
    ),
    YieldProduct.CEFI_CELSIUS: YieldBenchmark(
        product=YieldProduct.CEFI_CELSIUS,
        apy_min=0.0,
        apy_max=8.8,
        apy_mean=5.0,
        apy_median=4.5,
        apy_std=2.8,
        technical_risk=RiskLevel.LOW,
        counterparty_risk=RiskLevel.VERY_HIGH,
        regulatory_risk=RiskLevel.VERY_HIGH,
        notes="Bankrupt 2022; historical reference only",
    ),
}


def get_benchmark_yields() -> pd.DataFrame:
    """Get benchmark yield data as DataFrame.

    Returns:
        DataFrame with columns: product, apy_min, apy_max, apy_mean, apy_median,
        apy_std, technical_risk, counterparty_risk, regulatory_risk, notes
    """
    records = []
    for benchmark in BENCHMARK_YIELDS.values():
        records.append(
            {
                "product": benchmark.product.value,
                "apy_min": benchmark.apy_min,
                "apy_max": benchmark.apy_max,
                "apy_mean": benchmark.apy_mean,
                "apy_median": benchmark.apy_median,
                "apy_std": benchmark.apy_std,
                "technical_risk": benchmark.technical_risk.name,
                "counterparty_risk": benchmark.counterparty_risk.name,
                "regulatory_risk": benchmark.regulatory_risk.name,
                "notes": benchmark.notes,
            }
        )
    return pd.DataFrame(records)


def calculate_yield_advantage(
    pox_apy: float,
    alternative_product: YieldProduct = YieldProduct.WBTC_AAVE,
    use_median: bool = True,
) -> float:
    """Calculate PoX yield advantage over alternative product.

    Args:
        pox_apy: Current PoX APY (%)
        alternative_product: Alternative product to compare against
        use_median: If True, compare to median; else use mean

    Returns:
        Yield advantage as percentage points (positive = PoX superior)

    Example:
        >>> calculate_yield_advantage(12.0, YieldProduct.WBTC_AAVE)
        10.5  # PoX at 12% vs wBTC Aave at 1.5% median = +10.5 pp advantage
    """
    benchmark = BENCHMARK_YIELDS.get(alternative_product)
    if benchmark is None:
        raise ValueError(f"Unknown product: {alternative_product}")

    alt_apy = benchmark.apy_median if use_median else benchmark.apy_mean
    return pox_apy - alt_apy


def calculate_yield_advantage_ratio(
    pox_apy: float,
    alternative_product: YieldProduct = YieldProduct.WBTC_AAVE,
    use_median: bool = True,
) -> float:
    """Calculate PoX yield advantage as ratio.

    Args:
        pox_apy: Current PoX APY (%)
        alternative_product: Alternative product to compare against
        use_median: If True, compare to median; else use mean

    Returns:
        Yield ratio (e.g., 2.0 means PoX yields 2x the alternative)

    Example:
        >>> calculate_yield_advantage_ratio(12.0, YieldProduct.WBTC_AAVE)
        8.0  # PoX at 12% vs wBTC Aave at 1.5% median = 8x
    """
    benchmark = BENCHMARK_YIELDS.get(alternative_product)
    if benchmark is None:
        raise ValueError(f"Unknown product: {alternative_product}")

    alt_apy = benchmark.apy_median if use_median else benchmark.apy_mean
    if alt_apy == 0:
        return float("inf") if pox_apy > 0 else 1.0

    return pox_apy / alt_apy


def calculate_volatility_ratio(
    pox_apy_std: float,
    alternative_product: YieldProduct = YieldProduct.WBTC_AAVE,
) -> float:
    """Calculate PoX yield volatility relative to alternative.

    Args:
        pox_apy_std: Standard deviation of PoX APY
        alternative_product: Alternative product to compare against

    Returns:
        Volatility ratio (>1 means PoX more volatile)

    Example:
        >>> calculate_volatility_ratio(4.5, YieldProduct.WBTC_AAVE)
        4.5  # PoX std 4.5% vs wBTC Aave std 1.0% = 4.5x more volatile
    """
    benchmark = BENCHMARK_YIELDS.get(alternative_product)
    if benchmark is None:
        raise ValueError(f"Unknown product: {alternative_product}")

    if benchmark.apy_std == 0:
        return float("inf") if pox_apy_std > 0 else 1.0

    return pox_apy_std / benchmark.apy_std


def calculate_sharpe_ratio(
    mean_apy: float,
    std_apy: float,
    risk_free_rate: float = 0.0,
) -> float:
    """Calculate Sharpe-like ratio for yield product.

    Args:
        mean_apy: Mean APY (%)
        std_apy: Standard deviation of APY (%)
        risk_free_rate: Risk-free rate (%, default 0)

    Returns:
        Sharpe ratio (higher is better risk-adjusted return)

    Note:
        Traditional Sharpe ratio uses excess return / volatility.
        Here we adapt it for yield products.
    """
    if std_apy == 0:
        return float("inf") if mean_apy > risk_free_rate else 0.0

    return (mean_apy - risk_free_rate) / std_apy


def calculate_risk_adjusted_advantage(
    pox_apy: float,
    pox_apy_std: float,
    alternative_product: YieldProduct = YieldProduct.WBTC_AAVE,
) -> float:
    """Calculate risk-adjusted yield advantage (PoX Sharpe - Alternative Sharpe).

    Args:
        pox_apy: Current PoX APY (%)
        pox_apy_std: PoX APY standard deviation (%)
        alternative_product: Alternative product to compare against

    Returns:
        Difference in Sharpe ratios (positive = PoX superior risk-adjusted)

    Example:
        >>> calculate_risk_adjusted_advantage(12.0, 4.5, YieldProduct.WBTC_AAVE)
        1.17  # PoX Sharpe (2.67) - wBTC Sharpe (1.50) = +1.17
    """
    benchmark = BENCHMARK_YIELDS.get(alternative_product)
    if benchmark is None:
        raise ValueError(f"Unknown product: {alternative_product}")

    pox_sharpe = calculate_sharpe_ratio(pox_apy, pox_apy_std)
    alt_sharpe = calculate_sharpe_ratio(benchmark.apy_mean, benchmark.apy_std)

    return pox_sharpe - alt_sharpe


def calculate_risk_score(
    technical_risk: RiskLevel,
    counterparty_risk: RiskLevel,
    regulatory_risk: RiskLevel,
    weights: tuple[float, float, float] = (0.4, 0.4, 0.2),
) -> float:
    """Calculate composite risk score for a yield product.

    Args:
        technical_risk: Technical risk level
        counterparty_risk: Counterparty risk level
        regulatory_risk: Regulatory risk level
        weights: Weights for (technical, counterparty, regulatory)

    Returns:
        Composite risk score (1.0-4.0, lower is better)

    Example:
        >>> calculate_risk_score(RiskLevel.MEDIUM, RiskLevel.LOW, RiskLevel.MEDIUM)
        1.8  # Weighted average of risk levels
    """
    w_tech, w_counter, w_reg = weights

    score = (
        technical_risk.value * w_tech
        + counterparty_risk.value * w_counter
        + regulatory_risk.value * w_reg
    )

    return round(score, 2)


def get_product_risk_score(product: YieldProduct) -> float:
    """Get composite risk score for a yield product.

    Args:
        product: Yield product to score

    Returns:
        Composite risk score (1.0-4.0, lower is better)
    """
    benchmark = BENCHMARK_YIELDS.get(product)
    if benchmark is None:
        raise ValueError(f"Unknown product: {product}")

    return calculate_risk_score(
        benchmark.technical_risk,
        benchmark.counterparty_risk,
        benchmark.regulatory_risk,
    )


def compare_yields_across_products(
    pox_apy: float,
    pox_apy_std: float = 4.5,
) -> pd.DataFrame:
    """Compare PoX yield against all alternative products.

    Args:
        pox_apy: Current PoX APY (%)
        pox_apy_std: PoX APY standard deviation (%)

    Returns:
        DataFrame with comparison metrics for each alternative product:
        - product: Product name
        - alt_apy_median: Alternative product median APY
        - yield_advantage_pp: Yield advantage in percentage points
        - yield_ratio: Yield ratio (PoX / alternative)
        - pox_sharpe: PoX Sharpe ratio
        - alt_sharpe: Alternative Sharpe ratio
        - sharpe_advantage: Difference in Sharpe ratios
        - risk_score: Composite risk score for alternative
    """
    results = []

    pox_sharpe = calculate_sharpe_ratio(pox_apy, pox_apy_std)

    for product, benchmark in BENCHMARK_YIELDS.items():
        if product == YieldProduct.POX:
            continue  # Skip self-comparison

        alt_sharpe = calculate_sharpe_ratio(benchmark.apy_mean, benchmark.apy_std)

        results.append(
            {
                "product": product.value,
                "alt_apy_median": benchmark.apy_median,
                "yield_advantage_pp": round(pox_apy - benchmark.apy_median, 2),
                "yield_ratio": round(
                    (
                        pox_apy / benchmark.apy_median
                        if benchmark.apy_median > 0
                        else float("inf")
                    ),
                    2,
                ),
                "pox_sharpe": round(pox_sharpe, 2),
                "alt_sharpe": round(alt_sharpe, 2),
                "sharpe_advantage": round(pox_sharpe - alt_sharpe, 2),
                "risk_score": get_product_risk_score(product),
            }
        )

    return pd.DataFrame(results).sort_values("yield_advantage_pp", ascending=False)


def calculate_equilibrium_yield(
    alternative_product: YieldProduct = YieldProduct.WBTC_AAVE,
    risk_premium: float = 2.0,
) -> float:
    """Calculate equilibrium PoX yield needed to attract capital.

    Equilibrium yield = Alternative yield + Risk premium

    Args:
        alternative_product: Alternative product to compete with
        risk_premium: Required risk premium over alternative (percentage points)

    Returns:
        Equilibrium PoX APY (%)

    Example:
        >>> calculate_equilibrium_yield(YieldProduct.WBTC_AAVE, risk_premium=2.0)
        3.5  # wBTC Aave median 1.5% + 2.0% risk premium
    """
    benchmark = BENCHMARK_YIELDS.get(alternative_product)
    if benchmark is None:
        raise ValueError(f"Unknown product: {alternative_product}")

    return benchmark.apy_median + risk_premium


def get_competitive_positioning(
    pox_apy: float,
    pox_apy_std: float = 4.5,
) -> Dict[str, any]:
    """Get comprehensive competitive positioning summary.

    Args:
        pox_apy: Current PoX APY (%)
        pox_apy_std: PoX APY standard deviation (%)

    Returns:
        Dictionary with competitive positioning metrics:
        - current_pox_apy: Current PoX APY
        - pox_sharpe: PoX Sharpe ratio
        - pox_risk_score: PoX composite risk score
        - best_alternative: Best alternative product (highest yield)
        - best_alternative_apy: Best alternative APY
        - yield_advantage_vs_best: Advantage over best alternative (pp)
        - yield_ratio_vs_best: Ratio vs best alternative
        - avg_yield_advantage: Average advantage across all alternatives (pp)
        - competitive_rank: Rank among all products (1 = best)
    """
    pox_sharpe = calculate_sharpe_ratio(pox_apy, pox_apy_std)
    pox_risk_score = get_product_risk_score(YieldProduct.POX)

    # Find best alternative (highest median APY)
    best_alt_product = None
    best_alt_apy = 0.0

    for product, benchmark in BENCHMARK_YIELDS.items():
        if product == YieldProduct.POX:
            continue
        if benchmark.apy_median > best_alt_apy:
            best_alt_apy = benchmark.apy_median
            best_alt_product = product

    # Calculate advantages
    yield_adv_vs_best = pox_apy - best_alt_apy if best_alt_product else 0.0
    yield_ratio_vs_best = pox_apy / best_alt_apy if best_alt_apy > 0 else float("inf")

    # Calculate average advantage
    total_advantage = 0.0
    count = 0

    for product, benchmark in BENCHMARK_YIELDS.items():
        if product == YieldProduct.POX:
            continue
        total_advantage += pox_apy - benchmark.apy_median
        count += 1

    avg_advantage = total_advantage / count if count > 0 else 0.0

    # Determine competitive rank
    all_apys = [pox_apy]
    for product, benchmark in BENCHMARK_YIELDS.items():
        if product != YieldProduct.POX:
            all_apys.append(benchmark.apy_median)

    all_apys_sorted = sorted(all_apys, reverse=True)
    competitive_rank = all_apys_sorted.index(pox_apy) + 1

    return {
        "current_pox_apy": round(pox_apy, 2),
        "pox_sharpe": round(pox_sharpe, 2),
        "pox_risk_score": pox_risk_score,
        "best_alternative": best_alt_product.value if best_alt_product else None,
        "best_alternative_apy": round(best_alt_apy, 2),
        "yield_advantage_vs_best": round(yield_adv_vs_best, 2),
        "yield_ratio_vs_best": round(yield_ratio_vs_best, 2),
        "avg_yield_advantage": round(avg_advantage, 2),
        "competitive_rank": competitive_rank,
        "total_products": len(all_apys),
    }
