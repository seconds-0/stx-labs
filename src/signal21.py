"""Signal21 API helper functions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import requests

from .config import SIGNAL21_BASE
from .http_utils import RequestOptions, build_session, cached_json_request

PRICE_ENDPOINT = f"{SIGNAL21_BASE}/v1/price"
SQL_ENDPOINT = f"{SIGNAL21_BASE}/v1/sql-v2"


def _signal21_session() -> requests.Session:
    session = build_session({"User-Agent": "stx-labs-notebook/1.0"})
    return session


def fetch_price_series(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    frequency: str = "1h",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Fetch price data for a symbol and return as dataframe indexed by timestamp."""
    params = {
        "symbol": symbol,
        "from": start.strftime("%Y-%m-%d"),
        "to": end.strftime("%Y-%m-%d"),
    }
    payload = cached_json_request(
        RequestOptions(
            prefix="signal21_price",
            session=_signal21_session(),
            method="GET",
            url=PRICE_ENDPOINT,
            params=params,
            force_refresh=force_refresh,
        )
    )
    df = pd.DataFrame(payload)
    if df.empty:
        df = pd.DataFrame(columns=["ts", "price"])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts").sort_index()
    if "price" in df:
        df = df.rename(columns={"price": "px"})
    return (
        df.resample(frequency)
        .mean()
        .interpolate(method="time")
        .rename_axis("ts")
        .reset_index()
    )


def run_sql_query(query: str, *, page_size: int = 50_000, force_refresh: bool = False) -> pd.DataFrame:
    """Execute a SQL query and return the concatenated dataframe."""
    offset = 0
    frames: list[pd.DataFrame] = []
    session = _signal21_session()
    while True:
        body = {"query": query, "offset": offset, "limit": page_size}
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
        data = payload.get("data", {})
        records = _columnar_to_records(data)
        if not records:
            break
        frames.append(pd.DataFrame.from_records(records))
        if len(records) < page_size:
            break
        offset += page_size
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
