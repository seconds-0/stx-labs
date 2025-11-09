# Wallet Metrics Backfill Process - Deep Dive Analysis

## Overview

The `wallet_metrics.py` module implements a two-phase transaction history backfill strategy via the `ensure_transaction_history()` function. It fetches transaction data from the Hiro API and stores it in a DuckDB database, with intelligent pagination and resumption handling.

---

## 1. Function Signature & Parameters

### `ensure_transaction_history()`

```python
def ensure_transaction_history(
    *,
    max_days: int,
    force_refresh: bool,
    max_pages: int = DEFAULT_MAX_PAGES,  # 10,000
) -> None:
```

**Parameters:**

| Parameter | Type | Purpose | Notes |
|-----------|------|---------|-------|
| `max_days` | int | Historical window to fetch (days back from now) | Must be positive; ValueError if ≤ 0 |
| `force_refresh` | bool | Clear existing cache before fetching | If True, deletes all transactions from DB first |
| `max_pages` | int | Maximum API pages to fetch per phase | Default 10,000; prevents runaway API calls |

**Example Usage:**
```python
# Fetch last 180 days of history
ensure_transaction_history(max_days=180, force_refresh=False)

# Force full refresh (clears DB first)
ensure_transaction_history(max_days=365, force_refresh=True)
```

---

## 2. Two-Phase Backfill Architecture

### Phase 1: `_sync_latest_transactions()` - Forward Fill (Recent → Older)

Fetches the most recent transactions and works backward in time.

**Key Mechanics:**

```python
def _sync_latest_transactions(
    conn: duckdb.DuckDBPyConnection,
    *,
    max_pages: int,
) -> None:
```

1. **Initial State Detection:**
   - Queries `MAX(block_time)` from existing transactions table
   - If table is empty: `max_time = None`
   - If table has data: `max_time = latest_transaction_timestamp`

2. **Pagination & Cursor Movement:**
   - Calls `fetch_transactions_page(limit=50, offset=0, end_time=cursor_to)`
   - `end_time` parameter filters to transactions **before** that timestamp
   - Cursor logic: `_page_cursor(results)` returns `MIN(burn_block_time) - 1`
   - This moves the cursor **backward in time** to avoid re-fetching

3. **Stop Conditions:**
   - **Empty page**: API returns no results → exits loop
   - **Reached overlap**: If `newest_to_consider <= max_time` (already have this data) → exits
   - **Hit max_pages**: Exhausted page limit → exits

4. **Caching Behavior:**
   - First page: `force_refresh=True` (ignore cache, get fresh data)
   - TTL: 300 seconds (5 min) for first page, 1800 seconds (30 min) for subsequent
   - Allows quick re-runs to pick up new transactions

---

### Phase 2: `_sync_historical_transactions()` - Backward Fill (Oldest → Target)

Backfills to reach a historical cutoff date.

**Key Mechanics:**

```python
def _sync_historical_transactions(
    conn: duckdb.DuckDBPyConnection,
    *,
    cutoff: datetime,  # e.g., now - 180 days
    max_pages: int,
) -> None:
```

1. **Target Calculation:**
   - `target_time = cutoff.astimezone(UTC)` (e.g., 180 days ago)
   - Queries `MIN(block_time)` and `MIN(burn_block_time)` from DB
   - If minimum already ≤ target: **returns early** (already have all data!)

2. **Cursor Initialization:**
   - Uses `burn_block_time` if available, else `block_time`
   - Starting cursor = `int(cursor_source.timestamp()) - 1`
   - This "steps back in time" from the oldest known transaction

3. **Pagination & Backfill:**
   - Calls `fetch_transactions_page(end_time=cursor_to)` (cached, TTL=1800s)
   - Each page cursor = `_page_cursor(results) = MIN(burn_block_time) - 1`
   - Processes all results, inserts into DB
   - Updates `min_time` to track earliest transaction seen

4. **Stop Conditions:**
   - **Target reached**: `min_time <= target_time` → exits
   - **Empty page**: No more results → exits
   - **Cursor invalid**: `next_cursor is None or next_cursor >= cursor_to` → exits (no progress)
   - **Hit max_pages**: Exhausted page limit → exits

---

## 3. Pagination Cursor Logic

### `_page_cursor()` Function

```python
def _page_cursor(results: list[dict[str, Any]]) -> int | None:
    timestamps: list[int] = []
    for tx in results:
        cursor_candidate = tx.get("burn_block_time") or tx.get("block_time")
        if cursor_candidate is not None:
            timestamps.append(int(cursor_candidate))
    if not timestamps:
        return None
    return min(timestamps) - 1  # Move cursor BEFORE earliest in this batch
```

**Purpose:** Prevents overlaps and ensures forward progress

**Logic:**
- Prefers `burn_block_time` (canonical blockchain time)
- Falls back to `block_time` (Stacks block time)
- Returns `MIN(timestamps) - 1` to ensure next page fetches earlier data
- Returns `None` if no valid timestamps found (stops backfill)

---

## 4. DuckDB Schema & Caching

### Database Structure

**Location:** `data/cache/wallet_metrics.duckdb`

**Schema:**
```python
CREATE TABLE IF NOT EXISTS transactions (
    tx_id VARCHAR PRIMARY KEY,
    block_time TIMESTAMP,
    block_height BIGINT,
    sender_address VARCHAR,
    fee_ustx BIGINT,
    tx_type VARCHAR,
    canonical BOOLEAN,
    tx_status VARCHAR,
    burn_block_time TIMESTAMP,
    burn_block_height BIGINT,
    microblock_sequence BIGINT,
    ingested_at TIMESTAMP
);
```

### Transaction Filtering

**Only stored if ALL conditions met:**
- `sender_address` is present
- `canonical == True` (only canonical txs)
- `tx_status == "success"` (only successful txs)
- `block_time` is present

**Fee handling:**
- Tries `fee` first, falls back to `fee_rate`
- Defaults to 0 if unparseable

### Insertion

Uses `INSERT OR REPLACE BY NAME` to handle duplicates gracefully:
- Overwrites if same `tx_id` (primary key)
- Timezone normalization: converts all timestamps to UTC-naive for storage

---

## 5. Checking Cache State

### Query Current Cache Status

```python
import duckdb
from pathlib import Path

db_path = Path("data/cache/wallet_metrics.duckdb")
conn = duckdb.connect(str(db_path), read_only=True)

# Row count
row_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]

# Time range
result = conn.execute("""
    SELECT 
        MIN(block_time) as oldest,
        MAX(block_time) as newest,
        COUNT(*) as row_count
    FROM transactions
""").fetchone()

oldest, newest, count = result
print(f"Rows: {count}")
print(f"Oldest: {oldest}")
print(f"Newest: {newest}")
print(f"Span: {(newest - oldest).total_seconds() / 86400:.1f} days")

conn.close()
```

### Cache Files (HTTP Layer)

**Location:** `data/raw/hiro_transactions_*.json`
- One file per unique API call (deterministic SHA256 hash)
- TTL: 300s for fresh data, 1800s for backfill

---

## 6. Retry & API Limit Behavior

### HTTP Layer Retry Policy

**Config:** `src/config.py` - `DEFAULT_RETRY_CONFIG`

```python
@dataclass(frozen=True)
class RetryConfig:
    wait_min_seconds: float = 0.5
    wait_max_seconds: float = 8.0
    max_attempts: int = 5
    status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504, 522, 525)
```

**Behavior on Retryable Status Codes (429, 5xx, etc.):**
1. Raises `TransientHTTPError`
2. Exponential backoff with jitter: 0.5s → 8.0s
3. Max 5 attempts per request
4. On final failure: raises exception (not caught by backfill loop)

### Timeout

- **Request timeout:** 30 seconds (hardcoded in `http_utils._request_once()`)
- **No timeout between pages:** Long backfills can take hours

### API Page Limits

- **Hiro transaction page size:** 50 (hardcoded: `TRANSACTION_PAGE_LIMIT`)
- **Max pages per run:** 10,000 (default; prevents runaway)
  - At 50 tx/page: 500,000 transactions max per run
  - Typical pace: ~1-5 pages/second (depends on API latency)

### What Happens on API Errors

**Example: Hiro API returns 500 error**
1. First attempt: exponential backoff, retry up to 5 times
2. If still failing after 5 attempts: `TransientHTTPError` propagates
3. Backfill loop does NOT catch this—**exception bubbles up** to caller
4. If called from notebook: halts execution; user must re-run

---

## 7. Resumption & Incremental Behavior

### Key Design Principle

**State is persistent**: Each run picks up where the last one left off

### Scenario: Partial Backfill

**Example:** Run with `max_days=180, force_refresh=False` twice:

**Run 1 (0 sec - 30 sec):**
- Phase 1: Fetches 100 pages (newest → older)
- Phase 2 starts but hits max_pages before reaching cutoff
- DB now has transactions from today back to ~60 days ago
- Run stops

**Run 2 (minutes later):**
- Phase 1: Starts from latest again (new data accumulated)
- Phase 2: **Picks up where left off**
  - Queries `MIN(block_time)` = 60 days ago
  - Cursor starts from there
  - Continues backward until reaching 180-day target
- If hits max_pages again: stops, ready for Run 3

### Early Exit Condition

```python
if min_time is not None and min_time <= target_time:
    break  # Already have all data up to target
```

This means if you run multiple times:
- First run might reach target date
- Subsequent runs exit immediately in Phase 2 (no work needed)

### Force Refresh Behavior

```python
if force_refresh:
    conn.execute("DELETE FROM transactions")  # Clear entire table
```

- **Clears all existing data** before syncing
- Both phases then run as if DB was empty
- Useful for: fixing corrupted cache, changing data quality criteria

---

## 8. Timeout & Long-Running Behavior

### No Built-In Timeout

- Backfill can run indefinitely if API is responsive
- Hit max_pages limit: ~10,000 pages = ~500,000 txs
- At typical API pace (1-5 pages/sec): 30-150 minutes

### Recommended Monitoring Approach

```python
import time
import duckdb
from datetime import UTC, datetime

db_path = "data/cache/wallet_metrics.duckdb"

def check_progress():
    conn = duckdb.connect(db_path, read_only=True)
    result = conn.execute("""
        SELECT 
            COUNT(*) as rows,
            MIN(block_time) as oldest,
            MAX(block_time) as newest
        FROM transactions
    """).fetchone()
    conn.close()
    
    rows, oldest, newest = result
    if oldest:
        days_span = (newest - oldest).total_seconds() / 86400
        print(f"{rows:,} rows | {oldest} → {newest} ({days_span:.1f} days)")
        return rows, oldest, newest
    else:
        print("No data")
        return 0, None, None

# Monitor in loop
for i in range(100):
    check_progress()
    time.sleep(10)
```

---

## 9. Key Parameters for Automation

### For Backfill Script

```python
# Config
TARGET_DAYS = 180  # How far back to sync
MAX_PAGES_PER_RUN = 10_000  # Limit per execution
CHECK_INTERVAL = 5  # seconds between polls
MAX_RETRIES = 10  # how many runs before giving up

# Call signature
from src.wallet_metrics import ensure_transaction_history

ensure_transaction_history(
    max_days=TARGET_DAYS,
    force_refresh=False,  # Don't delete cache, just add
    max_pages=MAX_PAGES_PER_RUN,
)
```

### Detecting Backfill Complete

```python
def is_backfill_complete(target_days: int) -> bool:
    import duckdb
    from datetime import UTC, datetime, timedelta
    
    conn = duckdb.connect("data/cache/wallet_metrics.duckdb", read_only=True)
    min_row = conn.execute("SELECT MIN(block_time) FROM transactions").fetchone()
    conn.close()
    
    if not min_row or min_row[0] is None:
        return False
    
    min_time = pd.Timestamp(min_row[0]).tz_localize("UTC")
    target_time = datetime.now(UTC) - timedelta(days=target_days)
    
    return min_time <= pd.Timestamp(target_time)
```

---

## 10. Common Issues & Troubleshooting

### Issue: Backfill Stops Before Target Date

**Causes:**
1. Hit `max_pages` limit (default 10,000)
2. API rate limiting (429 → max retries exceeded)
3. API error (500+ after max retries) → exception stops loop

**Solution:**
- Check logs for error messages
- Increase `max_pages` if running locally
- Wait before retrying (API cooldown)
- Run multiple times to accumulate data

### Issue: DB Growing But Progress Slowing

**Expected behavior:**
- Phase 1: Fast (recent data, fewer pages needed)
- Phase 2: Slows as you go back in time (more total txs)

**Abnormal:**
- If `MAX(block_time)` stops changing: Phase 1 complete, Phase 2 running
- If `MIN(block_time)` stops changing: Page cursor logic broken or API returning duplicates

### Issue: Out of Memory on Large Backfill

**Cause:** DuckDB caching entire result set in memory

**Mitigation:**
- Run multiple times with smaller `max_days` increments
- Stop before OS swap exhausted

---

## Summary: Automation Design

A robust backfill monitor should:

1. **Call function repeatedly:**
   ```python
   while not is_backfill_complete(180):
       ensure_transaction_history(max_days=180, force_refresh=False)
       sleep(30)
   ```

2. **Check progress between runs:**
   - Query DB for `MIN(block_time)` and row count
   - Detect stalls (no progress for 5+ minutes → exit with error)

3. **Handle exceptions:**
   - Catch `TransientHTTPError` or general exceptions
   - Log them, continue retrying
   - Exponential backoff before retry (60s → 300s)

4. **Termination conditions:**
   - Target date reached → success
   - Max retries exceeded → give up
   - Stalled for timeout → give up
   - User cancellation → graceful shutdown

5. **Progress reporting:**
   - Log row count and date range after each run
   - Show time elapsed and estimated time remaining

