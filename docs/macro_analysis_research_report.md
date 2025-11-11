# STX/BTC Macroeconomic Analysis: Research Report & Implementation Plan

**Author**: Claude (Kuwait Workspace)
**Date**: 2025-11-03
**Branch**: `stx-btc-macro-analysis`
**Objective**: Analyze STX/BTC price ratio against macroeconomic indicators to identify market levers and correlation patterns

---

## Executive Summary

This report presents a comprehensive research effort to identify, evaluate, and plan the integration of macroeconomic data sources for analyzing the Stacks-to-Bitcoin (STX/BTC) price ratio over the last two years. The goal is to understand which market conditions, economic indicators, and cryptocurrency-specific events influence this ratio.

### Key Findings

1. **Zero barriers to implementation**: All required data sources are freely available with no API keys required for primary sources
2. **Minimal dependencies**: Only 2 new Python packages needed (`yfinance` and `pandas-datareader`)
3. **Perfect architectural fit**: Existing caching, retry, and error handling patterns apply seamlessly
4. **Tether hypothesis is testable**: Historical USDT/USDC supply data available via CoinGecko
5. **Estimated implementation time**: 5-8 hours for complete integration with testing and visualization

---

## Table of Contents

1. [Research Context](#research-context)
2. [Codebase Architecture Review](#codebase-architecture-review)
3. [Data Sources Catalog](#data-sources-catalog)
4. [Technical Implementation Plan](#technical-implementation-plan)
5. [Testing Strategy](#testing-strategy)
6. [Visualization & Analysis Approach](#visualization--analysis-approach)
7. [Risk Assessment & Mitigation](#risk-assessment--mitigation)
8. [Timeline & Milestones](#timeline--milestones)
9. [Appendices](#appendices)

---

## 1. Research Context

### 1.1 Research Objectives

The primary goal is to understand what macroeconomic levers and market events alter the STX/BTC price ratio. Specific areas of investigation:

- **Traditional finance indicators**: S&P 500 levels and momentum, unemployment rates, interest rates
- **Stablecoin hypothesis**: Tether (USDT) and USDC minting activity as potential BTC price drivers
- **Market sentiment**: VIX volatility index, Bitcoin dominance, crypto market cap
- **Currency dynamics**: US Dollar Index (DXY), gold prices
- **On-chain metrics**: Bitcoin network activity, exchange flows

### 1.2 Time Horizon

**Analysis period**: Last 2 years (November 2023 - November 2025)

This period captures:
- Post-FTX collapse recovery (late 2023)
- Bitcoin halving cycle (April 2024)
- Multiple Federal Reserve rate decisions
- 2024 US election and policy uncertainty
- Stacks Nakamoto upgrade deployment

### 1.3 Hypothesis to Test

**Primary hypothesis**: Tether and USDC minting events directly drive Bitcoin price, which in turn affects the STX/BTC ratio.

**Supporting questions**:
- Do USDT supply increases precede BTC price rallies?
- What lag exists between stablecoin mints and price movements?
- Does the STX/BTC ratio behave differently during high vs. low stablecoin minting periods?
- Are there regime changes when traditional finance indicators (S&P 500, unemployment) dominate vs. crypto-native factors?

---

## 2. Codebase Architecture Review

### 2.1 Existing Data Pipeline

The current codebase (`/Users/alexanderhuth/Code/stx-labs/.conductor/kuwait/`) implements a robust data fetching and caching system:

**Key modules**:
- `src/config.py`: Centralized configuration (paths, API endpoints, retry policies)
- `src/http_utils.py`: HTTP layer with retry, exponential backoff, deterministic file-based caching
- `src/prices.py`: Multi-provider price fetching (CoinGecko primary, Signal21 fallback)
- `src/signal21.py`: Stacks transaction fees via Signal21 SQL API (adaptive chunking)
- `src/hiro.py`: Miner rewards and PoX cycle metadata via Hiro API
- `src/panel_builder.py`: Joins all data sources on burn block height and timestamp
- `src/scenarios.py`: Sensitivity analysis for fee uplifts and stacker yields

**Current data flow**:
```
1. Fetch prices (CoinGecko → Signal21 fallback) → cache/prices/*.parquet
2. Fetch fees (Signal21 SQL, adaptive chunking) → cache/signal21/*.parquet
3. Fetch rewards (Hiro API, paginated) → cache/hiro/*.parquet
4. Join on burn_block_height via panel_builder.py
5. Merge prices via merge_asof() on timestamp
6. Compute derived metrics (rho, flags)
7. Generate scenario tables and visualizations
```

### 2.2 Caching Strategy

**Cache structure**:
```
data/
├── raw/              # Raw JSON API responses (TTL: 1 hour default)
│   └── *.json        # Deterministic SHA256 keys based on (method, URL, params)
├── cache/
│   ├── prices/       # Cleaned price series (Parquet)
│   ├── signal21/     # Fees data (Parquet)
│   └── hiro/         # Rewards and metadata (Parquet)
```

**Key characteristics**:
- **Deterministic**: Identical requests always hit same cache file
- **TTL-aware**: Configurable expiration (1 hour for API responses, 6 hours for CoinGecko)
- **Graceful degradation**: Falls back to cached data on API failures
- **Format**: JSON for raw responses, Parquet for cleaned data

### 2.3 Error Handling Patterns

**Retry logic** (`http_utils.py`):
```python
RetryConfig(
    wait_min_seconds=0.5,
    wait_max_seconds=8.0,
    max_attempts=5,
    status_forcelist=(429, 500, 502, 503, 504, 522)
)
```

**Adaptive chunking** (`signal21.py`):
- Requests start with 30-day windows
- On API limits or 500 errors, halve window size (30→15→5 days)
- Retry with smaller chunks

**Fallback chains**:
- CoinGecko → Signal21 → Placeholder for prices
- Always log warnings when using fallback sources

### 2.4 Integration Points for New Data

The architecture is perfectly suited for adding macroeconomic data:

1. **Create new module**: `src/macro_data.py` (follows `src/prices.py` pattern)
2. **Reuse HTTP layer**: All requests via `http_utils.cached_json_request()`
3. **Cache to Parquet**: Store in `data/cache/macro/*.parquet`
4. **Merge into panel**: Use `merge_asof()` in `panel_builder.py` to align timestamps
5. **Add tests**: Follow existing test patterns with mocked API responses
6. **Correlate with STX/BTC**: `src/macro_analysis.py` (new) computes Pearson/Spearman + lead/lag correlations for every indicator

---

## 3. Data Sources Catalog

### 3.1 Summary Table

| Indicator | Source | Auth Required | Cost | Granularity | Historical Coverage | Reliability | Implementation Effort |
|-----------|--------|---------------|------|-------------|---------------------|-------------|----------------------|
| **STX/BTC Price Ratio** | CoinGecko | No | Free | Hourly | 2013+ | ⭐⭐⭐⭐⭐ | ✅ Already implemented |
| **S&P 500 Index** | yfinance | No | Free | Daily | 1927+ | ⭐⭐⭐⭐⭐ | 🟢 5 min |
| **S&P 500 Deltas** | yfinance (computed) | No | Free | Daily | 1927+ | ⭐⭐⭐⭐⭐ | 🟢 5 min |
| **Unemployment Rate** | FRED (pandas-datareader) | No | Free | Monthly | 1948+ | ⭐⭐⭐⭐⭐ | 🟢 5 min |
| **Federal Funds Rate** | FRED (pandas-datareader) | No | Free | Daily | 1954+ | ⭐⭐⭐⭐⭐ | 🟢 5 min |
| **10-Year Treasury Yield** | FRED (pandas-datareader) | No | Free | Daily | 1962+ | ⭐⭐⭐⭐⭐ | 🟢 5 min |
| **VIX (Volatility Index)** | yfinance | No | Free | Daily | 1990+ | ⭐⭐⭐⭐⭐ | 🟢 5 min |
| **DXY (US Dollar Index)** | yfinance | No | Free | Daily | 2007+ | ⭐⭐⭐⭐ | 🟢 5 min |
| **Gold Prices** | yfinance (GC=F) | No | Free | Daily | 1975+ | ⭐⭐⭐⭐⭐ | 🟢 5 min |
| **Tether (USDT) Total Supply** | CoinGecko | No | Free | Daily | 2015+ | ⭐⭐⭐⭐ | 🟡 10 min |
| **USDC Total Supply** | CoinGecko | No | Free | Daily | 2018+ | ⭐⭐⭐⭐ | 🟡 10 min |
| **Bitcoin Dominance** | CoinGecko | No | Free | Daily | 2013+ | ⭐⭐⭐⭐⭐ | 🟢 5 min |
| **Total Crypto Market Cap** | CoinGecko | No | Free | Daily | 2013+ | ⭐⭐⭐⭐⭐ | 🟢 5 min |

**Legend**:
- ✅ Already implemented
- 🟢 Trivial (5-10 min)
- 🟡 Simple (10-30 min)
- ⭐ Reliability: 5 stars = production-grade, widely used in finance

### 3.2 Detailed Source Documentation

#### 3.2.1 yfinance (Traditional Finance & Commodities)

**Library**: `yfinance>=0.2.28`

**Capabilities**:
- S&P 500: Ticker `^GSPC`
- VIX: Ticker `^VIX`
- DXY: Ticker `DX=F` (futures contract)
- Gold: Ticker `GC=F` (futures contract)

**API Pattern**:
```python
import yfinance as yf

# Fetch S&P 500 data
ticker = yf.Ticker("^GSPC")
df = ticker.history(start="2023-11-01", end="2025-11-03", interval="1d")
# Returns DataFrame with: Open, High, Low, Close, Volume, Dividends, Stock Splits
```

**Rate limits**: None (scrapes Yahoo Finance website)

**Reliability**: Used by thousands of quant researchers and finance professionals. Occasionally has brief outages during market volatility.

**Caching strategy**: Cache daily OHLCV data in `data/cache/macro/yfinance_{ticker}_{start}_{end}.parquet`

**Error handling**:
- Network timeouts: Retry with exponential backoff
- Missing data for specific dates: Forward-fill from last valid value
- Ticker delisted/invalid: Raise clear error with ticker name

#### 3.2.2 FRED (Federal Reserve Economic Data)

**Library**: `pandas-datareader>=0.10.0`

**Capabilities**:
- Unemployment Rate: Series `UNRATE`
- Federal Funds Rate: Series `DFF` (daily) or `FEDFUNDS` (monthly)
- 10-Year Treasury Yield: Series `DGS10`

**API Pattern**:
```python
from pandas_datareader import data as pdr

# Fetch unemployment rate
df = pdr.DataReader("UNRATE", "fred", start="2023-11-01", end="2025-11-03")
# Returns DataFrame with DatetimeIndex and single column of values
```

**Rate limits**: 50 requests/second (generous for our use case)

**Reliability**: ⭐⭐⭐⭐⭐ Official US government data. Extremely stable and authoritative.

**Caching strategy**: Cache series in `data/cache/macro/fred_{series_id}_{start}_{end}.parquet`

**Error handling**:
- Series ID not found: Clear error message with suggestion to check FRED website
- Date range unavailable: Truncate to available range and warn user
- Network issues: Retry with exponential backoff

#### 3.2.3 CoinGecko (Crypto & Stablecoins)

**Already integrated** in `src/prices.py`

**Additional endpoints for this analysis**:
- Bitcoin dominance: `/global` endpoint, field `data.market_cap_percentage.btc`
- Total crypto market cap: `/global` endpoint, field `data.total_market_cap.usd`
- Tether total supply: `/coins/tether/market_chart/range` (derive supply = market_cap / price)
- USDC total supply: `/coins/usd-coin/market_chart/range` (derive supply = market_cap / price)

**API Pattern**:
```python
import requests

# Fetch Tether total supply over time
url = "https://api.coingecko.com/api/v3/coins/tether/market_chart/range"
params = {
    "vs_currency": "usd",
    "from": int(pd.Timestamp("2023-11-01", tz="UTC").timestamp()),
    "to": int(pd.Timestamp("2025-11-03", tz="UTC").timestamp()),
}
response = requests.get(url, params=params, timeout=30)
response.raise_for_status()
data = response.json()
```

**Price endpoints**: For STX pricing, CoinGecko uses the `blockstack` slug (`/coins/blockstack/market_chart/range`), not `stacks`.

**Rate limits**: 10-50 calls/minute (free tier). Our caching strategy respects this.

**Reliability**: ⭐⭐⭐⭐⭐ Industry standard for crypto pricing. Occasional brief outages during high volatility.

**Note**: CoinGecko does not provide a direct historical `total_supply` series for stablecoins. Approximating supply via `market_cap / price` is robust because price stays near $1; applying both series ensures resilience if stablecoin pegs deviate intraday.

**Existing caching**: Already implemented in `http_utils.py` with 6-hour TTL for CoinGecko

#### 3.2.4 Alternative/Advanced Sources (Phase 2)

These are optional enhancements for deeper analysis:

| Source | Use Case | API Key | Cost | Complexity |
|--------|----------|---------|------|------------|
| **Blockchain.com** | On-chain Bitcoin metrics (active addresses, hash rate) | No | Free | Medium |
| **Glassnode** | Advanced on-chain analytics (MVRV, SOPR) | Yes | $39-799/mo | Medium |
| **Etherscan** | Precise USDT/USDC minting events on Ethereum | Yes (free) | Free | Medium |
| **CryptoQuant** | Exchange flows, miner metrics | Yes | $79-299/mo | Medium |
| **Alternative.me** | Crypto Fear & Greed Index | No | Free | Low |

**Recommendation**: Start with Phase 1 (free, no-auth sources) and evaluate whether paid sources add value after initial analysis.

---

## 4. Technical Implementation Plan

### 4.1 Phase 1: Core Infrastructure (2-3 hours)

#### Step 1: Add Dependencies

**File**: `/Users/alexanderhuth/Code/stx-labs/.conductor/kuwait/requirements.txt`

```diff
pandas>=2.0.0
numpy>=1.24.0
requests>=2.31.0
python-dotenv>=1.0.0
plotly>=5.14.0
+ yfinance>=0.2.28
+ pandas-datareader>=0.10.0
```

**Installation** (after updating `requirements.txt`):
```bash
make setup  # ensures the virtualenv is up to date
pip install --upgrade yfinance pandas-datareader
pip freeze > requirements.txt
```

#### Step 2: Create `src/macro_data.py`

**Structure** (mirroring `src/prices.py`):

```python
"""
Macroeconomic data fetching with caching.

Provides functions to fetch traditional finance indicators (S&P 500, unemployment,
interest rates) and crypto-specific metrics (stablecoin supply, Bitcoin dominance).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf
from pandas_datareader import data as pdr

from src.cache_utils import read_parquet, write_parquet
from src.config import CACHE_DIR
from src.http_utils import RequestOptions, build_session, cached_json_request

MACRO_CACHE_DIR = CACHE_DIR / "macro"
MACRO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_COINGECKO_SESSION = build_session({"Accept": "application/json", "User-Agent": "stx-labs-macro/1.0"})


def _cache_path(slug: str, start_date: str, end_date: str) -> Path:
    return MACRO_CACHE_DIR / f"{slug}_{start_date}_{end_date}.parquet"


def _load_cached_frame(cache_file: Path) -> pd.DataFrame | None:
    cached = read_parquet(cache_file)
    if cached is None or cached.empty:
        return None
    frame = cached.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    return frame


def _store_frame(cache_file: Path, frame: pd.DataFrame) -> None:
    normalised = frame.copy()
    normalised["date"] = pd.to_datetime(normalised["date"]).dt.date
    write_parquet(cache_file, normalised)


def fetch_sp500_data(
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch S&P 500 index levels with computed daily deltas.

    Returns columns: date, sp500_close, sp500_pct_change
    """
    cache_file = _cache_path("sp500", start_date, end_date)
    if not force_refresh:
        cached = _load_cached_frame(cache_file)
        if cached is not None:
            return cached

    history = (
        yf.Ticker("^GSPC")
        .history(start=start_date, end=end_date, interval="1d")
        .rename_axis("date")
        .reset_index(names="date")
    )
    if history.empty:
        result = pd.DataFrame(columns=["date", "sp500_close", "sp500_pct_change"])
    else:
        result = history[["date", "Close"]].rename(columns={"Close": "sp500_close"})
        result["date"] = pd.to_datetime(result["date"]).dt.date
        result["sp500_pct_change"] = result["sp500_close"].pct_change() * 100

    _store_frame(cache_file, result)
    return result


def fetch_unemployment_data(
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch US unemployment rate from FRED.

    Returns columns: date, unemployment_rate
    """
    cache_file = _cache_path("unemployment", start_date, end_date)
    if not force_refresh:
        cached = _load_cached_frame(cache_file)
        if cached is not None:
            return cached

    df = (
        pdr.DataReader("UNRATE", "fred", start=start_date, end=end_date)
        .rename_axis("date")
        .reset_index(names="date")
    )
    if df.empty:
        result = pd.DataFrame(columns=["date", "unemployment_rate"])
    else:
        df["date"] = pd.to_datetime(df["date"]).dt.date
        result = df.rename(columns={"UNRATE": "unemployment_rate"})

    _store_frame(cache_file, result)
    return result


def fetch_interest_rates(
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch Federal Funds Rate and 10-Year Treasury Yield from FRED.

    Returns columns: date, fed_funds_rate, treasury_10y
    """
    cache_file = _cache_path("rates", start_date, end_date)
    if not force_refresh:
        cached = _load_cached_frame(cache_file)
        if cached is not None:
            return cached

    dff = (
        pdr.DataReader("DFF", "fred", start=start_date, end=end_date)
        .rename_axis("date")
        .reset_index(names="date")
    )
    dgs10 = (
        pdr.DataReader("DGS10", "fred", start=start_date, end=end_date)
        .rename_axis("date")
        .reset_index(names="date")
    )

    dff["date"] = pd.to_datetime(dff["date"]).dt.date
    dgs10["date"] = pd.to_datetime(dgs10["date"]).dt.date

    result = (
        dff.rename(columns={"DFF": "fed_funds_rate"})
        .merge(dgs10.rename(columns={"DGS10": "treasury_10y"}), on="date", how="outer")
        .sort_values("date")
    )

    _store_frame(cache_file, result)
    return result


def fetch_volatility_data(
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch VIX (CBOE Volatility Index).

    Returns columns: date, vix_close
    """
    cache_file = _cache_path("vix", start_date, end_date)
    if not force_refresh:
        cached = _load_cached_frame(cache_file)
        if cached is not None:
            return cached

    history = (
        yf.Ticker("^VIX")
        .history(start=start_date, end=end_date, interval="1d")
        .rename_axis("date")
        .reset_index(names="date")
    )
    if history.empty:
        result = pd.DataFrame(columns=["date", "vix_close"])
    else:
        result = history[["date", "Close"]].rename(columns={"Close": "vix_close"})
        result["date"] = pd.to_datetime(result["date"]).dt.date

    _store_frame(cache_file, result)
    return result


def _coingecko_market_chart_range(coin_id: str, start_ts: int, end_ts: int) -> dict:
    return cached_json_request(
        RequestOptions(
            prefix=f"coingecko_{coin_id}_macro",
            session=_COINGECKO_SESSION,
            method="GET",
            url=f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range",
            params={
                "vs_currency": "usd",
                "from": start_ts,
                "to": end_ts,
                "interval": "daily",
            },
            ttl_seconds=6 * 3600,
        )
    )


def _coingecko_supply_frame(
    coin_id: str,
    column_name: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = int(start_dt.timestamp())
    end_ts = min(int(end_dt.timestamp()), now_ts)

    if start_ts >= end_ts:
        return pd.DataFrame(columns=["date", column_name])

    payload = _coingecko_market_chart_range(coin_id, start_ts, end_ts)
    market_caps = pd.DataFrame(payload.get("market_caps", []), columns=["timestamp_ms", "market_cap_usd"])
    prices = pd.DataFrame(payload.get("prices", []), columns=["timestamp_ms", "price_usd"])

    if market_caps.empty or prices.empty:
        return pd.DataFrame(columns=["date", column_name])

    frame = market_caps.merge(prices, on="timestamp_ms", how="inner")
    frame["date"] = pd.to_datetime(frame["timestamp_ms"], unit="ms").dt.date
    frame[column_name] = frame["market_cap_usd"] / frame["price_usd"].replace({0: pd.NA})
    frame = frame.dropna(subset=[column_name])
    return frame[["date", column_name]].sort_values("date")


def fetch_stablecoin_supply(
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch Tether (USDT) and USDC total supply from CoinGecko.

    Returns columns: date, usdt_supply, usdc_supply, usdt_daily_change, usdc_daily_change
    """
    cache_file = _cache_path("stablecoins", start_date, end_date)
    if not force_refresh:
        cached = _load_cached_frame(cache_file)
        if cached is not None:
            return cached

    usdt = _coingecko_supply_frame("tether", "usdt_supply", start_date, end_date)
    usdc = _coingecko_supply_frame("usd-coin", "usdc_supply", start_date, end_date)

    result = (
        usdt.merge(usdc, on="date", how="outer")
        .sort_values("date")
        .assign(
            usdt_daily_change=lambda df: df["usdt_supply"].diff(),
            usdc_daily_change=lambda df: df["usdc_supply"].diff(),
        )
    )

    _store_frame(cache_file, result)
    return result


def fetch_additional_indicators(
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch DXY (US Dollar Index) and Gold prices.

    Returns columns: date, dxy_close, gold_close
    """
    cache_file = _cache_path("additional", start_date, end_date)
    if not force_refresh:
        cached = _load_cached_frame(cache_file)
        if cached is not None:
            return cached

    dxy_history = (
        yf.Ticker("DX=F")
        .history(start=start_date, end=end_date, interval="1d")
        .rename_axis("date")
        .reset_index(names="date")
    )
    gold_history = (
        yf.Ticker("GC=F")
        .history(start=start_date, end=end_date, interval="1d")
        .rename_axis("date")
        .reset_index(names="date")
    )

    result = (
        dxy_history[["date", "Close"]].rename(columns={"Close": "dxy_close"})
        .merge(
            gold_history[["date", "Close"]].rename(columns={"Close": "gold_close"}),
            on="date",
            how="outer",
        )
        .sort_values("date")
    )
    result["date"] = pd.to_datetime(result["date"]).dt.date

    _store_frame(cache_file, result)
    return result


def load_macro_panel(
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Load all macroeconomic indicators into a single panel DataFrame.

    Returns a dataframe with all macro indicators aligned by date.
    """
    frames = [
        fetch_sp500_data(start_date, end_date, force_refresh),
        fetch_unemployment_data(start_date, end_date, force_refresh),
        fetch_interest_rates(start_date, end_date, force_refresh),
        fetch_volatility_data(start_date, end_date, force_refresh),
        fetch_stablecoin_supply(start_date, end_date, force_refresh),
        fetch_additional_indicators(start_date, end_date, force_refresh),
    ]

    panel = frames[0]
    for frame in frames[1:]:
        panel = panel.merge(frame, on="date", how="outer")

    return panel.sort_values("date").reset_index(drop=True)
```

**Key design decisions**:
1. **Follows existing patterns**: Each fetch function mirrors `src/prices.py` structure
2. **Parquet caching**: All cleaned data cached in `data/cache/macro/`
3. **Explicit supply derivation**: Stablecoin supply computed from CoinGecko `market_cap / price`, preventing the common `total_volumes` misinterpretation
4. **Single entry point**: `load_macro_panel()` aggregates all indicators

#### Step 3: Update Configuration

**File**: `/Users/alexanderhuth/Code/stx-labs/.conductor/kuwait/src/config.py`

No changes needed—the new module instantiates `data/cache/macro/` on demand using the existing `CACHE_DIR` foundation.

#### Step 4: Create Cache Directory

No manual action required—the module initialises `data/cache/macro/` on import. Verify the path exists after the first run to confirm write permissions.

### 4.2 Phase 2: Testing (1-2 hours)

#### Create `tests/test_macro_data.py`

```python
"""
Tests for macro_data.py with mocked external APIs.
"""

import pandas as pd
import pytest
from unittest.mock import Mock, patch
from pathlib import Path

from src.macro_data import (
    fetch_sp500_data,
    fetch_unemployment_data,
    fetch_interest_rates,
    fetch_volatility_data,
    fetch_stablecoin_supply,
    load_macro_panel
)


@pytest.fixture
def temp_cache_dir(tmp_path, monkeypatch):
    """Use temporary directory for caching in tests."""
    macro_dir = tmp_path / "cache" / "macro"
    macro_dir.mkdir(parents=True)
    monkeypatch.setattr("src.macro_data.MACRO_CACHE_DIR", macro_dir)
    return macro_dir


def test_fetch_sp500_uses_cache(temp_cache_dir, monkeypatch):
    """Verify S&P 500 data is cached and reused."""

    # Mock yfinance Ticker
    mock_history = pd.DataFrame({
        "Close": [4500.0, 4550.0, 4525.0],
        "Open": [4480.0, 4530.0, 4540.0]
    }, index=pd.date_range("2024-01-01", periods=3))

    mock_ticker = Mock()
    mock_ticker.history.return_value = mock_history

    with patch("yfinance.Ticker", return_value=mock_ticker):
        # First call fetches from API
        df1 = fetch_sp500_data("2024-01-01", "2024-01-03")
        assert len(df1) == 3
        assert "sp500_close" in df1.columns
        assert "sp500_pct_change" in df1.columns

        # Second call hits cache (no API call)
        df2 = fetch_sp500_data("2024-01-01", "2024-01-03")
        pd.testing.assert_frame_equal(df1, df2)

        # Verify only one API call was made
        assert mock_ticker.history.call_count == 1


def test_fetch_unemployment_data(temp_cache_dir, monkeypatch):
    """Test unemployment data fetching from FRED."""

    mock_df = pd.DataFrame({
        "UNRATE": [3.7, 3.8, 3.9]
    }, index=pd.date_range("2024-01-01", periods=3, freq="MS"))

    with patch("pandas_datareader.data.DataReader", return_value=mock_df):
        df = fetch_unemployment_data("2024-01-01", "2024-03-01")

        assert len(df) == 3
        assert "unemployment_rate" in df.columns
        assert df["unemployment_rate"].iloc[0] == 3.7


def test_fetch_stablecoin_supply_computes_changes(temp_cache_dir, monkeypatch):
    """Test stablecoin supply fetching and daily change computation."""

    mock_usdt_response = {
        "market_caps": [
            [1704067200000, 95_000_000_000],  # 2024-01-01
            [1704153600000, 96_000_000_000],  # 2024-01-02
            [1704240000000, 96_500_000_000],  # 2024-01-03
        ],
        "prices": [
            [1704067200000, 1.0],
            [1704153600000, 1.0],
            [1704240000000, 1.0],
        ],
    }

    mock_usdc_response = {
        "market_caps": [
            [1704067200000, 24_000_000_000],
            [1704153600000, 24_200_000_000],
            [1704240000000, 24_100_000_000],
        ],
        "prices": [
            [1704067200000, 1.0],
            [1704153600000, 1.0],
            [1704240000000, 1.0],
        ],
    }

    def mock_request(options):
        if "tether" in options.url:
            return mock_usdt_response
        else:
            return mock_usdc_response

    with patch("src.macro_data.cached_json_request", side_effect=mock_request):
        df = fetch_stablecoin_supply("2024-01-01", "2024-01-03")

        assert len(df) == 3
        assert "usdt_supply" in df.columns
        assert "usdc_supply" in df.columns
        assert "usdt_daily_change" in df.columns
        assert "usdc_daily_change" in df.columns

        # Verify daily change computation
        assert df["usdt_daily_change"].iloc[1] == 1_000_000_000  # 96B - 95B
        assert df["usdc_daily_change"].iloc[2] == -100_000_000   # 24.1B - 24.2B


def test_load_macro_panel_merges_all_sources(temp_cache_dir, monkeypatch):
    """Test that load_macro_panel combines all indicators."""

    # Mock all fetch functions to return simple DataFrames
    with patch("src.macro_data.fetch_sp500_data") as mock_sp500, \
         patch("src.macro_data.fetch_unemployment_data") as mock_unemp, \
         patch("src.macro_data.fetch_interest_rates") as mock_rates, \
         patch("src.macro_data.fetch_volatility_data") as mock_vix, \
         patch("src.macro_data.fetch_stablecoin_supply") as mock_stable, \
         patch("src.macro_data.fetch_additional_indicators") as mock_add:

        dates = pd.date_range("2024-01-01", periods=3).date

        mock_sp500.return_value = pd.DataFrame({"date": dates, "sp500_close": [4500, 4550, 4525]})
        mock_unemp.return_value = pd.DataFrame({"date": dates, "unemployment_rate": [3.7, 3.7, 3.8]})
        mock_rates.return_value = pd.DataFrame({"date": dates, "fed_funds_rate": [5.33, 5.33, 5.33]})
        mock_vix.return_value = pd.DataFrame({"date": dates, "vix_close": [13.5, 14.2, 13.8]})
        mock_stable.return_value = pd.DataFrame({"date": dates, "usdt_supply": [95e9, 96e9, 96.5e9]})
        mock_add.return_value = pd.DataFrame({"date": dates, "dxy_close": [102.5, 102.8, 102.3]})

        panel = load_macro_panel("2024-01-01", "2024-01-03")

        # Verify all columns present
        assert "sp500_close" in panel.columns
        assert "unemployment_rate" in panel.columns
        assert "fed_funds_rate" in panel.columns
        assert "vix_close" in panel.columns
        assert "usdt_supply" in panel.columns
        assert "dxy_close" in panel.columns

        # Verify length
        assert len(panel) == 3


def test_force_refresh_bypasses_cache(temp_cache_dir, monkeypatch):
    """Verify force_refresh=True skips cache and fetches fresh data."""

    mock_history = pd.DataFrame({
        "Close": [4500.0, 4550.0],
        "Open": [4480.0, 4530.0]
    }, index=pd.date_range("2024-01-01", periods=2))

    mock_ticker = Mock()
    mock_ticker.history.return_value = mock_history

    with patch("yfinance.Ticker", return_value=mock_ticker):
        # First call
        df1 = fetch_sp500_data("2024-01-01", "2024-01-02")

        # Second call with force_refresh should hit API again
        df2 = fetch_sp500_data("2024-01-01", "2024-01-02", force_refresh=True)

        # Both should return same data, but API called twice
        pd.testing.assert_frame_equal(df1, df2)
        assert mock_ticker.history.call_count == 2
```

**Test execution**:
```bash
pytest tests/test_macro_data.py -v
```

### 4.3 Phase 3: Notebook Integration (2-3 hours)

#### Create new analysis notebook: `notebooks/stx_btc_macro_correlations.ipynb`

**Structure**:

```python
# Cell 1: Imports and setup
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.config import OUT_DIR
from src.prices import load_price_panel
from src.macro_data import load_macro_panel

# Parameters (papermill-compatible)
HISTORY_DAYS = 730  # Override via papermill parameter
FORCE_REFRESH = False

END_TS = datetime.now(timezone.utc)
START_TS = END_TS - timedelta(days=HISTORY_DAYS)
START_DATE = START_TS.date().isoformat()
END_DATE = END_TS.date().isoformat()

print(f"Analysis period: {START_DATE} to {END_DATE}")
```

```python
# Cell 2: Fetch price data (STX/BTC ratio)
print("Fetching STX/BTC price data...")
price_panel = load_price_panel(
    start=START_TS,
    end=END_TS,
    frequency="1D",  # Daily frequency for macro analysis
    force_refresh=FORCE_REFRESH,
)

print(f"Loaded {len(price_panel)} daily price records")
print(f"Columns: {price_panel.columns.tolist()}")
price_panel.head()
```

```python
# Cell 3: Fetch macroeconomic indicators
print("Fetching macroeconomic indicators...")
macro_panel = load_macro_panel(
    start_date=START_DATE,
    end_date=END_DATE,
    force_refresh=FORCE_REFRESH,
)

print(f"Loaded {len(macro_panel)} macro indicator records")
print(f"Columns: {macro_panel.columns.tolist()}")
macro_panel.head()
```

```python
# Cell 4: Merge price and macro data
print("Merging price and macro panels...")

# Convert timestamp to date for merging
price_panel["date"] = pd.to_datetime(price_panel["ts"], utc=True).dt.date
macro_panel["date"] = pd.to_datetime(macro_panel["date"]).dt.date

# Merge on date
full_panel = price_panel.merge(macro_panel, on="date", how="left")

print(f"Merged panel: {len(full_panel)} records")
print("Missing values per column:")
print(full_panel.isnull().sum())

# Forward-fill missing macro values (since some update monthly)
full_panel = full_panel.ffill()

full_panel.head()
```

```python
# Cell 5: Correlation analysis
print("Computing correlations with STX/BTC ratio...")

correlation_cols = [
    "sp500_close",
    "sp500_pct_change",
    "unemployment_rate",
    "fed_funds_rate",
    "treasury_10y",
    "vix_close",
    "usdt_supply",
    "usdc_supply",
    "usdt_daily_change",
    "usdc_daily_change",
    "dxy_close",
    "gold_close"
]

correlations = full_panel[["stx_btc"] + correlation_cols].corr()["stx_btc"].drop("stx_btc")
correlations = correlations.sort_values(ascending=False)

print("\nCorrelations with STX/BTC ratio:")
print(correlations)

# Plot correlation heatmap
fig = go.Figure(data=go.Heatmap(
    z=[correlations.values],
    x=correlations.index,
    y=["STX/BTC"],
    colorscale="RdBu",
    zmid=0,
    text=[correlations.values],
    texttemplate="%{text:.3f}",
    textfont={"size": 10}
))
fig.update_layout(
    title="Correlation with STX/BTC Ratio",
    xaxis_title="Indicator",
    height=300
)
fig.show()
```

```python
# Cell 6: Time series visualization
print("Creating time series dashboard...")

fig = make_subplots(
    rows=5,
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.05,
    subplot_titles=[
        "STX/BTC Price Ratio",
        "S&P 500 Index",
        "Stablecoin Supply (Tether + USDC)",
        "Interest Rates (Fed Funds & 10Y Treasury)",
        "VIX Volatility Index"
    ],
    specs=[[{"secondary_y": False}],
           [{"secondary_y": False}],
           [{"secondary_y": True}],
           [{"secondary_y": False}],
           [{"secondary_y": False}]]
)

# Row 1: STX/BTC ratio
fig.add_trace(
    go.Scatter(x=full_panel["date"], y=full_panel["stx_btc"], name="STX/BTC", line=dict(color="purple")),
    row=1, col=1
)

# Row 2: S&P 500
fig.add_trace(
    go.Scatter(x=full_panel["date"], y=full_panel["sp500_close"], name="S&P 500", line=dict(color="blue")),
    row=2, col=1
)

# Row 3: Stablecoin supply (dual axis)
fig.add_trace(
    go.Scatter(x=full_panel["date"], y=full_panel["usdt_supply"] / 1e9, name="USDT Supply (B)", line=dict(color="green")),
    row=3, col=1, secondary_y=False
)
fig.add_trace(
    go.Scatter(x=full_panel["date"], y=full_panel["usdc_supply"] / 1e9, name="USDC Supply (B)", line=dict(color="cyan")),
    row=3, col=1, secondary_y=True
)

# Row 4: Interest rates
fig.add_trace(
    go.Scatter(x=full_panel["date"], y=full_panel["fed_funds_rate"], name="Fed Funds Rate", line=dict(color="red")),
    row=4, col=1
)
fig.add_trace(
    go.Scatter(x=full_panel["date"], y=full_panel["treasury_10y"], name="10Y Treasury", line=dict(color="orange")),
    row=4, col=1
)

# Row 5: VIX
fig.add_trace(
    go.Scatter(x=full_panel["date"], y=full_panel["vix_close"], name="VIX", line=dict(color="darkred")),
    row=5, col=1
)

fig.update_layout(height=1200, title_text="STX/BTC vs Macroeconomic Indicators (2-Year View)")
fig.update_xaxes(title_text="Date", row=5, col=1)

fig.show()

# Save to HTML
output_file = OUT_DIR / "stx_btc_macro_dashboard.html"
fig.write_html(output_file)
print(f"Dashboard saved to {output_file}")
```

```python
# Cell 7: Tether hypothesis testing - Lead/lag analysis
print("Testing Tether minting hypothesis with lead/lag analysis...")

# Compute rolling correlations with various lags
lags = range(-30, 31)  # -30 days to +30 days
lag_correlations = []

for lag in lags:
    shifted = full_panel["usdt_daily_change"].shift(lag)
    aligned = pd.concat([full_panel["btc_usd"], shifted], axis=1, join="inner").dropna()
    if len(aligned) < 2:
        corr = float("nan")
    else:
        corr = aligned["btc_usd"].corr(aligned["usdt_daily_change"])
    lag_correlations.append({"lag_days": lag, "correlation": corr})

lag_df = pd.DataFrame(lag_correlations)

# Plot lead/lag correlation
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=lag_df["lag_days"],
    y=lag_df["correlation"],
    mode="lines+markers",
    name="Correlation",
    line=dict(color="green", width=2)
))
fig.add_vline(x=0, line_dash="dash", line_color="red", annotation_text="No lag")
fig.update_layout(
    title="USDT Supply Change vs BTC Price: Lead/Lag Correlation",
    xaxis_title="Lag (days) - Negative = Stablecoin leads BTC",
    yaxis_title="Correlation",
    height=400
)
fig.show()

# Find peak correlation
peak_lag = lag_df.loc[lag_df["correlation"].idxmax()]
print(f"\nPeak correlation: {peak_lag['correlation']:.4f} at lag {peak_lag['lag_days']} days")
if peak_lag["lag_days"] < 0:
    print(f"  → USDT minting LEADS BTC price by {abs(peak_lag['lag_days'])} days")
elif peak_lag["lag_days"] > 0:
    print(f"  → USDT minting LAGS BTC price by {peak_lag['lag_days']} days")
else:
    print(f"  → USDT minting and BTC price move simultaneously")
```

```python
# Cell 8: Regime detection - High vs. low stablecoin minting periods
print("Analyzing STX/BTC behavior during high vs. low stablecoin minting...")

# Define high/low minting regimes (top/bottom quartile)
usdt_change_threshold_high = full_panel["usdt_daily_change"].quantile(0.75)
usdt_change_threshold_low = full_panel["usdt_daily_change"].quantile(0.25)

full_panel["stablecoin_regime"] = "Medium"
full_panel.loc[full_panel["usdt_daily_change"] >= usdt_change_threshold_high, "stablecoin_regime"] = "High Minting"
full_panel.loc[full_panel["usdt_daily_change"] <= usdt_change_threshold_low, "stablecoin_regime"] = "Low/Negative Minting"

# Compare STX/BTC behavior across regimes
regime_stats = full_panel.groupby("stablecoin_regime").agg({
    "stx_btc": ["mean", "std", "min", "max"],
    "btc_usd": ["mean", "std"],
    "sp500_pct_change": "mean"
})

print("\nSTX/BTC statistics by stablecoin minting regime:")
print(regime_stats)

# Visualize
fig = go.Figure()
for regime in ["High Minting", "Medium", "Low/Negative Minting"]:
    subset = full_panel[full_panel["stablecoin_regime"] == regime]
    fig.add_trace(go.Scatter(
        x=subset["date"],
        y=subset["stx_btc"],
        mode="markers",
        name=regime,
        marker=dict(size=4, opacity=0.6)
    ))

fig.update_layout(
    title="STX/BTC Ratio by Stablecoin Minting Regime",
    xaxis_title="Date",
    yaxis_title="STX/BTC",
    height=500
)
fig.show()
```

```python
# Cell 9: Export results
print("Exporting analysis results...")

# Export full panel
full_panel.to_parquet(OUT_DIR / "stx_btc_macro_panel.parquet")
full_panel.to_csv(OUT_DIR / "stx_btc_macro_panel.csv", index=False)

# Export correlation table
correlations.to_csv(OUT_DIR / "stx_btc_correlations.csv")

# Export lead/lag analysis
lag_df.to_csv(OUT_DIR / "usdt_btc_leadlag_analysis.csv", index=False)

# Export regime statistics
regime_stats.to_csv(OUT_DIR / "stablecoin_regime_statistics.csv")

print("Analysis complete! Outputs saved to out/ directory:")
print("  - stx_btc_macro_panel.parquet/.csv")
print("  - stx_btc_correlations.csv")
print("  - usdt_btc_leadlag_analysis.csv")
print("  - stablecoin_regime_statistics.csv")
print("  - stx_btc_macro_dashboard.html")
```

**Makefile addition**:
```makefile
.PHONY: notebook-macro
notebook-macro:  ## Run STX/BTC macro correlation analysis
	papermill notebooks/stx_btc_macro_correlations.ipynb out/stx_btc_macro_correlations_output.ipynb

.PHONY: notebook-macro-bg
notebook-macro-bg:  ## Run macro analysis in background
	nohup papermill notebooks/stx_btc_macro_correlations.ipynb out/stx_btc_macro_correlations_output.ipynb > out/macro_notebook.log 2>&1 &
	@echo "Macro analysis running in background. Monitor with: tail -f out/macro_notebook.log"
```

---

## 5. Testing Strategy

### 5.1 Unit Tests

**Coverage targets**:
- `src/macro_data.py`: ≥85% line coverage
- All fetch functions tested with mocked APIs
- Cache hit/miss scenarios verified
- Error handling for network failures, missing data

**Test fixtures**:
- `temp_cache_dir`: Isolate cache between tests
- Mock responses for yfinance, pandas-datareader, CoinGecko

### 5.2 Integration Tests

**Smoke test** (add to existing `make smoke-notebook`):
```bash
# 30-day test with macro indicators (cache-only)
make notebook-macro HISTORY_DAYS=30 FORCE_REFRESH=False
```

**Full integration**:
```bash
# Full 2-year analysis with fresh data
make notebook-macro HISTORY_DAYS=730 FORCE_REFRESH=True
```

### 5.3 Data Quality Checks

Within notebook (Cell 4):
```python
# Verify data completeness
required_cols = ["stx_btc", "sp500_close", "usdt_supply", "fed_funds_rate"]
for col in required_cols:
    missing_pct = full_panel[col].isnull().sum() / len(full_panel) * 100
    assert missing_pct < 5, f"{col} has {missing_pct:.1f}% missing values (threshold: 5%)"
    print(f"✓ {col}: {missing_pct:.2f}% missing")
```

---

## 6. Visualization & Analysis Approach

### 6.1 Primary Visualizations

**Dashboard 1: Time Series Overview** (5 subplots, shared x-axis)
- STX/BTC ratio
- S&P 500 index
- USDT + USDC supply (dual y-axis)
- Interest rates (Fed Funds + 10Y Treasury)
- VIX volatility

**Dashboard 2: Correlation Heatmap**
- Rolling 30-day correlations between STX/BTC and all indicators
- Color-coded: red (negative), white (neutral), blue (positive)
- Identify regime changes over time

**Dashboard 3: Lead/Lag Analysis**
- X-axis: Lag in days (-30 to +30)
- Y-axis: Correlation with BTC price
- Highlight peak correlation to determine if Tether minting leads/lags price

**Dashboard 4: Regime Comparison**
- Box plots of STX/BTC distribution during:
  - High stablecoin minting periods
  - Medium minting periods
  - Low/negative minting periods
- Statistical tests (t-test) for significance

### 6.2 Statistical Methods

**Correlation metrics**:
- Pearson correlation (linear relationships)
- Spearman rank correlation (non-linear monotonic relationships)
- Rolling window: 30 days, 60 days, 90 days

**Lead/lag analysis**:
- Cross-correlation function (CCF) for time-lagged correlations
- Granger causality test (optional Phase 2)

**Regime detection**:
- Quantile-based thresholds (top/bottom 25% for high/low regimes)
- Hidden Markov Models for state detection (optional advanced analysis)

### 6.3 Key Questions to Answer

1. **Tether hypothesis**:
   - Does USDT supply increase precede BTC price rallies?
   - What is the optimal lag (if any)?
   - Is the effect stronger for large minting events (>$1B)?

2. **Traditional finance spillovers**:
   - Does S&P 500 momentum predict STX/BTC changes?
   - Do interest rate hikes correlate with STX/BTC compression?
   - Does VIX (fear index) spike before crypto selloffs?

3. **Crypto-specific dynamics**:
   - Does Bitcoin dominance increase hurt STX/BTC ratio?
   - Are there structural breaks around major events (halving, Nakamoto upgrade)?

4. **Regime identification**:
   - Can we classify periods as "risk-on" (high S&P, low VIX) vs. "risk-off"?
   - Does STX/BTC behave differently in each regime?

---

## 7. Risk Assessment & Mitigation

### 7.1 Data Quality Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **API rate limits** | Incomplete data fetch | Medium | Caching + exponential backoff |
| **Missing historical data** | Gaps in analysis | Low | Forward-fill + document gaps |
| **Stale CoinGecko data** | Inaccurate stablecoin supply | Low | 6-hour cache TTL + manual refresh |
| **yfinance scraping breaks** | No S&P 500 data | Low | Fallback to FRED SPY ETF data |
| **FRED series discontinued** | No unemployment/rates | Very Low | Official govt data, very stable |

### 7.2 Analysis Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **Spurious correlations** | False insights | High | Use multiple correlation metrics; validate with domain knowledge |
| **Look-ahead bias** | Invalid backtesting | Medium | Ensure all merges use `merge_asof` with proper direction |
| **Overfitting to 2-year period** | Non-generalizable | Medium | Acknowledge limitations; suggest longer backtest in future |
| **Confounding variables** | Misattributed causality | High | Clearly state "correlation ≠ causation"; run multivariate regression |

### 7.3 Technical Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **Memory overflow** | Notebook crash | Low | Use daily (not hourly) frequency; 730 days × 15 indicators = ~11K rows (manageable) |
| **Cache corruption** | Stale/invalid data | Low | Validate Parquet files on read; fallback to fresh fetch |
| **Dependency conflicts** | Import errors | Low | Pin versions in requirements.txt; test in clean venv |

---

## 8. Timeline & Milestones

### 8.1 Phase 1: Core Implementation (2-3 hours)

**Deliverables**:
- [x] Research data sources (COMPLETED)
- [ ] Add dependencies to requirements.txt
- [ ] Create `src/macro_data.py` with 6 fetch functions
- [ ] Create `data/cache/macro/` directory
- [ ] Basic unit tests in `tests/test_macro_data.py`

**Success criteria**:
- All fetch functions return valid DataFrames
- Cache hit/miss works correctly
- `pytest tests/test_macro_data.py` passes

### 8.2 Phase 2: Testing & Validation (1-2 hours)

**Deliverables**:
- [ ] Complete test coverage (≥85%)
- [ ] Smoke test with 30-day window
- [ ] Data quality validation checks

**Success criteria**:
- All tests pass
- Smoke test completes without errors
- Missing data <5% for all indicators

### 8.3 Phase 3: Analysis & Visualization (2-3 hours)

**Deliverables**:
- [ ] Create `notebooks/stx_btc_macro_correlations.ipynb`
- [ ] Implement 4 core visualizations
- [ ] Lead/lag analysis for Tether hypothesis
- [ ] Regime detection and comparison
- [ ] Export results to CSV/HTML

**Success criteria**:
- Notebook runs end-to-end without errors
- All visualizations render correctly
- Tether lead/lag analysis produces clear result
- Outputs saved to `out/` directory

### 8.4 Phase 4: Documentation & Refinement (1 hour)

**Deliverables**:
- [ ] Update README.md with new analysis
- [ ] Add Makefile targets for macro analysis
- [ ] Document key findings in `docs/macro_findings.md`
- [ ] Create pull request with bead reference

**Success criteria**:
- Documentation is clear and complete
- Make targets work as expected
- Code review passes

---

## 9. Appendices

### Appendix A: Code Snippets

#### A.1 yfinance Usage

```python
import yfinance as yf

# Fetch S&P 500 historical data
ticker = yf.Ticker("^GSPC")
df = ticker.history(start="2023-11-01", end="2025-11-03", interval="1d")

# Returns DataFrame:
#             Open    High     Low   Close      Volume  Dividends  Stock Splits
# 2023-11-01  4200.5  4225.0  4195.0  4210.3  5000000000      0.0           0.0
# ...

# Extract closing prices
closes = df["Close"]
```

#### A.2 FRED Data via pandas-datareader

```python
from pandas_datareader import data as pdr

# Fetch unemployment rate
unemployment = pdr.DataReader("UNRATE", "fred", start="2023-01-01", end="2025-11-03")

# Returns DataFrame:
#             UNRATE
# 2023-01-01     3.5
# 2023-02-01     3.6
# ...

# Available series:
# - UNRATE: Unemployment Rate
# - DFF: Federal Funds Effective Rate (daily)
# - FEDFUNDS: Federal Funds Rate (monthly)
# - DGS10: 10-Year Treasury Constant Maturity Rate
# - DGS2: 2-Year Treasury Constant Maturity Rate
```

#### A.3 CoinGecko Stablecoin Supply

```python
import requests
import pandas as pd

url = "https://api.coingecko.com/api/v3/coins/tether/market_chart/range"
params = {
    "vs_currency": "usd",
    "from": int(pd.Timestamp("2023-11-01", tz="UTC").timestamp()),
    "to": int(pd.Timestamp("2025-11-03", tz="UTC").timestamp()),
}
response = requests.get(url, params=params, timeout=30)
response.raise_for_status()
data = response.json()

prices = pd.DataFrame(data["prices"], columns=["timestamp_ms", "price_usd"])
market_caps = pd.DataFrame(data["market_caps"], columns=["timestamp_ms", "market_cap_usd"])
stablecoin_supply = (
    market_caps.merge(prices, on="timestamp_ms")
    .assign(supply=lambda df: df["market_cap_usd"] / df["price_usd"].replace({0: pd.NA}))
    .dropna(subset=["supply"])
)
stablecoin_supply["date"] = pd.to_datetime(stablecoin_supply["timestamp_ms"], unit="ms")
```

### Appendix B: Correlation Interpretation Guide

| Correlation | Interpretation | Action |
|-------------|----------------|--------|
| **+0.7 to +1.0** | Strong positive | STX/BTC moves with indicator |
| **+0.3 to +0.7** | Moderate positive | Partial co-movement |
| **-0.3 to +0.3** | Weak/None | Little to no relationship |
| **-0.7 to -0.3** | Moderate negative | Inverse relationship |
| **-1.0 to -0.7** | Strong negative | STX/BTC moves opposite to indicator |

**Important caveats**:
- Correlation ≠ causation
- Spurious correlations common in financial data
- Use domain knowledge to validate relationships
- Consider lag effects (correlation may peak at non-zero lag)

### Appendix C: FRED Series Reference

| Series ID | Name | Frequency | Start Year |
|-----------|------|-----------|------------|
| **UNRATE** | Unemployment Rate | Monthly | 1948 |
| **DFF** | Federal Funds Effective Rate | Daily | 1954 |
| **FEDFUNDS** | Federal Funds Rate | Monthly | 1954 |
| **DGS10** | 10-Year Treasury Constant Maturity | Daily | 1962 |
| **DGS2** | 2-Year Treasury Constant Maturity | Daily | 1976 |
| **T10Y2Y** | 10Y-2Y Treasury Spread | Daily | 1976 |
| **DEXUSEU** | US/Euro Exchange Rate | Daily | 1999 |
| **CPIAUCSL** | Consumer Price Index (CPI) | Monthly | 1947 |

Full catalog: https://fred.stlouisfed.org/

### Appendix D: Expected File Structure After Implementation

```
stx-labs/.conductor/kuwait/
├── src/
│   ├── config.py
│   ├── http_utils.py
│   ├── cache_utils.py
│   ├── prices.py
│   ├── macro_data.py          # ← NEW
│   ├── signal21.py
│   ├── hiro.py
│   ├── fees.py
│   ├── panel_builder.py
│   └── scenarios.py
├── tests/
│   ├── test_caching.py
│   ├── test_http_utils.py
│   ├── test_prices.py
│   ├── test_macro_data.py     # ← NEW
│   ├── test_panel_builder.py
│   └── test_scenarios.py
├── notebooks/
│   ├── stx_pox_flywheel.ipynb
│   └── stx_btc_macro_correlations.ipynb  # ← NEW
├── data/
│   ├── raw/                   # JSON cache
│   └── cache/
│       ├── prices/
│       ├── signal21/
│       ├── hiro/
│       └── macro/             # ← NEW
│           ├── sp500_*.parquet
│           ├── unemployment_*.parquet
│           ├── rates_*.parquet
│           ├── vix_*.parquet
│           ├── stablecoins_*.parquet
│           └── additional_*.parquet
├── out/
│   ├── stx_btc_macro_panel.parquet         # ← NEW
│   ├── stx_btc_correlations.csv            # ← NEW
│   ├── usdt_btc_leadlag_analysis.csv       # ← NEW
│   ├── stablecoin_regime_statistics.csv    # ← NEW
│   └── stx_btc_macro_dashboard.html        # ← NEW
├── docs/
│   ├── macro_analysis_research_report.md   # ← THIS FILE
│   └── macro_findings.md                   # ← NEW (Phase 4)
├── requirements.txt           # ← UPDATED
└── Makefile                   # ← UPDATED
```

---

## 10. Next Steps & Recommendations

### 10.1 Immediate Actions

1. **Review this report** and confirm approach aligns with research objectives
2. **Prioritize indicators** - Which are most critical? (Recommend: S&P 500, Tether/USDC, interest rates)
3. **Decide on implementation pace**:
   - **Fast track** (4-6 hours): Implement core functionality, skip advanced analysis
   - **Comprehensive** (8-10 hours): Full implementation with all visualizations and regime detection
4. **Set up development branch** (already done: `stx-btc-macro-analysis`)

### 10.2 Open Questions for User

1. **Hypothesis prioritization**: Is the Tether minting hypothesis the #1 priority, or should we give equal weight to all indicators?

2. **Analysis depth**: Do you want:
   - **Exploratory** - Just visualizations and basic correlations
   - **Analytical** - Include lead/lag analysis and regime detection
   - **Statistical** - Add Granger causality tests, multivariate regression

3. **Time horizon**: Stick with 2 years, or extend to 3-5 years if data available?

4. **Output format**: Are interactive Plotly dashboards sufficient, or do you need static PNGs for presentations?

5. **Future enhancements**: Interest in paid data sources (Glassnode, CryptoQuant) if free sources prove insufficient?

### 10.3 Long-Term Opportunities

**Phase 2 enhancements** (if Phase 1 proves valuable):
- Granger causality testing for directional relationships
- Multivariate regression: "What % of STX/BTC variance is explained by macro factors?"
- Event study analysis: Impact of FOMC meetings, halving, major hacks
- Machine learning: Predict STX/BTC direction using macro features

**Phase 3 advanced features**:
- Real-time monitoring dashboard with alerts
- Automated reports on regime changes
- Integration with PoX yield analysis (connect macro → BTC bids → stacker APY)

---

## Summary

This research effort has identified **12 high-quality, free data sources** across traditional finance, macroeconomics, and crypto markets that can be integrated into the existing Stacks PoX analysis codebase with **minimal technical friction**.

**Key strengths of this approach**:
- Zero API authentication required for primary sources
- Only 2 new dependencies (both production-grade)
- Perfect architectural fit with existing caching and error handling
- Estimated 5-8 hours for complete implementation and testing
- Directly testable hypothesis (Tether minting → BTC price)

**Next step**: Review this report and confirm priorities, then proceed with Phase 1 implementation (create `src/macro_data.py` and test suite).

---

**Report prepared by**: Claude (Kuwait Workspace)
**Date**: 2025-11-03
**Workspace**: `/Users/alexanderhuth/Code/stx-labs/.conductor/kuwait`
**Branch**: `stx-btc-macro-analysis`
