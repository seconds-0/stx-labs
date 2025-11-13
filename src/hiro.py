"""Hiro Stacks API helper functions."""

from __future__ import annotations

import os
import warnings
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Dict, Iterator

import pandas as pd
import requests

from . import config as cfg
from .cache_utils import read_parquet, write_parquet
from .config import HIRO_BASE, HIRO_API_KEY_ENV
from .http_utils import (
    RequestOptions,
    TransientHTTPError,
    build_session,
    cached_json_request,
)

BURNCHAIN_REWARDS_ENDPOINT = f"{HIRO_BASE}/extended/v1/burnchain/rewards"
BLOCK_BY_BURN_HEIGHT_ENDPOINT = f"{HIRO_BASE}/extended/v1/block/by_burn_block_height"
BLOCK_BY_HEIGHT_ENDPOINT = f"{HIRO_BASE}/extended/v1/block/by_height"
POX_CYCLES_ENDPOINT = f"{HIRO_BASE}/extended/v2/pox/cycles"
TX_BY_BLOCK_HEIGHT_ENDPOINT = f"{HIRO_BASE}/extended/v1/tx/block_height"
TRANSACTION_HISTORY_ENDPOINT = f"{HIRO_BASE}/extended/v1/tx"
ADDRESS_BALANCES_ENDPOINT = f"{HIRO_BASE}/extended/v1/address"

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


def fetch_transactions_page(
    *,
    limit: int = 50,
    offset: int = 0,
    include_unanchored: bool = False,
    start_time: int | None = None,
    end_time: int | None = None,
    sort_by: str | None = None,
    force_refresh: bool = False,
    ttl_seconds: int = 900,
) -> Dict[str, Any]:
    """Fetch a page of canonical transactions with optional burn time filtering."""
    params: Dict[str, Any] = {
        "limit": min(limit, 50),
        "offset": offset,
        "unanchored": str(include_unanchored).lower(),
        "order": "desc",
    }
    if start_time is not None:
        params["start_time"] = start_time
    if end_time is not None:
        params["end_time"] = end_time
    effective_sort = sort_by
    if effective_sort is None and (start_time is not None or end_time is not None):
        effective_sort = "burn_block_time"
    if effective_sort is not None:
        params["sort_by"] = effective_sort

    return cached_json_request(
        RequestOptions(
            prefix="hiro_transactions",
            session=_hiro_session(),
            method="GET",
            url=TRANSACTION_HISTORY_ENDPOINT,
            params=params,
            ttl_seconds=ttl_seconds,
            force_refresh=force_refresh,
        )
    )


def fetch_burnchain_rewards(
    *,
    limit: int = 250,
    offset: int = 0,
    start_height: int | None = None,
    end_height: int | None = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Fetch a page of burnchain rewards."""
    params: Dict[str, Any] = {"limit": min(limit, 250), "offset": offset}
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
    page_size = min(page_limit, 250)
    reached_lower_bound = False
    while True:
        payload = fetch_burnchain_rewards(
            limit=page_size,
            offset=offset,
            start_height=start_height,
            end_height=end_height,
            force_refresh=force_refresh,
        )
        results = payload.get("results", [])
        if not results:
            break
        for item in results:
            burn_height = int(item["burn_block_height"])
            if end_height is not None and burn_height > end_height:
                continue
            if start_height is not None and burn_height < start_height:
                reached_lower_bound = True
                continue
            yield item
        if reached_lower_bound:
            break
        offset += page_size
        if len(results) < page_size:
            if start_height is not None and not reached_lower_bound:
                warnings.warn(
                    (
                        "Reached end of Hiro rewards results without hitting "
                        f"requested start_height={start_height}."
                    ),
                    RuntimeWarning,
                )
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


def fetch_block_by_height(
    block_height: int,
    *,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Fetch canonical Stacks block details by Stacks block height."""
    url = f"{BLOCK_BY_HEIGHT_ENDPOINT}/{block_height}"
    return cached_json_request(
        RequestOptions(
            prefix="hiro_block_height",
            session=_hiro_session(),
            method="GET",
            url=url,
            force_refresh=force_refresh,
        )
    )


def fetch_pox_cycles(
    *, limit: int = 20, offset: int = 0, force_refresh: bool = False
) -> Dict[str, Any]:
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
        records: list[Dict[str, Any]] = []
        for height in missing:
            try:
                payload = fetch_block_by_burn_height(
                    height, force_refresh=force_refresh
                )
            except TransientHTTPError as exc:
                warnings.warn(
                    f"Hiro block lookup transient failure for burn height {height}: {exc}",
                    RuntimeWarning,
                )
                continue
            except requests.HTTPError as exc:
                response = getattr(exc, "response", None)
                status = response.status_code if response is not None else None
                if status == 404:
                    continue
                raise
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
    limit: int = 50,
    offset: int = 0,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    url = f"{TX_BY_BLOCK_HEIGHT_ENDPOINT}/{block_height}"
    params = {"limit": min(limit, 50), "offset": offset}
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


ANCHOR_CACHE_PATH = HIRO_CACHE_DIR / "anchor_metadata.parquet"


def fetch_address_balances(
    address: str, *, force_refresh: bool = False, ttl_seconds: int = 6 * 3600
) -> Dict[str, Any]:
    """Fetch current balances for a principal address (cached).

    Uses Hiro extended balances endpoint. Response typically includes an "stx"
    object with "balance" (microSTX). We cache responses for a few hours to
    avoid hammering the API when classifying many wallets.
    """
    url = f"{ADDRESS_BALANCES_ENDPOINT}/{address}/balances"
    return cached_json_request(
        RequestOptions(
            prefix="hiro_address_balances",
            session=_hiro_session(),
            method="GET",
            url=url,
            ttl_seconds=ttl_seconds,
            force_refresh=force_refresh,
        )
    )
