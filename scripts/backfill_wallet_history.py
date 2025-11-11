#!/usr/bin/env python3
"""
Automated wallet transaction history backfill script.

Repeatedly calls wallet_metrics.ensure_transaction_history() until the target
date range is achieved. Designed to run in tmux/screen for long-running backfills.

Usage:
    python scripts/backfill_wallet_history.py [--target-days 180] [--max-iterations 50]

The script will:
1. Check current database state (min/max timestamps, row counts)
2. Run ensure_transaction_history() to fetch more data
3. Monitor progress after each iteration
4. Stop when target date is reached or max iterations hit
5. Provide detailed progress logging throughout

Safe to interrupt and restart - picks up where it left off via DuckDB state.
"""
import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add src/ to path so we can import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb

from src import wallet_metrics
from src.config import CACHE_DIR


def get_db_status(db_path: Path) -> dict:
    """Query DuckDB for current backfill status."""
    if not db_path.exists():
        return {
            "exists": False,
            "row_count": 0,
            "wallet_count": 0,
            "min_time": None,
            "max_time": None,
        }

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        # Check if transactions table exists
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name = 'transactions'"
        ).fetchall()
        if not tables:
            return {
                "exists": True,
                "row_count": 0,
                "wallet_count": 0,
                "min_time": None,
                "max_time": None,
            }

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

        return {
            "exists": True,
            "row_count": result[0] if result else 0,
            "wallet_count": result[1] if result else 0,
            "min_time": result[2] if result else None,
            "max_time": result[3] if result else None,
        }
    finally:
        conn.close()


def format_status(status: dict) -> str:
    """Format database status for human-readable output."""
    if not status["exists"]:
        return "Database does not exist yet"

    if status["row_count"] == 0:
        return "Database exists but is empty"

    lines = [
        f"Rows: {status['row_count']:,}",
        f"Unique wallets: {status['wallet_count']:,}",
    ]

    if status["min_time"]:
        lines.append(f"Earliest transaction: {status['min_time']}")
    if status["max_time"]:
        lines.append(f"Latest transaction: {status['max_time']}")

    return " | ".join(lines)


def calculate_target_date(target_days: int) -> datetime:
    """Calculate the target date (now - target_days)."""
    return datetime.now(timezone.utc) - timedelta(days=target_days)


def is_backfill_complete(status: dict, target_date: datetime) -> bool:
    """Check if backfill has reached the target date."""
    if not status["exists"] or status["min_time"] is None:
        return False

    # Parse min_time (could be string or datetime)
    if isinstance(status["min_time"], str):
        min_time = datetime.fromisoformat(status["min_time"].replace("Z", "+00:00"))
    else:
        min_time = status["min_time"]

    # Ensure timezone-aware comparison
    if min_time.tzinfo is None:
        min_time = min_time.replace(tzinfo=timezone.utc)

    return min_time <= target_date


def run_backfill_iteration(max_days: int, iteration: int, max_pages: int, force_refresh: bool = False) -> bool:
    """
    Run one iteration of the backfill process.

    Returns True if successful, False if error occurred.
    """
    print(f"\n{'='*80}")
    print(f"ITERATION {iteration}: Starting backfill (max_days={max_days}, max_pages={max_pages})")
    print(f"{'='*80}")

    start_time = time.time()

    try:
        wallet_metrics.ensure_transaction_history(
            max_days=max_days,
            force_refresh=force_refresh,
            max_pages=max_pages
        )
        elapsed = time.time() - start_time
        print(f"\n✓ Iteration {iteration} completed in {elapsed:.1f}s")
        return True

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n✗ Iteration {iteration} failed after {elapsed:.1f}s")
        print(f"Error: {type(e).__name__}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Automated wallet transaction history backfill",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Backfill to 180 days (default)
  python scripts/backfill_wallet_history.py

  # Backfill to 365 days with max 100 iterations
  python scripts/backfill_wallet_history.py --target-days 365 --max-iterations 100

  # Force refresh (ignore cache)
  python scripts/backfill_wallet_history.py --force-refresh

  # Run in tmux for long-running backfills
  tmux new -s wallet-sync
  python scripts/backfill_wallet_history.py --target-days 365
  # Ctrl+B D to detach, tmux attach -t wallet-sync to reattach
        """,
    )
    parser.add_argument(
        "--target-days",
        type=int,
        default=180,
        help="Number of days to backfill (default: 180)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=50,
        help="Maximum number of backfill iterations (default: 50, 0=unlimited)",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Force refresh (ignore HTTP cache)",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=5,
        help="Delay in seconds between iterations (default: 5)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=2000,
        help="Maximum pages per iteration (default: 2000, lower = faster iterations)",
    )

    args = parser.parse_args()

    # Calculate target date
    target_date = calculate_target_date(args.target_days)
    db_path = CACHE_DIR / "wallet_metrics.duckdb"

    print("="*80)
    print("WALLET TRANSACTION HISTORY BACKFILL")
    print("="*80)
    print(f"Target: {args.target_days} days back to {target_date.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Max iterations: {args.max_iterations}")
    print(f"Max pages per iteration: {args.max_pages}")
    print(f"Force refresh: {args.force_refresh}")
    print(f"Database: {db_path}")
    print("="*80)

    # Check initial status
    print("\nInitial database status:")
    initial_status = get_db_status(db_path)
    print(format_status(initial_status))

    if is_backfill_complete(initial_status, target_date):
        print(f"\n✓ Backfill already complete! Database covers target date range.")
        return 0

    # Run iterations until complete or max iterations reached
    iteration = 0
    consecutive_failures = 0
    max_consecutive_failures = 3

    while args.max_iterations == 0 or iteration < args.max_iterations:
        iteration += 1

        # Run backfill
        success = run_backfill_iteration(
            max_days=args.target_days,
            iteration=iteration,
            max_pages=args.max_pages,
            force_refresh=args.force_refresh
        )

        if not success:
            consecutive_failures += 1
            print(f"⚠ Consecutive failures: {consecutive_failures}/{max_consecutive_failures}")

            if consecutive_failures >= max_consecutive_failures:
                print(f"\n✗ Stopping after {max_consecutive_failures} consecutive failures")
                return 1

            # Longer delay after failure
            print(f"Waiting {args.delay * 2}s before retry...")
            time.sleep(args.delay * 2)
            continue

        # Reset failure counter on success
        consecutive_failures = 0

        # Check progress
        status = get_db_status(db_path)
        print(f"\nCurrent status: {format_status(status)}")

        # Calculate progress
        if status["min_time"]:
            if isinstance(status["min_time"], str):
                min_time = datetime.fromisoformat(status["min_time"].replace("Z", "+00:00"))
            else:
                min_time = status["min_time"]

            if min_time.tzinfo is None:
                min_time = min_time.replace(tzinfo=timezone.utc)

            days_covered = (datetime.now(timezone.utc) - min_time).days
            progress_pct = (days_covered / args.target_days) * 100
            print(f"Progress: {days_covered}/{args.target_days} days ({progress_pct:.1f}%)")

        # Check if complete
        if is_backfill_complete(status, target_date):
            print("\n" + "="*80)
            print("✓ BACKFILL COMPLETE!")
            print("="*80)
            print(f"Total iterations: {iteration}")
            print(f"Final status: {format_status(status)}")
            print("\nNext steps:")
            print("  1. Run 'make smoke-notebook' or 'make notebook' to regenerate dashboards")
            print("  2. Or run 'python scripts/build_dashboards.py' for quick dashboard update")
            return 0

        # Delay before next iteration
        if iteration < args.max_iterations:
            print(f"\nWaiting {args.delay}s before next iteration...")
            time.sleep(args.delay)

    # Max iterations reached without completion
    print("\n" + "="*80)
    print("⚠ MAX ITERATIONS REACHED")
    print("="*80)
    print(f"Completed {args.max_iterations} iterations but target not yet reached")
    final_status = get_db_status(db_path)
    print(f"Current status: {format_status(final_status)}")
    print("\nOptions:")
    print("  1. Re-run this script to continue backfilling")
    print("  2. Increase --max-iterations if needed")
    print("  3. Check logs for any errors that need investigation")
    return 1


if __name__ == "__main__":
    sys.exit(main())
