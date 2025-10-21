"""Hiro Stacks API helper functions."""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any, Dict, Iterator

import pandas as pd
import requests

from .config import HIRO_BASE, HIRO_API_KEY_ENV
from .http_utils import RequestOptions, build_session, cached_json_request

BURNCHAIN_REWARDS_ENDPOINT = f"{HIRO_BASE}/extended/v1/burnchain/rewards"
BLOCK_BY_BURN_HEIGHT_ENDPOINT = f"{HIRO_BASE}/extended/v1/block/by_burn_block_height"
POX_CYCLES_ENDPOINT = f"{HIRO_BASE}/extended/v2/pox/cycles"
TX_BY_BLOCK_HEIGHT_ENDPOINT = f"{HIRO_BASE}/extended/v1/tx/block_height"


def _hiro_session() -> requests.Session:
    headers = {"User-Agent": "stx-labs-notebook/1.0"}
    api_key = _get_api_key()
    if api_key:
        headers["X-API-Key"] = api_key
    return build_session(headers)


def _get_api_key() -> str | None:
    return os.getenv(HIRO_API_KEY_ENV)


def fetch_burnchain_rewards(
    *,
    limit: int = 500,
    offset: int = 0,
    start_height: int | None = None,
    end_height: int | None = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Fetch a page of burnchain rewards."""
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if start_height is not None:
        params["burn_block_height_gte"] = start_height
    if end_height is not None:
        params["burn_block_height_lte"] = end_height
    return cached_json_request(
        RequestOptions(
            prefix="hiro_rewards",
            session=_hiro_session(),
            method="GET",
            url=BURNCHAIN_REWARDS_ENDPOINT,
            params=params,
            force_refresh=force_refresh,
        )
    )


def iterate_burnchain_rewards(
    *,
    start_height: int | None = None,
    end_height: int | None = None,
    page_limit: int = 500,
    force_refresh: bool = False,
) -> Iterator[Dict[str, Any]]:
    offset = 0
    while True:
        payload = fetch_burnchain_rewards(
            limit=page_limit,
            offset=offset,
            start_height=start_height,
            end_height=end_height,
            force_refresh=force_refresh,
        )
        results = payload.get("results", [])
        if not results:
            break
        for item in results:
            yield item
        offset += page_limit
        if len(results) < page_limit:
            break


def aggregate_rewards_by_burn_block(
    *,
    start_height: int | None = None,
    end_height: int | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Aggregate sats committed per burn block height."""
    records: Dict[int, Dict[str, Any]] = {}
    for row in iterate_burnchain_rewards(
        start_height=start_height,
        end_height=end_height,
        force_refresh=force_refresh,
    ):
        burn_height = row["burn_block_height"]
        reward_amount = int(row["reward_amount"])
        record = records.setdefault(
            burn_height,
            {"burn_block_height": burn_height, "reward_amount_sats_sum": 0, "reward_recipients": 0},
        )
        record["reward_amount_sats_sum"] += reward_amount
        record["reward_recipients"] += 1
    if not records:
        return pd.DataFrame(columns=["burn_block_height", "reward_amount_sats_sum", "reward_recipients"])
    df = pd.DataFrame(sorted(records.values(), key=lambda r: r["burn_block_height"]))
    return df


def fetch_block_by_burn_height(
    burn_height: int,
    *,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    url = f"{BLOCK_BY_BURN_HEIGHT_ENDPOINT}/{burn_height}"
    return cached_json_request(
        RequestOptions(
            prefix="hiro_block_burn",
            session=_hiro_session(),
            method="GET",
            url=url,
            force_refresh=force_refresh,
        )
    )


def fetch_pox_cycles(*, limit: int = 200, offset: int = 0, force_refresh: bool = False) -> Dict[str, Any]:
    params = {"limit": limit, "offset": offset}
    return cached_json_request(
        RequestOptions(
            prefix="hiro_pox_cycles",
            session=_hiro_session(),
            method="GET",
            url=POX_CYCLES_ENDPOINT,
            params=params,
            force_refresh=force_refresh,
        )
    )


def list_pox_cycles(*, force_refresh: bool = False) -> pd.DataFrame:
    """Fetch the available PoX cycles into a dataframe."""
    offset = 0
    frames: list[pd.DataFrame] = []
    while True:
        payload = fetch_pox_cycles(offset=offset, force_refresh=force_refresh)
        results = payload.get("results", [])
        if not results:
            break
        frames.append(pd.DataFrame(results))
        offset += len(results)
        if len(results) < payload.get("limit", len(results)):
            break
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def collect_anchor_metadata(
    burn_heights: Iterable[int],
    *,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Fetch anchor block metadata for a set of burn heights."""
    records: list[Dict[str, Any]] = []
    for height in burn_heights:
        payload = fetch_block_by_burn_height(height, force_refresh=force_refresh)
        if not payload:
            continue
        records.append(
            {
                "burn_block_height": payload.get("burn_block_height"),
                "stacks_block_hash": payload.get("hash"),
                "stacks_block_height": payload.get("height"),
                "miner_txid": payload.get("miner_txid"),
                "burn_block_time_iso": payload.get("burn_block_time_iso"),
                "burn_block_time": payload.get("burn_block_time"),
                "parent_index_block_hash": payload.get("parent_index_block_hash"),
            }
        )
    if not records:
        return pd.DataFrame(
            columns=[
                "burn_block_height",
                "stacks_block_hash",
                "stacks_block_height",
                "miner_txid",
                "burn_block_time_iso",
                "burn_block_time",
                "parent_index_block_hash",
            ]
        )
    return pd.DataFrame(records).sort_values("burn_block_height")


def fetch_tx_by_block_height(
    block_height: int,
    *,
    limit: int = 200,
    offset: int = 0,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    url = f"{TX_BY_BLOCK_HEIGHT_ENDPOINT}/{block_height}"
    params = {"limit": limit, "offset": offset}
    return cached_json_request(
        RequestOptions(
            prefix="hiro_block_tx",
            session=_hiro_session(),
            method="GET",
            url=url,
            params=params,
            force_refresh=force_refresh,
        )
    )
