#!/usr/bin/env python3
"""
Quick status checker for wallet transaction backfill progress.

Usage:
    python scripts/check_backfill_status.py [--target-days 180]

Displays:
- Current row count and unique wallet count
- Date range covered (min/max block_time)
- Progress toward target date
- Estimated completion status
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add src/ to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
from src.config import CACHE_DIR


def main():
    parser = argparse.ArgumentParser(description="Check wallet backfill status")
    parser.add_argument(
        "--target-days",
        type=int,
        default=180,
        help="Target backfill days (default: 180)",
    )
    args = parser.parse_args()

    db_path = CACHE_DIR / "wallet_metrics.duckdb"
    target_date = datetime.now(timezone.utc) - timedelta(days=args.target_days)

    print("="*80)
    print("WALLET BACKFILL STATUS")
    print("="*80)

    if not db_path.exists():
        print("❌ Database does not exist yet")
        print(f"Expected location: {db_path}")
        print("\nRun 'python scripts/backfill_wallet_history.py' to start backfill")
        return 1

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        # Check if table exists
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name = 'transactions'"
        ).fetchall()

        if not tables:
            print("❌ Transactions table does not exist yet")
            print("\nRun 'python scripts/backfill_wallet_history.py' to start backfill")
            return 1

        # Get stats
        result = conn.execute(
            """
            SELECT
                COUNT(*) as row_count,
                COUNT(DISTINCT sender_address) as wallet_count,
                MIN(block_time) as min_time,
                MAX(block_time) as max_time
            FROM transactions
            """
        ).fetchone()

        if not result or result[0] == 0:
            print("❌ Database exists but is empty")
            print("\nRun 'python scripts/backfill_wallet_history.py' to start backfill")
            return 1

        row_count, wallet_count, min_time, max_time = result

        # Parse timestamps
        if isinstance(min_time, str):
            min_time = datetime.fromisoformat(min_time.replace("Z", "+00:00"))
        if isinstance(max_time, str):
            max_time = datetime.fromisoformat(max_time.replace("Z", "+00:00"))

        # Ensure timezone-aware
        if min_time and min_time.tzinfo is None:
            min_time = min_time.replace(tzinfo=timezone.utc)
        if max_time and max_time.tzinfo is None:
            max_time = max_time.replace(tzinfo=timezone.utc)

        # Display results
        print(f"Database: {db_path}")
        print(f"Size: {db_path.stat().st_size / 1024 / 1024:.1f} MB")
        print()
        print(f"Total transactions: {row_count:,}")
        print(f"Unique wallets: {wallet_count:,}")
        print()
        print(f"Earliest transaction: {min_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"Latest transaction: {max_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print()

        # Calculate coverage
        if min_time:
            now = datetime.now(timezone.utc)
            days_covered = (now - min_time).days
            progress_pct = (days_covered / args.target_days) * 100

            print(f"Target: {args.target_days} days back to {target_date.strftime('%Y-%m-%d')}")
            print(f"Coverage: {days_covered} days ({progress_pct:.1f}%)")
            print()

            if min_time <= target_date:
                print("✅ BACKFILL COMPLETE - Target date reached!")
                print()
                print("Next steps:")
                print("  • Run 'make smoke-notebook' or 'make notebook' to regenerate dashboards")
                print("  • Or run 'python scripts/build_dashboards.py' for quick update")
                return 0
            else:
                days_remaining = (min_time - target_date).days
                print(f"⏳ BACKFILL IN PROGRESS - {days_remaining} days remaining")
                print()
                print("Next steps:")
                print("  • Continue running 'python scripts/backfill_wallet_history.py'")
                print("  • Or let the current backfill process complete")
                return 2

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
