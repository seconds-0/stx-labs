"""Utilities for fetching macroeconomic indicators with caching."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
import logging

import pandas as pd
import yfinance as yf
from pandas_datareader import data as pdr

from .cache_utils import read_parquet, write_parquet
from .config import CACHE_DIR
from .http_utils import RequestOptions, build_session, cached_json_request

MACRO_CACHE_DIR = CACHE_DIR / "macro"
MACRO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_COINGECKO_SESSION = build_session(
    {"Accept": "application/json", "User-Agent": "stx-labs-macro/1.0"}
)

LOGGER = logging.getLogger(__name__)

def _cache_path(slug: str, start_date: str, end_date: str) -> Path:
    return MACRO_CACHE_DIR / f"{slug}_{start_date}_{end_date}.parquet"


def _load_cached_frame(path: Path) -> pd.DataFrame | None:
    cached = read_parquet(path)
    if cached is None or cached.empty:
        return None
    frame = cached.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    return frame


def _store_frame(path: Path, frame: pd.DataFrame) -> None:
    normalised = frame.copy()
    normalised["date"] = pd.to_datetime(normalised["date"]).dt.date
    write_parquet(path, normalised)


def _history_to_frame(history: pd.DataFrame, source: str, alias: str) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame(columns=["date", alias])
    frame = history.reset_index()
    frame["date"] = pd.to_datetime(frame["Date"]).dt.date
    renamed = frame.rename(columns={source: alias})
    return renamed[["date", alias]]


def fetch_sp500_data(
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Return S&P 500 closing levels and daily percent change."""
    cache_file = _cache_path("sp500", start_date, end_date)
    if not force_refresh:
        cached = _load_cached_frame(cache_file)
        if cached is not None:
            return cached

    history = yf.Ticker("^GSPC").history(
        start=start_date,
        end=end_date,
        interval="1d",
    )
    closes = _history_to_frame(history, "Close", "sp500_close")
    if closes.empty:
        result = pd.DataFrame(columns=["date", "sp500_close", "sp500_pct_change"])
    else:
        result = closes.copy()
        result["sp500_pct_change"] = result["sp500_close"].pct_change() * 100

    _store_frame(cache_file, result)
    return result


def fetch_unemployment_data(
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Return US unemployment rate from FRED."""
    cache_file = _cache_path("unemployment", start_date, end_date)
    if not force_refresh:
        cached = _load_cached_frame(cache_file)
        if cached is not None:
            return cached

    df = (
        pdr.DataReader("UNRATE", "fred", start=start_date, end=end_date)
        .rename_axis("date")
        .reset_index()
        .rename(columns={"UNRATE": "unemployment_rate"})
    )
    if df.empty:
        result = pd.DataFrame(columns=["date", "unemployment_rate"])
    else:
        df["date"] = pd.to_datetime(df["date"]).dt.date
        result = df[["date", "unemployment_rate"]]

    _store_frame(cache_file, result)
    return result


def fetch_interest_rates(
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Return Federal Funds Rate and 10Y Treasury yield from FRED."""
    cache_file = _cache_path("rates", start_date, end_date)
    if not force_refresh:
        cached = _load_cached_frame(cache_file)
        if cached is not None:
            return cached

    dff = (
        pdr.DataReader("DFF", "fred", start=start_date, end=end_date)
        .rename_axis("date")
        .reset_index()
        .rename(columns={"DFF": "fed_funds_rate"})
    )
    dgs10 = (
        pdr.DataReader("DGS10", "fred", start=start_date, end=end_date)
        .rename_axis("date")
        .reset_index()
        .rename(columns={"DGS10": "treasury_10y"})
    )

    for frame in (dff, dgs10):
        if not frame.empty:
            frame["date"] = pd.to_datetime(frame["date"]).dt.date

    result = (
        dff[["date", "fed_funds_rate"]]
        .merge(dgs10[["date", "treasury_10y"]], on="date", how="outer")
        .sort_values("date")
    )

    _store_frame(cache_file, result)
    return result


def fetch_volatility_data(
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Return VIX closing levels."""
    cache_file = _cache_path("vix", start_date, end_date)
    if not force_refresh:
        cached = _load_cached_frame(cache_file)
        if cached is not None:
            return cached

    history = yf.Ticker("^VIX").history(
        start=start_date,
        end=end_date,
        interval="1d",
    )
    frame = _history_to_frame(history, "Close", "vix_close")

    _store_frame(cache_file, frame)
    return frame


def _coingecko_market_chart_range(
    coin_id: str,
    start_ts: int,
    end_ts: int,
) -> dict:
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

    try:
        payload = _coingecko_market_chart_range(coin_id, start_ts, end_ts)
    except Exception as exc:  # pragma: no cover - network issues
        LOGGER.warning("Failed to fetch %s supply from CoinGecko: %s", coin_id, exc)
        return pd.DataFrame(columns=["date", column_name])
    market_caps = pd.DataFrame(
        payload.get("market_caps", []), columns=["timestamp_ms", "market_cap_usd"]
    )
    prices = pd.DataFrame(
        payload.get("prices", []), columns=["timestamp_ms", "price_usd"]
    )

    if market_caps.empty or prices.empty:
        return pd.DataFrame(columns=["date", column_name])

    frame = market_caps.merge(prices, on="timestamp_ms", how="inner")
    frame[column_name] = frame["market_cap_usd"] / frame["price_usd"].replace(
        {0: pd.NA}
    )
    frame = frame.dropna(subset=[column_name])
    frame["date"] = pd.to_datetime(frame["timestamp_ms"], unit="ms").dt.date
    daily = (
        frame.sort_values("timestamp_ms")
        .groupby("date", as_index=False)[column_name]
        .last()
    )
    return daily.sort_values("date")


def fetch_stablecoin_supply(
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Return USDT and USDC supply and daily deltas."""
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
    """Return DXY and gold futures closing prices."""
    cache_file = _cache_path("additional", start_date, end_date)
    if not force_refresh:
        cached = _load_cached_frame(cache_file)
        if cached is not None:
            return cached

    dxy_history = yf.Ticker("DX=F").history(
        start=start_date,
        end=end_date,
        interval="1d",
    )
    gold_history = yf.Ticker("GC=F").history(
        start=start_date,
        end=end_date,
        interval="1d",
    )

    dxy = _history_to_frame(dxy_history, "Close", "dxy_close")
    gold = _history_to_frame(gold_history, "Close", "gold_close")

    result = dxy.merge(gold, on="date", how="outer").sort_values("date")

    _store_frame(cache_file, result)
    return result


def load_macro_panel(
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Return merged macroeconomic indicators aligned on date."""
    frames: Iterable[pd.DataFrame] = [
        fetch_sp500_data(start_date, end_date, force_refresh),
        fetch_unemployment_data(start_date, end_date, force_refresh),
        fetch_interest_rates(start_date, end_date, force_refresh),
        fetch_volatility_data(start_date, end_date, force_refresh),
        fetch_stablecoin_supply(start_date, end_date, force_refresh),
        fetch_additional_indicators(start_date, end_date, force_refresh),
    ]

    panel = pd.DataFrame(columns=["date"])
    for frame in frames:
        if frame.empty:
            continue
        if panel.empty:
            panel = frame
            continue
        panel = panel.merge(frame, on="date", how="outer")

    return panel.sort_values("date").reset_index(drop=True)
