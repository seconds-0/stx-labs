# Wallet Metrics Backfill - Exploration Summary

**Date:** November 7, 2025  
**Purpose:** Deep exploration of wallet_metrics.py to understand backfill mechanics for automation  
**Status:** Complete

---

## What Was Explored

### Files Analyzed

1. **src/wallet_metrics.py** (675 lines)
   - Main function: `ensure_transaction_history(max_days, force_refresh, max_pages)`
   - Phase 1: `_sync_latest_transactions()` - forward fill
   - Phase 2: `_sync_historical_transactions()` - backward fill
   - Helper functions: pagination, filtering, insertion logic

2. **src/hiro.py** (346 lines)
   - `fetch_transactions_page()` - core API call with caching
   - Transaction filtering and batch processing
   - Pagination parameter construction

3. **src/http_utils.py** (144 lines)
   - Caching mechanism with TTL support
   - Retry logic using tenacity library
   - Status code handling for transient failures

4. **src/config.py** (67 lines)
   - Path and API configuration
   - RetryConfig dataclass: backoff parameters
   - Environment variable loading

---

## Key Insights

### 1. Two-Phase Architecture (Most Important)

The backfill uses **two distinct phases** that are tightly coupled:

**Phase 1: _sync_latest_transactions()**
- Fetches **newest** transactions first
- Works **backward in time** (recent → past)
- Stops when: reaches overlap with existing data, OR hits max_pages, OR no more results
- Important: Uses `force_refresh=True` on first API call to bypass cache

**Phase 2: _sync_historical_transactions()**
- Backfills **from oldest known to target date**
- Works **further backward in time** (past → very old)
- Early exit if already have target date (critical efficiency feature!)
- Uses persistent state: `MIN(block_time)` becomes next cursor

**Why two phases?**
- Phase 1 is fast: captures recent activity efficiently
- Phase 2 is thorough: backfills to arbitrary cutoff date
- Together: optimal coverage with minimal API calls

### 2. Pagination Cursor System

The cursor logic is elegant and prevents overlaps:

```
Each page returns results in descending time order (newest first)
Cursor for next page = MIN(timestamps_in_page) - 1 second

Phase 1:
  Page 1: end_time=None → txs from T to T-1000s → cursor = T-1000s - 1
  Page 2: end_time=T-1000s-1 → txs from T-1000s-1 to T-2000s → cursor = T-2000s - 1
  ...continues backward until overlap or empty

Phase 2:
  Starting point = MIN(block_time from DB) - 1
  Continues backward from there
  Same pattern: cursor = min(results) - 1
```

**Critical detail:** Prefers `burn_block_time` over `block_time` because it's canonical blockchain time.

### 3. Resumption is Built-In

The key to automation: **the function is designed for repeated calls**

```python
# Call 1: Fetches recent + hits max_pages
ensure_transaction_history(max_days=180, force_refresh=False)
# Result: DB has 0 → 60 days ago

# Call 2 (seconds later): Continues from where we left off
ensure_transaction_history(max_days=180, force_refresh=False)
# Phase 1: Fetches new recent data (small)
# Phase 2: Continues from 60 days, pushes to 120 days ago
# Result: DB has 0 → 120 days ago

# Call 3: Finishes the backfill
ensure_transaction_history(max_days=180, force_refresh=False)
# Phase 1: Quick (minimal new data)
# Phase 2: Reaches 180-day target, exits early
# Result: DB has 0 → 180 days ago

# Call 4+: Idempotent (no work)
ensure_transaction_history(max_days=180, force_refresh=False)
# Phase 2 checks: MIN(block_time) <= target? Yes! Return immediately.
# Duration: <1 second
```

### 4. DuckDB Cache Schema

```sql
CREATE TABLE transactions (
    tx_id VARCHAR PRIMARY KEY,              -- Unique identifier
    block_time TIMESTAMP,                   -- When tx was mined
    block_height BIGINT,                    -- Stacks block number
    sender_address VARCHAR,                 -- Who sent it
    fee_ustx BIGINT,                        -- Fee in microSTX
    tx_type VARCHAR,                        -- contract-call, token-transfer, etc.
    canonical BOOLEAN,                      -- Only True (canonical txs only)
    tx_status VARCHAR,                      -- Only 'success'
    burn_block_time TIMESTAMP,              -- When in BTC chain (preferred for sorting)
    burn_block_height BIGINT,               -- Bitcoin block number
    microblock_sequence BIGINT,             -- Position in microblock
    ingested_at TIMESTAMP                   -- When we fetched this record
);
```

**Filtering logic:** Only inserts if ALL of these are true:
- `sender_address` exists
- `canonical == True`
- `tx_status == "success"`
- `block_time` is present

### 5. Retry & Timeout Behavior

**HTTP Retry Policy (from http_utils.py):**
- Retryable status codes: 429, 500, 502, 503, 504, 522, 525
- Backoff: exponential from 0.5s to 8.0s
- Max attempts: 5
- If all 5 fail: `TransientHTTPError` propagates up (NOT caught by backfill)

**Request Timeout:** 30 seconds per request (hardcoded in _request_once)

**Important:** The backfill loop does NOT have internal retry—exceptions bubble up to the caller!

### 6. Caching Layers

**Layer 1: HTTP Response Cache (data/raw/*.json)**
- Deterministic key: SHA256(method, URL, params)
- TTL: configurable (300s for fresh, 1800s for stable)
- Used by: hiro.py fetch functions
- Effect: Same API call within TTL window doesn't hit network

**Layer 2: DuckDB Database (data/cache/wallet_metrics.duckdb)**
- Persistent: survives program restarts
- Indexed on: tx_id (primary key)
- Used by: wallet metrics queries
- Effect: Historical data persists across runs

---

## Parameters & Configuration

### Function Parameters

| Parameter | Type | Default | Purpose |
|-----------|------|---------|---------|
| `max_days` | int | required | Days of history to fetch from today |
| `force_refresh` | bool | required | If True, delete all existing txs first |
| `max_pages` | int | 10,000 | Max API pages per single run |

### Important Constants (in wallet_metrics.py)

```python
TRANSACTION_PAGE_LIMIT = 50        # Fixed API page size
DEFAULT_MAX_PAGES = 10_000         # Default page limit
DUCKDB_PATH = Path("data/cache/wallet_metrics.duckdb")
```

### HTTP Retry Config (in config.py)

```python
wait_min_seconds = 0.5             # Min exponential backoff
wait_max_seconds = 8.0             # Max exponential backoff
max_attempts = 5                   # Retry count per request
status_forcelist = (429, 500, 502, 503, 504, 522, 525)
```

---

## Automation Strategy

### Basic Monitoring Loop

```python
while not is_complete(max_days=180):
    try:
        ensure_transaction_history(max_days=180, force_refresh=False)
    except Exception as e:
        log(f"Error: {e}")
        # Continue to next iteration
    
    progress = check_progress()
    log(f"Progress: {progress}")
    sleep(30)
```

### Key Queries for Monitoring

```python
# Check current state
SELECT COUNT(*), MIN(block_time), MAX(block_time) FROM transactions

# Calculate completion
target_time = now() - 180 days
is_complete = MIN(block_time) <= target_time
```

### Deployment Options

1. **Manual:** Run once, check progress
2. **Cron:** Schedule every 6 hours
3. **Systemd:** Continuous monitoring service
4. **Background daemon:** In notebook with monitoring display

---

## Expected Performance

### Time to Complete (wall-clock)

| Target | Time | Notes |
|--------|------|-------|
| 30 days | 5-15 min | Mostly Phase 1 |
| 90 days | 20-60 min | Both phases |
| 180 days | 45-120 min | Heavy Phase 2 |
| 365 days | 2-4 hours | Very heavy Phase 2 |

### Data per Run (varies widely)

First run (to max_days cutoff):
- Rows: ~500K (50 tx/page × 10K pages = max)
- Pages: 1K-10K (depends on target days)
- Duration: 3-120 minutes

Subsequent runs (new data only):
- Rows: Depends on new activity
- Pages: 5-100 (usually small)
- Duration: 1-5 minutes

After completion:
- Rows: 0 (unless new data arrived)
- Pages: 1-5 (just checking)
- Duration: <1 second

---

## Critical Design Decisions

1. **No built-in retry loop:** Backfill exceptions bubble up. The **monitoring script** must handle retries.

2. **State is persistent:** DB cache survives restarts. Multiple runs are idempotent once complete.

3. **Early exit in Phase 2:** If target already reached, Phase 2 returns immediately. This is the critical optimization for incremental updates.

4. **TTL on HTTP cache:** Fresh data (Phase 1) has 300s TTL, but historical (Phase 2) has 1800s. Allows quick re-runs for new data.

5. **Primary key on tx_id:** INSERT OR REPLACE means duplicates are handled gracefully (overwritten with newer ingested_at timestamp).

---

## Files Delivered

All stored in `/Users/alexanderhuth/Code/stx-labs/docs/`:

1. **wallet_backfill_analysis.md** (472 lines)
   - Comprehensive 10-section deep dive
   - Technical reference for developers
   - Covers all mechanics and edge cases

2. **wallet_backfill_quick_ref.md** (311 lines)
   - Quick lookup guide with code snippets
   - ASCII diagrams and examples
   - Ready-to-use query templates

3. **BACKFILL_AUTOMATION_GUIDE.md** (450+ lines)
   - Step-by-step automation guide
   - Production-ready code examples
   - Deployment options and troubleshooting

---

## Next Steps for Implementation

1. **Build progress checker** (uses check_backfill_progress function)
2. **Create backfill loop** (uses run_backfill_until_complete function)
3. **Add monitoring** (log progress, detect stalls, report ETA)
4. **Deploy** (choose manual, cron, or systemd based on your needs)
5. **Test** with small target_days (30 days) before production

All code templates are provided in the automation guide.

---

**Analysis Complete** - Ready to proceed with automation implementation.

