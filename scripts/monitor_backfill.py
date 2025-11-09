#!/usr/bin/env python3
"""
Real-time backfill monitoring script.

Displays live updates of backfill progress with visual indicators,
timing estimates, and database statistics. Run in a separate terminal
while backfill is running in the background.

Usage:
    python scripts/monitor_backfill.py [--target-days 180] [--refresh-interval 10]

Features:
- Real-time progress bar and percentage
- Live database statistics (rows, wallets, date range)
- Time elapsed and estimated time remaining
- Recent log entries from backfill process
- Auto-refresh display (clears screen between updates)
- Colorized output for better readability
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add src/ to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
from src.config import CACHE_DIR


# ANSI color codes
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def clear_screen():
    """Clear terminal screen."""
    os.system('clear' if os.name != 'nt' else 'cls')


def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}m"
    else:
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}h {minutes}m"


def get_db_stats(db_path: Path) -> dict:
    """Get current database statistics."""
    if not db_path.exists():
        return None

    try:
        conn = duckdb.connect(str(db_path), read_only=True)
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
        conn.close()

        if not result or result[0] == 0:
            return None

        return {
            "row_count": result[0],
            "wallet_count": result[1],
            "min_time": result[2],
            "max_time": result[3],
        }
    except Exception as e:
        return {"error": str(e)}


def parse_log_timestamp(line: str) -> datetime:
    """Try to parse timestamp from log line."""
    # Look for ISO format timestamps
    try:
        # Simple heuristic: find YYYY-MM-DD pattern
        if len(line) > 19:
            date_str = line[:19]
            return datetime.fromisoformat(date_str)
    except:
        pass
    return None


def get_recent_log_lines(log_path: Path, num_lines: int = 10) -> list:
    """Get recent lines from log file."""
    if not log_path.exists():
        return []

    try:
        with open(log_path, 'r') as f:
            lines = f.readlines()
            return lines[-num_lines:] if lines else []
    except Exception as e:
        return [f"Error reading log: {e}"]


def draw_progress_bar(progress_pct: float, width: int = 50) -> str:
    """Draw a fancy progress bar."""
    filled = int(width * progress_pct / 100)
    bar = '█' * filled + '░' * (width - filled)
    return f"[{bar}] {progress_pct:.1f}%"


def check_process_running(pid_file: Path, log_path: Path) -> tuple:
    """Check if backfill process is running and get its details."""
    # Try to find backfill process
    try:
        import subprocess
        result = subprocess.run(
            ['pgrep', '-f', 'backfill_wallet_history.py'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            pids = result.stdout.strip().split('\n')
            return True, pids[0] if pids else None
    except:
        pass

    # Fallback: check if log file is being written to
    if log_path.exists():
        # Check if log was modified recently (within last 60 seconds)
        mtime = log_path.stat().st_mtime
        age = time.time() - mtime
        if age < 60:
            return True, None

    return False, None


def display_monitor(args, start_time: float, previous_stats: dict = None):
    """Display monitoring dashboard."""
    clear_screen()

    db_path = CACHE_DIR / "wallet_metrics.duckdb"
    log_path = Path("out/backfill.log")
    pid_file = Path("out/backfill.pid")
    target_date = datetime.now(timezone.utc) - timedelta(days=args.target_days)

    # Header
    print(f"{Colors.BOLD}{Colors.HEADER}{'='*80}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.HEADER}{'WALLET BACKFILL MONITOR':^80}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.HEADER}{'='*80}{Colors.ENDC}\n")

    # Process status
    is_running, pid = check_process_running(pid_file, log_path)
    if is_running:
        status_color = Colors.GREEN
        status_text = "✓ RUNNING"
        if pid:
            status_text += f" (PID {pid})"
    else:
        status_color = Colors.RED
        status_text = "✗ NOT RUNNING (or idle)"

    print(f"{Colors.BOLD}Process Status:{Colors.ENDC} {status_color}{status_text}{Colors.ENDC}")
    print(f"{Colors.BOLD}Target:{Colors.ENDC} {args.target_days} days back to {target_date.strftime('%Y-%m-%d')}")
    print(f"{Colors.BOLD}Elapsed Time:{Colors.ENDC} {format_duration(time.time() - start_time)}")
    print()

    # Database statistics
    stats = get_db_stats(db_path)

    if stats is None:
        print(f"{Colors.YELLOW}⚠ Database not yet created or empty{Colors.ENDC}\n")
    elif "error" in stats:
        print(f"{Colors.RED}✗ Error reading database: {stats['error']}{Colors.ENDC}\n")
    else:
        print(f"{Colors.BOLD}{Colors.CYAN}DATABASE STATISTICS{Colors.ENDC}")
        print(f"{'─'*80}")

        # Parse timestamps
        min_time = stats["min_time"]
        max_time = stats["max_time"]

        if isinstance(min_time, str):
            min_time = datetime.fromisoformat(min_time.replace("Z", "+00:00"))
        if isinstance(max_time, str):
            max_time = datetime.fromisoformat(max_time.replace("Z", "+00:00"))

        if min_time and min_time.tzinfo is None:
            min_time = min_time.replace(tzinfo=timezone.utc)
        if max_time and max_time.tzinfo is None:
            max_time = max_time.replace(tzinfo=timezone.utc)

        # Calculate progress
        now = datetime.now(timezone.utc)
        days_covered = (now - min_time).days if min_time else 0
        progress_pct = min(100, (days_covered / args.target_days) * 100)

        # Progress bar
        print(f"\n{draw_progress_bar(progress_pct)}")
        print()

        # Stats
        print(f"{Colors.BOLD}Transactions:{Colors.ENDC} {stats['row_count']:,}")
        print(f"{Colors.BOLD}Unique Wallets:{Colors.ENDC} {stats['wallet_count']:,}")
        print(f"{Colors.BOLD}Earliest Tx:{Colors.ENDC} {min_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"{Colors.BOLD}Latest Tx:{Colors.ENDC} {max_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"{Colors.BOLD}Coverage:{Colors.ENDC} {days_covered} days / {args.target_days} days")

        # Change rate (if we have previous stats)
        if previous_stats and previous_stats.get("row_count"):
            row_delta = stats["row_count"] - previous_stats["row_count"]
            wallet_delta = stats["wallet_count"] - previous_stats["wallet_count"]
            time_delta = args.refresh_interval

            rows_per_sec = row_delta / time_delta if time_delta > 0 else 0
            print(f"{Colors.BOLD}Rate:{Colors.ENDC} {Colors.GREEN}+{row_delta:,} rows (+{wallet_delta} wallets) in {time_delta}s ({rows_per_sec:.1f} rows/s){Colors.ENDC}")

        # Estimated completion
        if progress_pct > 0 and progress_pct < 100:
            elapsed = time.time() - start_time
            estimated_total = elapsed / (progress_pct / 100)
            remaining = estimated_total - elapsed
            eta = datetime.now() + timedelta(seconds=remaining)

            print(f"\n{Colors.BOLD}Estimated completion:{Colors.ENDC} {format_duration(remaining)} ({eta.strftime('%H:%M:%S')})")
        elif progress_pct >= 100:
            print(f"\n{Colors.GREEN}{Colors.BOLD}✓ BACKFILL COMPLETE!{Colors.ENDC}")

        print()

    # Recent log entries
    print(f"{Colors.BOLD}{Colors.CYAN}RECENT LOG ENTRIES{Colors.ENDC}")
    print(f"{'─'*80}")

    log_lines = get_recent_log_lines(log_path, num_lines=8)
    if log_lines:
        for line in log_lines:
            line = line.rstrip()
            if not line:
                continue

            # Colorize based on content
            if '✓' in line or 'completed' in line.lower():
                print(f"{Colors.GREEN}{line}{Colors.ENDC}")
            elif '✗' in line or 'error' in line.lower() or 'failed' in line.lower():
                print(f"{Colors.RED}{line}{Colors.ENDC}")
            elif '⚠' in line or 'warning' in line.lower():
                print(f"{Colors.YELLOW}{line}{Colors.ENDC}")
            elif 'ITERATION' in line or '=' in line:
                print(f"{Colors.BOLD}{line}{Colors.ENDC}")
            else:
                print(line)
    else:
        print(f"{Colors.YELLOW}No log output yet (log may be buffering...){Colors.ENDC}")

    print()

    # Footer
    print(f"{'─'*80}")
    print(f"{Colors.BOLD}Log file:{Colors.ENDC} {log_path}")
    print(f"{Colors.BOLD}Database:{Colors.ENDC} {db_path}")
    if db_path.exists():
        db_size_mb = db_path.stat().st_size / 1024 / 1024
        print(f"{Colors.BOLD}DB Size:{Colors.ENDC} {db_size_mb:.1f} MB")
    print()
    print(f"Refreshing every {args.refresh_interval}s... (Ctrl+C to stop)")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Real-time backfill monitoring dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--target-days",
        type=int,
        default=180,
        help="Target backfill days (default: 180)",
    )
    parser.add_argument(
        "--refresh-interval",
        type=int,
        default=10,
        help="Refresh interval in seconds (default: 10)",
    )

    args = parser.parse_args()

    print(f"{Colors.BOLD}Starting backfill monitor...{Colors.ENDC}")
    print(f"Press Ctrl+C to stop\n")
    time.sleep(2)

    start_time = time.time()
    previous_stats = None

    try:
        while True:
            previous_stats = display_monitor(args, start_time, previous_stats)
            time.sleep(args.refresh_interval)

    except KeyboardInterrupt:
        print(f"\n\n{Colors.BOLD}Monitor stopped by user{Colors.ENDC}")
        print(f"\nTo check status again, run:")
        print(f"  python scripts/monitor_backfill.py")
        print(f"\nOr for quick status:")
        print(f"  make backfill-status")
        return 0


if __name__ == "__main__":
    sys.exit(main())
