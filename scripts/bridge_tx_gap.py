#!/usr/bin/env python3
"""Bridge a large tx-history gap by paginating Hiro backwards from now.

The incremental `_sync_latest_transactions` in wallet_metrics bails as soon as
a fetched page's oldest tx is <= the DB's current max block_time. That works
for daily catch-up (gap < page width) but cannot bridge multi-month gaps.
This script paginates Hiro's `/extended/v2/transactions` endpoint from
`end_time=now()` straight backwards, inserting every canonical success tx,
until it reaches `--until-timestamp` (Unix seconds).

Safe to interrupt and resume: picks up from the newest gap boundary each run.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.hiro import fetch_transactions_page
from src.wallet_metrics import (
    TRANSACTION_PAGE_LIMIT,
    _connect,
    _ensure_schema,
    _insert_transactions,
    _page_cursor,
    _prepare_transactions,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--until-timestamp",
        type=int,
        required=True,
        help="Stop once a page's oldest tx is at/before this Unix timestamp.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=30000,
        help="Hard cap on pages (default 30k, ~4h of Stacks history at 10min blocks).",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=50,
        help="Print a progress line every N pages.",
    )
    args = parser.parse_args()

    target_ts = args.until_timestamp
    target_dt = datetime.fromtimestamp(target_ts, UTC)
    print(f"Bridging gap from now back to {target_dt.isoformat()}", flush=True)

    cursor = int(time.time())
    pages = 0
    inserted_total = 0
    started = time.time()
    last_print = started

    with _connect() as conn:
        _ensure_schema(conn)

        while pages < args.max_pages:
            pages += 1
            payload = fetch_transactions_page(
                limit=TRANSACTION_PAGE_LIMIT,
                offset=0,
                include_unanchored=False,
                force_refresh=False,
                ttl_seconds=1800,
                end_time=cursor,
            )
            results = payload.get("results", [])
            if not results:
                print(f"[page {pages}] empty results, stopping.", flush=True)
                break

            frame = _prepare_transactions(results)
            if not frame.empty:
                inserted = _insert_transactions(conn, frame)
                inserted_total += inserted

            next_cursor = _page_cursor(results)
            if next_cursor is None or next_cursor >= cursor:
                print(
                    f"[page {pages}] cursor stalled "
                    f"({next_cursor} >= {cursor}), stopping.",
                    flush=True,
                )
                break

            if next_cursor <= target_ts:
                reached = datetime.fromtimestamp(next_cursor, UTC).isoformat()
                print(
                    f"[page {pages}] reached target ({reached} <= target), stopping.",
                    flush=True,
                )
                break

            cursor = next_cursor

            now = time.time()
            if pages % args.progress_every == 0 or (now - last_print) > 30:
                cursor_dt = datetime.fromtimestamp(cursor, UTC)
                elapsed = now - started
                rate = pages / elapsed if elapsed > 0 else 0
                print(
                    f"[page {pages}] cursor={cursor_dt.isoformat()} "
                    f"inserted_total={inserted_total} "
                    f"elapsed={elapsed:.0f}s rate={rate:.1f} pg/s",
                    flush=True,
                )
                last_print = now

    elapsed = time.time() - started
    print(
        f"Done: {pages} pages, {inserted_total} rows inserted in {elapsed:.0f}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
