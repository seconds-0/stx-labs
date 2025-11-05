"""Hiro Stacks API helper functions."""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from . import config as cfg
from .cache_utils import read_parquet, write_parquet
from .config import HIRO_API_KEY_ENV, HIRO_BASE
from .http_utils import RequestOptions, build_session, cached_json_request

BURNCHAIN_REWARDS_ENDPOINT = f"{HIRO_BASE}/extended/v1/burnchain/rewards"
BLOCK_BY_BURN_HEIGHT_ENDPOINT = f"{HIRO_BASE}/extended/v1/block/by_burn_block_height"
POX_CYCLES_ENDPOINT = f"{HIRO_BASE}/extended/v2/pox/cycles"
TX_BY_BLOCK_HEIGHT_ENDPOINT = f"{HIRO_BASE}/extended/v1/tx/block_height"
TX_LIST_ENDPOINT = f"{HIRO_BASE}/extended/v1/tx"

HIRO_CACHE_DIR = cfg.CACHE_DIR / "hiro"
HIRO_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _rewards_cache_path(start_height: int | None, end_height: int | None) -> Path:
    label = "all"
    if start_height is not None or end_height is not None:
        label = f"{start_height or 'min'}_{end_height or 'max'}"
    return HIRO_CACHE_DIR / f"rewards_{label}.parquet"


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
) -> dict[str, Any]:
    """Fetch a page of burnchain rewards."""
    params: dict[str, Any] = {"limit": limit, "offset": offset}
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
) -> Iterator[dict[str, Any]]:
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
        yield from results
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
    cache_path = _rewards_cache_path(start_height, end_height)
    if not force_refresh:
        cached = read_parquet(cache_path)
        if cached is not None:
            cached["burn_block_height"] = cached["burn_block_height"].astype(int)
            cached["reward_amount_sats_sum"] = cached["reward_amount_sats_sum"].astype(
                int
            )
            cached["reward_recipients"] = cached["reward_recipients"].astype(int)
            return cached.sort_values("burn_block_height")

    records: dict[int, dict[str, Any]] = {}
    for row in iterate_burnchain_rewards(
        start_height=start_height,
        end_height=end_height,
        force_refresh=force_refresh,
    ):
        burn_height = row["burn_block_height"]
        reward_amount = int(row["reward_amount"])
        record = records.setdefault(
            burn_height,
            {
                "burn_block_height": burn_height,
                "reward_amount_sats_sum": 0,
                "reward_recipients": 0,
            },
        )
        record["reward_amount_sats_sum"] += reward_amount
        record["reward_recipients"] += 1
    if not records:
        df = pd.DataFrame(
            columns=["burn_block_height", "reward_amount_sats_sum", "reward_recipients"]
        )
    else:
        df = pd.DataFrame(
            sorted(records.values(), key=lambda r: r["burn_block_height"])
        )
    write_parquet(cache_path, df)
    return df


def fetch_block_by_burn_height(
    burn_height: int,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
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


def fetch_pox_cycles(
    *, limit: int = 20, offset: int = 0, force_refresh: bool = False
) -> dict[str, Any]:
    params = {"limit": min(limit, 20), "offset": offset}
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
    total = None
    frames: list[pd.DataFrame] = []
    while True:
        payload = fetch_pox_cycles(offset=offset, force_refresh=force_refresh)
        results = payload.get("results", [])
        if not results:
            break
        frames.append(pd.DataFrame(results))
        total = payload.get("total")
        offset += len(results)
        if total is not None and offset >= total:
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
    requested = {int(h) for h in burn_heights}
    if not requested:
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

    existing = read_parquet(ANCHOR_CACHE_PATH)
    if existing is None or force_refresh:
        existing = pd.DataFrame(
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
    else:
        existing["burn_block_height"] = existing["burn_block_height"].astype(int)

    cached_heights = set(existing["burn_block_height"].tolist())
    missing = sorted(requested - cached_heights)

    if missing:
        records: list[dict[str, Any]] = []
        for height in missing:
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
        if records:
            new_df = pd.DataFrame(records)
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined = combined.drop_duplicates(
                subset=["burn_block_height"], keep="last"
            )
            write_parquet(ANCHOR_CACHE_PATH, combined)
            existing = combined

    result = existing[existing["burn_block_height"].isin(requested)].copy()
    return result.sort_values("burn_block_height")


def fetch_tx_by_block_height(
    block_height: int,
    *,
    limit: int = 200,
    offset: int = 0,
    force_refresh: bool = False,
) -> dict[str, Any]:
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


def fetch_transactions_page(
    *,
    limit: int = 200,
    offset: int = 0,
    include_unanchored: bool = False,
    force_refresh: bool = False,
    ttl_seconds: float | None = 600,
    start_time: int | None = None,
    end_time: int | None = None,
) -> dict[str, Any]:
    """Fetch a page of transactions ordered by newest first."""
    params: dict[str, Any] = {"limit": min(limit, 200), "offset": offset}
    if not include_unanchored:
        params["unanchored"] = "false"
    if start_time is not None:
        params["from"] = start_time
    if end_time is not None:
        params["to"] = end_time
    return cached_json_request(
        RequestOptions(
            prefix="hiro_tx_pages",
            session=_hiro_session(),
            method="GET",
            url=TX_LIST_ENDPOINT,
            params=params,
            force_refresh=force_refresh,
            ttl_seconds=ttl_seconds,
        )
    )


ANCHOR_CACHE_PATH = HIRO_CACHE_DIR / "anchor_metadata.parquet"
