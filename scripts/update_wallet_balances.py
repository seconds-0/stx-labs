#!/usr/bin/env python3
"""Refresh cached wallet balance snapshots to keep funded counts accurate."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

# Add src/ to path so we can import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from src import ops_events
from src import wallet_metrics
from src.http_utils import TransientHTTPError
from src.wallet_value import ClassificationThresholds

# Configure logging to show INFO level messages
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-days",
        type=int,
        default=120,
        help="Activity horizon (days) to consider when selecting wallets (default: 120)",
    )
    parser.add_argument(
        "--activation-days",
        type=int,
        default=120,
        help="Only refresh balances for wallets activated within this many days (default: 120)",
    )
    parser.add_argument(
        "--as-of-date",
        type=str,
        help="Override snapshot date (YYYY-MM-DD). Defaults to today (UTC).",
    )
    parser.add_argument(
        "--threshold-stx",
        type=float,
        default=ClassificationThresholds().funded_stx_min,
        help="Funded threshold in STX (default: 10)",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Force transaction history refresh before computing wallet set.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.5,
        help="Delay between balance requests in seconds (default: 0.5, conservative for 500 RPM limit)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Process addresses in batches of this size (default: 100)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=20,
        help="Number of concurrent requests per batch (default: 20)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot_date = (
        datetime.strptime(args.as_of_date, "%Y-%m-%d").date()
        if args.as_of_date
        else datetime.now(UTC).date()
    )

    try:
        wallet_metrics.ensure_transaction_history(
            max_days=args.max_days,
            force_refresh=args.force_refresh,
        )
    except TransientHTTPError as e:
        if "429" in str(e):
            print(
                "Warning: Rate limited while syncing latest transactions. "
                "Continuing with existing database state."
            )
        else:
            raise
    activity = wallet_metrics.load_recent_wallet_activity(max_days=args.max_days)
    first_seen = wallet_metrics.update_first_seen_cache(activity)
    if first_seen.empty:
        print("No wallets discovered; nothing to update.")
        return

    first_seen_df = first_seen.copy()
    first_seen_df["first_seen"] = pd.to_datetime(first_seen_df["first_seen"], utc=True)
    cutoff = datetime.now(UTC) - timedelta(days=args.activation_days)
    filtered = first_seen_df[first_seen_df["first_seen"] >= cutoff]
    addresses = filtered["address"].astype(str).tolist()
    if not addresses:
        print("No wallets within activation window; nothing to update.")
        return

    print(f"Processing {len(addresses)} wallets with delay={args.delay_seconds}s, batch_size={args.batch_size}, max_workers={args.max_workers}")

    def progress_callback(
        completed_batches: int,
        total_batches: int,
        processed_addresses: int,
        total_addresses: int,
    ) -> None:
        batches = max(total_batches, 1)
        detail = (
            f"Batch {completed_batches}/{total_batches} | "
            f"{processed_addresses}/{total_addresses} wallets"
            if total_addresses
            else "Preparing wallet set"
        )
        ops_events.emit_progress(
            stage="wallet_balances",
            current=min(completed_batches, batches),
            total=batches,
            detail=detail,
        )

    inserted = wallet_metrics.ensure_wallet_balances(
        addresses,
        as_of_date=snapshot_date,
        funded_threshold_stx=args.threshold_stx,
        delay_seconds=args.delay_seconds,
        batch_size=args.batch_size,
        max_workers=args.max_workers,
        progress_callback=progress_callback,
    )
    
    print(
        f"Inserted {inserted} balance snapshots for {snapshot_date}."
    )
    
    # The function is resumable - failed addresses aren't inserted, so re-running
    # will retry only the missing ones
    if inserted < len(addresses):
        print(
            f"Note: {len(addresses) - inserted} wallets failed to fetch (likely rate limited). "
            f"Re-run this script to retry failed addresses."
        )


if __name__ == "__main__":
    main()
