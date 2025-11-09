# Wallet Metrics Backfill Automation Guide

This document synthesizes the wallet metrics backfill process analysis to help you build automated helpers and monitoring tools.

## Executive Summary

The wallet metrics backfill is implemented as a **two-phase transaction history synchronization**:

1. **Phase 1 (Recent):** Fetches latest transactions and works backward
2. **Phase 2 (Historical):** Backfills to reach a target date (e.g., 180 days ago)

The process is **idempotent and resumable**: call it multiple times, and it continues where it left off. Each run can fetch up to 10,000 API pages (500,000 transactions) before stopping.

---

## Key Insight: How to Automate This

The function `ensure_transaction_history(max_days=N, force_refresh=False)` implements intelligent resumption:

- **First call:** Fetches all data from today to N days ago
- **Subsequent calls:** Only fetch new data (if any) and continue backfill if not done
- **After completion:** Exits immediately with minimal work

This makes it perfect for a monitoring loop:

```python
while not is_complete(max_days=180):
    ensure_transaction_history(max_days=180, force_refresh=False)
    sleep(30)
    print_progress()
```

---

## Understanding the Backfill Mechanics

### The Cursor System

Pagination uses a **timestamp cursor** to prevent re-fetching and ensure forward progress:

```python
# Phase 1: Recent to past
cursor_to = None  # Start with undefined, fetch latest
# Result: txs from time T to T-1000s
cursor_to = MIN(timestamps) - 1  # Next request: before MIN timestamp

# Phase 2: Past to target
cursor_to = MIN(block_time) - 1  # Start from oldest in DB
# Request: txs before cursor_to
# Result: older txs
cursor_to = MIN(results_timestamps) - 1  # Continue backward
```

**Key principle:** Each page's minimum timestamp becomes the next page's maximum (minus 1 second). This ensures no gaps or overlaps.

### Stop Conditions

The function stops when it reaches **any** of these conditions:

1. **Target date reached** (Phase 2): `MIN(block_time) <= target_time` → done!
2. **Empty page:** API returns no results → can't go further
3. **Max pages hit:** Exhausted page limit (10,000) → resume next time
4. **No progress:** Cursor didn't move backward → exit, try again later
5. **API error:** After 5 retries, exception bubbles up → handle in outer loop

---

## Building the Monitoring Script

### Step 1: Check Progress Function

```python
import duckdb
from datetime import datetime, timedelta, UTC
import pandas as pd
from pathlib import Path

def check_backfill_progress(target_days: int = 180) -> dict:
    """Query DB cache status and completion percentage."""
    db_path = Path("data/cache/wallet_metrics.duckdb")
    
    if not db_path.exists():
        return {
            "status": "no_cache",
            "rows": 0,
            "oldest": None,
            "newest": None,
            "complete": False,
            "days_coverage": 0,
        }
    
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        result = conn.execute("""
            SELECT 
                COUNT(*) as row_count,
                MIN(block_time) as oldest,
                MAX(block_time) as newest
            FROM transactions
        """).fetchone()
        
        rows, oldest, newest = result
        
        if not oldest:
            return {
                "status": "empty",
                "rows": 0,
                "oldest": None,
                "newest": None,
                "complete": False,
                "days_coverage": 0,
            }
        
        target_time = datetime.now(UTC) - timedelta(days=target_days)
        is_complete = pd.Timestamp(oldest) <= pd.Timestamp(target_time)
        days_span = (newest - oldest).total_seconds() / 86400
        
        return {
            "status": "complete" if is_complete else "in_progress",
            "rows": rows,
            "oldest": oldest,
            "newest": newest,
            "complete": is_complete,
            "days_coverage": days_span,
            "target_days": target_days,
        }
    finally:
        conn.close()


# Usage
progress = check_backfill_progress(target_days=180)
print(f"Status: {progress['status']}")
print(f"Rows: {progress['rows']:,}")
print(f"Coverage: {progress['days_coverage']:.1f} days")
print(f"Complete: {progress['complete']}")
```

### Step 2: Resumable Backfill Loop

```python
import time
import logging
from datetime import datetime
from src.wallet_metrics import ensure_transaction_history

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

def run_backfill_until_complete(
    target_days: int = 180,
    max_runs: int = 100,
    wait_seconds: int = 30,
    timeout_minutes: int = 60,
):
    """
    Run backfill repeatedly until target date is reached or max_runs exceeded.
    
    Args:
        target_days: Historical window to fetch (days back from now)
        max_runs: Maximum number of times to call ensure_transaction_history
        wait_seconds: Seconds to wait between runs
        timeout_minutes: Max wall-clock time (gives up if exceeded)
    """
    start_time = time.time()
    max_elapsed = timeout_minutes * 60
    
    for run_number in range(1, max_runs + 1):
        elapsed = time.time() - start_time
        
        # Check timeout
        if elapsed > max_elapsed:
            logger.error(f"Timeout after {timeout_minutes} minutes")
            return False
        
        # Check progress before running
        progress_before = check_backfill_progress(target_days)
        logger.info(f"[Run {run_number}] Before: {progress_before['rows']:,} rows, "
                   f"{progress_before['days_coverage']:.1f} days coverage")
        
        # If complete, stop
        if progress_before['complete']:
            logger.info("Backfill complete!")
            return True
        
        # Run backfill
        try:
            logger.info(f"[Run {run_number}] Starting ensure_transaction_history...")
            ensure_transaction_history(
                max_days=target_days,
                force_refresh=False,
            )
        except Exception as e:
            logger.warning(f"[Run {run_number}] Error: {e}")
            # Continue anyway, maybe transient
        
        # Check progress after running
        progress_after = check_backfill_progress(target_days)
        logger.info(f"[Run {run_number}] After: {progress_after['rows']:,} rows, "
                   f"{progress_after['days_coverage']:.1f} days coverage")
        
        # Detect stalls
        if progress_after['rows'] == progress_before['rows']:
            logger.warning(f"[Run {run_number}] No progress made (same row count)")
            # Could wait longer and retry, or give up
        
        # If complete, return success
        if progress_after['complete']:
            logger.info("Backfill complete!")
            return True
        
        # Wait before next run (unless it's the last)
        if run_number < max_runs:
            logger.info(f"Waiting {wait_seconds}s before next run...")
            time.sleep(wait_seconds)
    
    logger.error(f"Exceeded max_runs ({max_runs}), backfill may not be complete")
    return False


# Usage
if __name__ == "__main__":
    success = run_backfill_until_complete(
        target_days=180,
        max_runs=10,
        wait_seconds=30,
        timeout_minutes=120,  # 2 hours max
    )
    exit(0 if success else 1)
```

### Step 3: Production Monitoring Script

```python
#!/usr/bin/env python3
"""
Automated wallet metrics backfill monitor.
Runs in background, updates cache, reports progress.
"""

import sys
import time
import json
import logging
from datetime import datetime, UTC
from pathlib import Path

# Configure logging
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "backfill.log"

handler = logging.FileHandler(log_file)
handler.setFormatter(logging.Formatter(
    '%(asctime)s | %(levelname)s | %(message)s'
))
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(handler)

from src.wallet_metrics import ensure_transaction_history

def write_status(status: dict) -> None:
    """Write current status to JSON file for monitoring."""
    status_file = Path("data/backfill_status.json")
    status_file.write_text(json.dumps({
        **status,
        "timestamp": datetime.now(UTC).isoformat(),
    }, indent=2))

def main():
    target_days = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    
    logger.info(f"Starting backfill monitor (target: {target_days} days)")
    write_status({"status": "starting", "target_days": target_days})
    
    try:
        success = run_backfill_until_complete(
            target_days=target_days,
            max_runs=50,
            wait_seconds=60,
            timeout_minutes=360,  # 6 hours
        )
        
        if success:
            write_status({
                "status": "complete",
                "target_days": target_days,
                **check_backfill_progress(target_days)
            })
        else:
            write_status({
                "status": "failed",
                "target_days": target_days,
                **check_backfill_progress(target_days)
            })
        
        return 0 if success else 1
    
    except Exception as e:
        logger.exception("Unhandled exception")
        write_status({
            "status": "error",
            "error": str(e),
            "target_days": target_days,
        })
        return 2

if __name__ == "__main__":
    sys.exit(main())
```

---

## Detecting Common Issues

### Problem: Backfill Never Completes

**Diagnosis steps:**

```python
# 1. Check if DB is growing
import time
from docs.wallet_backfill_quick_ref import check_backfill_progress

p1 = check_backfill_progress(180)
time.sleep(60)
p2 = check_backfill_progress(180)

if p1['rows'] == p2['rows']:
    print("ERROR: No progress in 60 seconds!")
    # Likely API error, rate limit, or network issue
else:
    print(f"Progress: {p2['rows'] - p1['rows']} rows/min")
    # Extrapolate time to completion
    pace = (p2['rows'] - p1['rows']) / 60  # rows/sec
    remaining_days = p2['target_days'] - p2['days_coverage']
    # This is rough, but better than nothing
```

### Problem: High Memory Usage

**Cause:** Each `ensure_transaction_history()` call loads all results into memory

**Mitigation:**
- Run with smaller `max_days` increments
- Increase wait time between runs to let OS swap
- Monitor memory with `ps` or `top`

### Problem: API Timeout After Long Backfill

**Cause:** 30-second request timeout during slow API responses

**Fix:** Not fixable from backfill code (timeout is hardcoded in http_utils.py)
- Retry the backfill (will pick up where it left off)
- Run during off-peak hours (less API load)

---

## Configuration Parameters

### For Your Script

```python
# Target how many days back to sync
TARGET_DAYS = 180

# How many runs to attempt before giving up
MAX_RUNS = 50

# Seconds between runs
WAIT_SECONDS = 60

# Wall-clock timeout in minutes
TIMEOUT_MINUTES = 360  # 6 hours

# Stall detection: if no progress for this many seconds, give up
STALL_TIMEOUT_SECONDS = 300  # 5 minutes
```

### Hiro API (src/wallet_metrics.py)

```python
TRANSACTION_PAGE_LIMIT = 50  # Hardcoded, can't change
DEFAULT_MAX_PAGES = 10_000   # Max pages per ensure_transaction_history() call
```

### HTTP Retry (src/config.py)

```python
wait_min_seconds = 0.5       # Min backoff
wait_max_seconds = 8.0       # Max backoff  
max_attempts = 5             # Retries per request
```

---

## Performance Expectations

### Time to Complete

| Target | Typical Time | Notes |
|--------|--------------|-------|
| 30 days | 5-15 min | Mostly Phase 1 |
| 90 days | 20-60 min | Phases 1+2 |
| 180 days | 45-120 min | Heavy Phase 2 |
| 365 days | 2-4 hours | Very heavy Phase 2 |

### Rows Per Run

| Scenario | Rows | Pages | Time |
|----------|------|-------|------|
| Fresh sync (30d) | ~50K | ~1K | 3-5 min |
| New data only | ~5K | ~100 | 1-2 min |
| After complete | ~0 | ~5 | <1 sec |

---

## Deployment Options

### Option 1: Manual (When Needed)

```bash
# Terminal 1: Start backfill
python -m scripts.backfill_monitor 180

# Terminal 2: Monitor (optional)
while true; do
  python -c "
from docs.wallet_backfill_quick_ref import check_backfill_progress
import json
p = check_backfill_progress(180)
print(json.dumps(p, indent=2, default=str))
"
  sleep 30
done
```

### Option 2: Scheduled (Cron)

```bash
# In crontab -e
0 */6 * * * /usr/bin/python3 /path/to/stx-labs/scripts/backfill_monitor.py 180 >> /var/log/backfill.log 2>&1
```

### Option 3: Continuous (systemd)

Create `/etc/systemd/system/stx-backfill.service`:

```ini
[Unit]
Description=Stacks wallet metrics backfill
After=network.target

[Service]
Type=simple
User=appuser
WorkingDirectory=/opt/stx-labs
ExecStart=/usr/bin/python3 scripts/backfill_monitor.py 180
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
```

Then:
```bash
systemctl enable stx-backfill
systemctl start stx-backfill
systemctl status stx-backfill
```

---

## Integration with Dashboard Build

The dashboard build script (`scripts/build_dashboards.py`) calls `build_wallet_metrics()`, which in turn calls `ensure_transaction_history()`. So backfill runs automatically!

To ensure sufficient data before dashboard generation:

```python
# Before building dashboards
from scripts.backfill_monitor import run_backfill_until_complete

# Ensure we have at least 180 days
if not run_backfill_until_complete(target_days=180, max_runs=30):
    logger.warning("Backfill incomplete, proceeding with available data")

# Now build dashboard
from scripts.build_dashboards import build_all
build_all()
```

---

## Troubleshooting Checklist

- [ ] Is HIRO_API_KEY set? `echo $HIRO_API_KEY`
- [ ] Is internet working? `curl https://api.hiro.so/extended/v1/tx -H "X-API-Key: $HIRO_API_KEY"`
- [ ] Is DuckDB writeable? `ls -l data/cache/wallet_metrics.duckdb`
- [ ] Is disk space available? `df -h data/`
- [ ] Are there errors in the logs? `grep -i error logs/backfill.log`
- [ ] How much data do we have? Run `check_backfill_progress()`
- [ ] Is the process still running? `ps aux | grep backfill`

---

## Next Steps

1. **Implement Step 1 & 2** above to create a basic backfill monitor
2. **Test locally** with `max_days=30, max_runs=5` first
3. **Add to deployment** (cron or systemd)
4. **Monitor** the logs and status JSON file
5. **Build dashboards** once backfill is complete

For detailed API mechanics, see `/docs/wallet_backfill_analysis.md`.

