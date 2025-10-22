"""Price helpers for combining price series with caching and fallbacks."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import warnings

import pandas as pd

from . import config as cfg
from .http_utils import RequestOptions, build_session, cached_json_request
from .signal21 import fetch_price_series as fetch_price_series_signal21


COINGECKO_IDS = {
    "STX-USD": ("stacks", "usd"),
    "BTC-USD": ("bitcoin", "usd"),
}

PRICE_CACHE_DIR = cfg.CACHE_DIR / "prices"
PRICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_COINGECKO_SESSION = build_session({"Accept": "application/json", "User-Agent": "stx-labs-notebook/1.0"})


def _cache_path(symbol: str) -> Path:
    sanitized = symbol.lower().replace("/", "-").replace(" ", "-").replace("-", "_")
    return PRICE_CACHE_DIR / f"{sanitized}.parquet"


def _load_cached(symbol: str) -> pd.DataFrame:
    path = _cache_path(symbol)
    if not path.exists():
        return pd.DataFrame(columns=["ts", "px"])
    df = pd.read_parquet(path)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def _store_cache(symbol: str, df: pd.DataFrame) -> None:
    path = _cache_path(symbol)
    df.sort_values("ts").to_parquet(path, index=False)


def _cache_covers(df: pd.DataFrame, start: datetime, end: datetime) -> bool:
    if df.empty:
        return False
    return df["ts"].min() <= start and df["ts"].max() >= end


def _fetch_prices_coingecko(symbol: str, start: datetime, end: datetime, *, force_refresh: bool) -> pd.DataFrame:
    if symbol not in COINGECKO_IDS:
        raise ValueError(f"CoinGecko mapping not defined for {symbol}")
    coin_id, vs_currency = COINGECKO_IDS[symbol]
    url = f"{cfg.COINGECKO_BASE}/coins/{coin_id}/market_chart/range"
    params = {
        "vs_currency": vs_currency,
        "from": int(start.timestamp()),
        "to": int(end.timestamp()),
    }
    payload = cached_json_request(
        RequestOptions(
            prefix=f"coingecko_{coin_id}_{vs_currency}",
            session=_COINGECKO_SESSION,
            method="GET",
            url=url,
            params=params,
            force_refresh=force_refresh,
            ttl_seconds=6 * 3600,
        )
    )
    prices = payload.get("prices", [])
    if not prices:
        return pd.DataFrame(columns=["ts", "px"])
    df = pd.DataFrame(prices, columns=["ts_ms", "px"])
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df = df[["ts", "px"]]
    return df


def _fetch_prices_fallback(symbol: str, start: datetime, end: datetime, *, frequency: str, force_refresh: bool) -> pd.DataFrame:
    return fetch_price_series_signal21(
        symbol,
        start,
        end,
        frequency=frequency,
        force_refresh=force_refresh,
    )


def _ensure_price_series(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    frequency: str,
    force_refresh: bool,
) -> pd.DataFrame:
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)

    cache_df = pd.DataFrame(columns=["ts", "px"])
    if not force_refresh:
        cache_df = _load_cached(symbol)

    need_fetch = force_refresh or not _cache_covers(cache_df, start, end)
    if need_fetch:
        try:
            fresh_df = _fetch_prices_coingecko(symbol, start, end, force_refresh=force_refresh)
        except Exception as exc:  # broad to fall back gracefully
            warnings.warn(
                f"CoinGecko failed for {symbol}: {exc}. Falling back to Signal21.",
                RuntimeWarning,
            )
            fresh_df = _fetch_prices_fallback(symbol, start, end, frequency=frequency, force_refresh=force_refresh)

        if fresh_df.empty:
            warnings.warn(
                f"No price data retrieved for {symbol} between {start} and {end}.",
                RuntimeWarning,
            )
        else:
            cache_df = (
                pd.concat([cache_df, fresh_df], ignore_index=True)
                .drop_duplicates(subset=["ts"])  # latest wins
                .sort_values("ts")
            )
            _store_cache(symbol, cache_df)

    if cache_df.empty:
        return cache_df

    mask = (cache_df["ts"] >= start) & (cache_df["ts"] <= end)
    subset = cache_df.loc[mask].copy()
    if subset.empty:
        return subset
    return (
        subset.set_index("ts")
        .resample(frequency)
        .mean()
        .interpolate(method="time")
        .rename_axis("ts")
        .reset_index()
    )


def fetch_price_series(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    frequency: str = "1h",
    force_refresh: bool = False,
) -> pd.DataFrame:
    return _ensure_price_series(
        symbol,
        start,
        end,
        frequency=frequency,
        force_refresh=force_refresh,
    )


def cached_price_series(symbol: str) -> pd.DataFrame:
    """Return the currently cached raw price series for a symbol."""
    df = _load_cached(symbol)
    return df.copy()


def load_price_panel(
    start: datetime,
    end: datetime,
    *,
    frequency: str = "1h",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Return merged STX-USD, BTC-USD, and STX/BTC hourly data."""
    stx = fetch_price_series("STX-USD", start, end, frequency=frequency, force_refresh=force_refresh)
    btc = fetch_price_series("BTC-USD", start, end, frequency=frequency, force_refresh=force_refresh)

    df = (
        stx.rename(columns={"px": "stx_usd"})
        .merge(btc.rename(columns={"px": "btc_usd"}), on="ts", how="outer")
        .sort_values("ts")
    )
    df["stx_usd"] = df["stx_usd"].astype(float)
    df["btc_usd"] = df["btc_usd"].astype(float)
    df["stx_usd"] = df["stx_usd"].interpolate(method="time")
    df["btc_usd"] = df["btc_usd"].interpolate(method="time")
    df["stx_btc"] = df["stx_usd"] / df["btc_usd"]
    return df
