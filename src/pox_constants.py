"""PoX Protocol and Economic Constants.

This module centralizes all magic numbers and constants used across the PoX
analysis codebase. Each constant includes documentation of its source and rationale.
"""

from __future__ import annotations

# =============================================================================
# PoX Protocol Constants
# =============================================================================

# PoX cycle duration in days
# Source: Stacks protocol specification (~2100 Bitcoin blocks ÷ ~144 blocks/day)
POX_CYCLE_DAYS = 14

# Bitcoin blocks per PoX cycle
# Source: Stacks protocol specification
POX_CYCLE_BLOCKS = 2100

# Calendar days per year (for APY annualization)
DAYS_PER_YEAR = 365


# =============================================================================
# Economic Assumptions
# =============================================================================

# Default STX circulating supply in microSTX
# Source: Approximate circulating supply as of 2024
# Note: This is a conservative estimate; actual supply varies with emissions
DEFAULT_CIRCULATING_SUPPLY_USTX = 1_380_000_000 * 1_000_000  # 1.38B STX

# Default STX/BTC exchange rate
# Source: Historical median price (~0.00003 BTC per STX)
# Note: Used as fallback when price data unavailable
DEFAULT_STX_BTC_PRICE = 0.00003

# Default BTC commitment ratio (rho)
# Source: Historical median observed ratio of (BTC committed / reward value)
# Range: 0.0 (no commitment) to 2.0 (miners overbid)
DEFAULT_COMMITMENT_RATIO = 0.5

# Default coinbase reward per tenure in STX
# Source: Stacks protocol specification
DEFAULT_COINBASE_STX = 1_000.0

# Default average fee per transaction in STX
# Source: Historical observation of typical transaction fees
DEFAULT_FEE_PER_TX_STX = 0.08


# =============================================================================
# Feasibility Thresholds (for competitive threshold analysis)
# =============================================================================

# BTC increase percentage considered "achievable"
# Rationale: Based on historical miner capacity and market liquidity
# - Below 50%: Can likely be achieved via organic fee growth and miner competition
# - Above 50%: Requires significant ecosystem growth or external catalysts
BTC_INCREASE_ACHIEVABLE_THRESHOLD_PCT = 50.0

# Participation decrease percentage considered "achievable"
# Rationale: Based on stacker behavior and liquidity preferences
# - Within -25%: Can occur naturally due to market conditions or yield opportunities
# - Beyond -25%: Requires major protocol changes or market disruptions
PARTICIPATION_DECREASE_ACHIEVABLE_THRESHOLD_PCT = -25.0


# =============================================================================
# Risk Scoring (for competitive positioning)
# =============================================================================

# Sharpe ratio thresholds for risk classification
# Source: Traditional finance risk-adjusted return metrics
SHARPE_RATIO_LOW_RISK_THRESHOLD = 1.0  # Sharpe >= 1.0 considered favorable
SHARPE_RATIO_MEDIUM_RISK_THRESHOLD = 0.5  # Sharpe 0.5-1.0 considered moderate
# Below 0.5 considered high risk


# =============================================================================
# Unit Conversions
# =============================================================================

# microSTX per STX (1 STX = 1,000,000 microSTX)
USTX_PER_STX = 1_000_000

# Satoshis per BTC (1 BTC = 100,000,000 satoshis)
SATS_PER_BTC = 100_000_000


# =============================================================================
# Data Validation Bounds
# =============================================================================

# Participation rate bounds (percentage)
MIN_PARTICIPATION_RATE_PCT = 0.0
MAX_PARTICIPATION_RATE_PCT = 100.0

# Commitment ratio (rho) bounds
# Rationale: rho > 2.0 indicates severe overbidding (rare); negative rho is invalid
MIN_RHO = 0.0
MAX_RHO = 2.0
