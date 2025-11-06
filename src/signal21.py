"""Signal21 API helper functions."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any
import warnings

import pandas as pd
import requests

from .config import SIGNAL21_BASE
from .http_utils import (
    RequestOptions,
    TransientHTTPError,
    build_session,
    cached_json_request,
)

PRICE_ENDPOINT = f"{SIGNAL21_BASE}/v1/price"
SQL_ENDPOINT = f"{SIGNAL21_BASE}/v1/sql-v2"

UTC = timezone.utc


def _signal21_session() -> requests.Session:
    session = build_session({"User-Agent": "stx-labs-notebook/1.0"})
    return session


MAX_CHUNK_DAYS = 30
MIN_CHUNK_DAYS = 5


def fetch_price_series(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    frequency: str = "1h",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Fetch price data for a symbol and return as dataframe indexed by timestamp."""
    frames: list[pd.DataFrame] = []
    queue: deque[tuple[datetime, datetime]] = deque(_iter_date_chunks(start, end, MAX_CHUNK_DAYS))
    session = _signal21_session()

    while queue:
        chunk_start, chunk_end = queue.pop()
        try:
            chunk_df = _fetch_price_chunk(
                symbol,
                chunk_start,
                chunk_end,
                session=session,
                force_refresh=force_refresh,
            )
        except TransientHTTPError as exc:
            span_days = (chunk_end - chunk_start).days
            if span_days <= MIN_CHUNK_DAYS:
                warnings.warn(
                    f"Signal21 price API repeatedly failed for {symbol} between "
                    f"{chunk_start.date()} and {chunk_end.date()}: {exc}. Skipping chunk.",
                    RuntimeWarning,
                )
                continue
            midpoint = chunk_start + timedelta(days=span_days // 2)
            queue.appendleft((midpoint + timedelta(days=1), chunk_end))
            queue.appendleft((chunk_start, midpoint))
            continue

        if not chunk_df.empty:
            frames.append(chunk_df)

    if not frames:
        return pd.DataFrame(columns=["ts", "px"])

    df = (
        pd.concat(frames, ignore_index=True)
            .drop_duplicates(subset=["ts"])
            .sort_values("ts")
    )
    if "price" in df.columns:
        df = df.rename(columns={"price": "px"})

    if df.empty:
        return df

    df = df.set_index("ts")
    return (
        df.resample(frequency)
        .mean()
        .interpolate(method="time")
        .rename_axis("ts")
        .reset_index()
    )


def _fetch_price_chunk(
    symbol: str,
    chunk_start: datetime,
    chunk_end: datetime,
    *,
    session: requests.Session,
    force_refresh: bool,
) -> pd.DataFrame:
    params = {
        "symbol": symbol,
        "from": chunk_start.strftime("%Y-%m-%d"),
        "to": chunk_end.strftime("%Y-%m-%d"),
    }
    payload = cached_json_request(
        RequestOptions(
            prefix="signal21_price",
            session=session,
            method="GET",
            url=PRICE_ENDPOINT,
            params=params,
            force_refresh=force_refresh,
        )
    )
    df = pd.DataFrame(payload)
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def _iter_date_chunks(
    start: datetime,
    end: datetime,
    max_days: int,
) -> list[tuple[datetime, datetime]]:
    """Initial chunking helper before adaptive retries."""
    if start > end:
        raise ValueError("start must be <= end")

    chunks: list[tuple[datetime, datetime]] = []
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=max_days - 1), end)
        chunks.append((current, chunk_end))
        if chunk_end >= end:
            break
        current = chunk_end + timedelta(days=1)
    return chunks


def run_sql_query(query: str, *, page_size: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Execute a SQL query and return the concatenated dataframe."""
    offset = 0
    frames: list[pd.DataFrame] = []
    session = _signal21_session()
    while True:
        body: dict[str, Any] = {"query": query, "offset": offset}
        payload = cached_json_request(
            RequestOptions(
                prefix="signal21_sql",
                session=session,
                method="POST",
                url=SQL_ENDPOINT,
                json_body=body,
                force_refresh=force_refresh,
            )
        )
        data = payload.get("columns") or payload.get("data", {})
        records = _columnar_to_records(data)
        if not records:
            break
        frames.append(pd.DataFrame.from_records(records))
        next_offset = payload.get("next")
        if next_offset is None:
            break
        offset = int(next_offset)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _columnar_to_records(data: dict[str, list[Any]]) -> list[dict[str, Any]]:
    if not data:
        return []
    columns = list(data.keys())
    length = len(data[columns[0]])
    return [{col: data[col][idx] for col in columns} for idx in range(length)]


def probe_schema(table: str, limit: int = 5) -> pd.DataFrame:
    """Convenience helper to inspect table schema via SELECT * LIMIT."""
    query = f"SELECT * FROM {table} LIMIT {limit};"
    return run_sql_query(query)
