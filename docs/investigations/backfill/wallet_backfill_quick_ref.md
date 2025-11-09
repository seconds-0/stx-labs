# Wallet Metrics Backfill - Quick Reference

## Function Call

```python
from src.wallet_metrics import ensure_transaction_history

# Basic call
ensure_transaction_history(
    max_days=180,           # Target: 180 days of history
    force_refresh=False,    # Don't delete existing cache
)
```

---

## Execution Flow Diagram

```
ensure_transaction_history(max_days=180, force_refresh=False)
│
├─ if force_refresh: DELETE FROM transactions  ← Only if force_refresh=True
│
├─ PHASE 1: _sync_latest_transactions()
│  │
│  ├─ Query MAX(block_time) from DB
│  │  └─ If empty: max_time = None
│  │  └─ Else: max_time = latest transaction
│  │
│  └─ Loop (up to max_pages):
│     ├─ fetch_transactions_page(end_time=cursor_to)
│     ├─ Parse results, filter (canonical + success only)
│     ├─ Insert into transactions table
│     └─ Stop if: empty page OR reached overlap OR hit max_pages
│
└─ PHASE 2: _sync_historical_transactions()
   │
   ├─ Calculate target_time = now - 180 days
   ├─ Query MIN(block_time) from DB
   │  └─ If already <= target: RETURN (done!)
   │
   └─ Loop (up to max_pages):
      ├─ Start cursor from MIN(block_time) - 1
      ├─ fetch_transactions_page(end_time=cursor_to)
      ├─ Parse, filter, insert
      └─ Stop if: target reached OR empty page OR no progress
```

---

## Phase Comparison

| Aspect | Phase 1 (Latest) | Phase 2 (Historical) |
|--------|------------------|----------------------|
| **Direction** | Recent → Past | Past → Target |
| **Start cursor** | None (undefined time) | MIN(block_time) - 1 |
| **Stop condition** | Empty page OR overlap OR max_pages | Target date ≤ reached OR empty OR max_pages |
| **Cache TTL** | 300s (fresh) / 1800s (fast) | 1800s (stable) |
| **Early exit?** | No | Yes, if already have target data |

---

## Key Variables

### Configuration

```python
TRANSACTION_PAGE_LIMIT = 50        # API page size (fixed)
DEFAULT_MAX_PAGES = 10_000         # Default page limit per run
DUCKDB_PATH = Path("data/cache/wallet_metrics.duckdb")
```

### Retry Policy (http_utils.py)

```python
wait_min_seconds = 0.5              # Min backoff
wait_max_seconds = 8.0              # Max backoff
max_attempts = 5                    # Retry attempts
status_forcelist = (429, 500, 502, 503, 504, 522, 525)
```

### Request Timeout

- **Single request:** 30 seconds (hardcoded)
- **Between pages:** No limit (could take hours)

---

## Cursor Logic

```
Current DB state:
  MIN(block_time) = 2024-06-01 10:00 (60 days ago)
  MAX(block_time) = 2024-09-01 10:00 (today)

Phase 2 initialization:
  target_time = 2024-03-04 (180 days from now)
  cursor_to = int(2024-06-01 10:00 timestamp) - 1
           = 1717224000 - 1
           = 1717223999

Fetch: GET /tx?end_time=1717223999
Result page has transactions from 2024-06-01 09:45 to 2024-05-31 14:20
  MIN timestamp in results = 2024-05-31 14:20
  next_cursor = int(2024-05-31 14:20 timestamp) - 1
              = 1717160400 - 1
              = 1717160399

Next iteration: GET /tx?end_time=1717160399
...continues until MIN(block_time) <= target_time
```

---

## Status Queries

### Check Progress

```python
import duckdb
from datetime import datetime, timedelta, UTC
import pandas as pd

conn = duckdb.connect("data/cache/wallet_metrics.duckdb", read_only=True)

# Current state
result = conn.execute("""
    SELECT 
        COUNT(*) as row_count,
        MIN(block_time) as oldest,
        MAX(block_time) as newest
    FROM transactions
""").fetchone()

rows, oldest, newest = result
if oldest:
    days = (newest - oldest).total_seconds() / 86400
    print(f"Rows: {rows:,} | Span: {days:.1f} days | {oldest} → {newest}")
else:
    print("Empty database")

# Check if target reached
target = datetime.now(UTC) - timedelta(days=180)
is_complete = pd.Timestamp(oldest) <= pd.Timestamp(target)
print(f"180-day target complete: {is_complete}")

conn.close()
```

---

## Error Handling

### What Exceptions Can Occur

1. **ValueError**: `max_days <= 0`
2. **TransientHTTPError**: API returned 429/5xx after max retries
3. **RuntimeError**: Non-JSON response from API
4. **OSError**: Disk I/O error during cache operations

### Recovery Pattern

```python
import time
from src.wallet_metrics import ensure_transaction_history

max_retries = 5
for attempt in range(max_retries):
    try:
        ensure_transaction_history(max_days=180, force_refresh=False)
        print("Success!")
        break
    except Exception as e:
        print(f"Attempt {attempt+1} failed: {e}")
        if attempt < max_retries - 1:
            wait = min(60 * (2 ** attempt), 300)  # Exponential backoff, cap at 5min
            print(f"Retrying in {wait}s...")
            time.sleep(wait)
        else:
            print("Max retries exceeded")
            raise
```

---

## Monitoring Progress

### Poll Interval Recommendation

- **Check every 10-30 seconds** during backfill
- **Long-running backfill (>1h):** Check every 60s
- **Look for stalls:** No progress after 5+ minutes → abort

### Key Metrics

```python
# Calculate backfill pace
rows_before = current_rows
time.sleep(30)
rows_after = current_rows
rows_per_sec = (rows_after - rows_before) / 30

# Estimate time to complete
target_rows = 1_000_000  # Example
remaining = max(0, target_rows - rows_after)
eta_seconds = remaining / rows_per_sec if rows_per_sec > 0 else float('inf')
print(f"ETA: {eta_seconds/3600:.1f} hours")
```

---

## API Behavior Notes

### Pagination Strategy

- **Hiro API supports `end_time` filtering:** Returns txs before this timestamp
- **Results ordered descending:** Newest first
- **No guarantee of contiguous results:** May skip blocks

### Cache Behavior

- **HTTP responses cached in:** `data/raw/hiro_transactions_*.json`
- **Deterministic keys:** Same request = same cache file
- **TTL respected:** Stale entries ignored
- **force_refresh=True:** Bypasses HTTP cache (not DB cache)

### Rate Limits

- Hiro API limits not explicitly documented
- Exponential backoff helps with 429 errors
- If consistently failing: try again after several minutes

---

## Resumption Example

```
Time 0:00 - Start 1:
  max_days=180, force_refresh=False
  Phase 1: Fetches 50 pages (today → 1 week ago)
  Phase 2: Fetches 100 pages (1 week ago → 30 days ago)
  Hits max_pages=10,000
  DB now has: 0 → 30 days ago
  
Time 0:30 - Start 2:
  max_days=180, force_refresh=False
  Phase 1: Fetches 5 pages (new data since run 1)
  Phase 2: Queries MIN(block_time) = 30 days ago
           Starts from there, fetches 200 pages
           Hits max_pages=10,000
           DB now has: 0 → 90 days ago

Time 1:00 - Start 3:
  max_days=180, force_refresh=False
  Phase 1: Fetches 2 pages (latest new txs)
  Phase 2: Queries MIN(block_time) = 90 days ago
           Continues backfill
           Reaches target_time = 180 days ago
           BREAKS early (no max_pages needed)
           DB now has: 0 → 180 days ago
           
Time 1:01 - Start 4:
  max_days=180, force_refresh=False
  Phase 1: Fetches 1 page
  Phase 2: Queries MIN(block_time) = 180+ days ago
           Condition: min_time <= target_time
           RETURNS IMMEDIATELY (nothing to do)
           Duration: <1 second
```

---

## Common Patterns

### Pattern 1: One-Off Full Backfill

```python
# Initial setup: Get last year of data
ensure_transaction_history(max_days=365, force_refresh=True)

# Time: ~2-4 hours for full year
# Monitor: Check progress every minute
```

### Pattern 2: Incremental Updates

```python
# Run after other updates
ensure_transaction_history(max_days=180, force_refresh=False)

# Time: <1 minute if already synced, up to 30min if needs backfill
# Safe to run multiple times (idempotent after completion)
```

### Pattern 3: Continuous Monitoring

```python
import schedule

def backfill_job():
    ensure_transaction_history(max_days=180, force_refresh=False)
    print("Backfill complete")

schedule.every(6).hours.do(backfill_job)
schedule.every(30).minutes.do(backfill_job)  # Quick updates

while True:
    schedule.run_pending()
    time.sleep(30)
```

