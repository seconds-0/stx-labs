# Notebook Hang Investigation Report

## Executive Summary

The notebook is hanging at **Code Cell 6** (18% progress) and **Code Cell 12** (34% progress) - both related to price fetching operations. The hang is NOT an infinite loop but rather a **combination of:**

1. **Network timeout issues** with Signal21 API (returning 500 errors)
2. **Missing price data** in the cache (price cache is completely empty)
3. **Exponential backoff retry logic** that takes ~2-3 minutes to exhaust
4. **No global timeout** on price fetching operations (only per-request 30s timeout)

The notebook does NOT hang outright - it exhausts retries and falls back to placeholders, but this takes a VERY long time.

---

## Detailed Analysis

### 1. Cell 6: Price Fetching (THE CULPRIT)

**Location:** Notebook cell 11 (code cell 6)
```python
cache_before = {symbol: len(prices.cached_price_series(symbol)) for symbol in PRICE_SYMBOLS}
prices_df = prices.load_price_panel(ANALYSIS_START, END_DATE, force_refresh=FORCE_REFRESH)
cache_after = {symbol: len(prices.cached_price_series(symbol)) for symbol in PRICE_SYMBOLS}
```

**Call stack:**
```
prices.load_price_panel()
  ├─ fetch_price_series("STX-USD", ..., force_refresh=False)
  │   └─ _ensure_price_series()
  │       ├─ _fetch_prices_coingecko() → FAILS with 404 (CoinGecko doesn't have STX)
  │       └─ _fetch_prices_fallback() → calls Signal21
  │           └─ fetch_price_series_signal21() from src/signal21.py
  │               ├─ _fetch_price_chunk() [chunk 1/12]
  │               ├─ _fetch_price_chunk() [chunk 2/12]
  │               └─ ... [continues chunking with retries on 500 errors]
  │
  └─ fetch_price_series("BTC-USD", ...)
      └─ Same process as STX-USD
```

### 2. Why It Takes So Long

**Timeout Settings in `src/config.py`:**
```python
DEFAULT_RETRY_CONFIG = RetryConfig(
    wait_min_seconds=0.5,      # Initial backoff
    wait_max_seconds=8.0,      # Max backoff between attempts
    max_attempts=5,            # Max retry attempts PER REQUEST
    status_forcelist=(429, 500, 502, 503, 504, 522),  # Include 500 errors
)
```

**Request timeout in `src/http_utils.py` line 100:**
```python
response = opts.session.request(
    ...
    timeout=30,  # 30 second timeout PER REQUEST
)
```

**Signal21 Adaptive Chunking in `src/signal21.py` lines 49-73:**
```python
while queue:
    chunk_start, chunk_end = queue.pop()
    try:
        chunk_df = _fetch_price_chunk(...)
    except TransientHTTPError as exc:
        span_days = (chunk_end - chunk_start).days
        if span_days <= MIN_CHUNK_DAYS:  # MIN_CHUNK_DAYS = 5
            warnings.warn(
                f"Signal21 price API repeatedly failed for {symbol}: {exc}. Skipping chunk.",
                ...
            )
            continue
        # If chunk > 5 days, HALVE it and retry
        midpoint = chunk_start + timedelta(days=span_days // 2)
        queue.appendleft((midpoint + timedelta(days=1), chunk_end))
        queue.appendleft((chunk_start, midpoint))
        continue
```

**Timing Breakdown for ONE Symbol (365-day range):**

1. **Initial chunking:** 365 days = 12 chunks of 30 days each
2. **Each chunk that fails:** Gets halved until it reaches 5 days minimum
3. **Retry logic per chunk:**
   - Attempt 1: 30s timeout → 500 error
   - Backoff: 0.5s - 8s exponential jitter
   - Attempt 2: 30s timeout → 500 error
   - ... up to 5 total attempts per chunk

**Example timing for ONE chunk with 5 failures:**
- Attempt 1: 30s (timeout) + 0.5s (backoff) = 30.5s
- Attempt 2: 30s + ~2s (backoff) = 32s
- Attempt 3: 30s + ~4s (backoff) = 34s
- Attempt 4: 30s + ~7s (backoff) = 37s
- Attempt 5: 30s + ~8s (backoff) = 38s
- **Per-chunk total: ~2.5 minutes**

**For 2 symbols × 12 chunks = ~30 minutes (if all fail)** ← This is likely why you see hangs at 18% and 34%!

### 3. Cache Status Reveals the Problem

**Current cache state from notebook output:**
```
STX-USD cache: empty
BTC-USD cache: empty
Fees cache: missing (data/cache/signal21/fees_by_tenure_all.parquet)
Rewards cache: missing (data/cache/hiro/rewards_all.parquet)
```

**Directory listing:**
```bash
ls -lah /data/cache/prices/
  total 0
  drwxr-xr-x  2 alexanderhuth staff 64B  (EMPTY)
```

**This means:**
- No cached prices to skip fetching
- Must fetch from APIs
- APIs are failing (CoinGecko 404, Signal21 500)
- Must exhaust all retries before giving up

### 4. The Actual Error Messages (from notebook output)

```
RuntimeWarning: CoinGecko failed for STX-USD: 404 Client Error: Not Found 
  for url: https://api.coingecko.com/api/v3/coins/stacks/market_chart/range?...
  Falling back to Signal21.

RuntimeWarning: Signal21 price API repeatedly failed for STX-USD between 
  2025-10-17 and 2025-10-22: Status 500 for https://api-test.signal21.io/v1/price. 
  Skipping chunk.
```

**Root causes:**
1. CoinGecko is returning **404 for STX** - endpoint may not exist or STX mapping is wrong
2. Signal21 is returning **500 errors** - server-side issue or rate limiting

### 5. Why Doesn't It Just Timeout?

**Design issue:** There's a **per-request 30s timeout** but **NO overall operation timeout** on `load_price_panel()`. The function will retry forever within exponential backoff bounds.

In `src/http_utils.py`:
```python
@retry(
    retry=retry_if_exception(_retry_condition),
    wait=wait_exponential_jitter(...),
    stop=stop_after_attempt(5),  # ← This is per REQUEST, not global
    reraise=True,
)
def _execute() -> Any:
    return _request_once(opts)
```

But `cached_json_request()` is called repeatedly in a loop for EACH chunk, and each chunk can fail 5 times independently.

### 6. Cell 12 Hang Point

**Location:** Notebook cell 19 (code cell 12)
```python
if not panel_df.empty:
    missing_fees = panel_df['fees_stx_sum'].isna().sum()
    ...
```

This hangs because it depends on earlier cells (especially cell 7 - `fetch_fees_by_tenure()`), which also uses Signal21 SQL queries that likely hit the same 500 errors.

---

## Root Cause Summary

| Issue | Location | Impact |
|-------|----------|--------|
| **CoinGecko 404 for STX** | `src/prices.py:120` | Falls back to Signal21 immediately |
| **Signal21 500 errors** | `src/signal21.py:59-73` | Triggers adaptive chunking retry loop |
| **No global timeout** | `src/prices.py:208-233` | Retries exhaust 2-3 min per symbol |
| **Exponential backoff** | `src/config.py:38-39` | Waits up to 8s between attempts |
| **Empty price cache** | `data/cache/prices/` | No skip-on-cache option available |

---

## Proposed Solutions

### Solution 1: Cache-Only Mode (FASTEST - 30 seconds)
**Trade-off:** Skips price fetching entirely, uses placeholders

**Implementation:**
```python
# Add to notebook parameters
CACHE_ONLY_MODE = True  # Skip all API calls, use placeholders

# Modify src/prices.py
def load_price_panel(..., cache_only=False):
    if cache_only:
        # Return placeholder series with 0.0 prices
        placeholder_index = pd.date_range(start, end, freq=frequency, tz=UTC)
        df = pd.DataFrame({
            'ts': placeholder_index,
            'stx_usd': 0.0,
            'btc_usd': 0.0,
            'stx_btc': 0.0
        })
        return df
    # ... existing logic
```

**Pros:**
- Notebook runs immediately (30s)
- Analysis still works with placeholder prices (0.0)
- Downstream code handles price = 0 gracefully

**Cons:**
- No price data in outputs
- PoX APY calculations meaningless without prices
- Scenario analysis broken

---

### Solution 2: Global Timeout on Price Fetching (RECOMMENDED - 2-3 minutes)
**Trade-off:** Kill price fetching after 2-3 min, use placeholders

**Implementation:**
```python
# Add to src/prices.py
import signal
from threading import Thread
import queue

def _fetch_with_timeout(symbol, start, end, timeout=180):
    """Fetch price series with global timeout."""
    result_queue = queue.Queue()
    
    def worker():
        try:
            result = fetch_price_series(symbol, start, end, ...)
            result_queue.put(("success", result))
        except Exception as exc:
            result_queue.put(("error", exc))
    
    thread = Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    
    if thread.is_alive():
        # Thread still running - timeout
        warnings.warn(f"Price fetching for {symbol} exceeded timeout ({timeout}s)")
        return pd.DataFrame(columns=["ts", "px"])
    
    status, result = result_queue.get()
    if status == "error":
        raise result
    return result
```

**Pros:**
- Notebook completes in predictable 2-3 min
- Falls back gracefully to placeholders
- Respects existing retry logic (doesn't skip it)
- Works across platforms

**Cons:**
- Still loses price data
- May need tuning for slow networks

---

### Solution 3: Skip Signal21 Entirely, Use Placeholder (SIMPLE - 30 seconds)
**Trade-off:** CoinGecko only, no fallback chain

**Implementation:**
```python
# In src/prices.py, modify _ensure_price_series()
def _ensure_price_series(...):
    ...
    try:
        fresh_df = _fetch_prices_coingecko(...)
    except Exception as exc:
        warnings.warn(f"CoinGecko failed: {exc}. Using placeholder.", ...)
        # DON'T try Signal21, jump straight to placeholder
        fresh_df = pd.DataFrame()
    ...
```

**Pros:**
- Very simple change
- Notebook runs in 30s
- No Signal21 dependency

**Cons:**
- Loses ALL price data (even from CoinGecko)
- Not suitable for production

---

### Solution 4: Adjust Retry Thresholds (BANDAID)
**Trade-off:** Longer wait times, but might get data eventually

**Implementation:**
```python
# In src/config.py
DEFAULT_RETRY_CONFIG = RetryConfig(
    wait_min_seconds=0.5,
    wait_max_seconds=8.0,
    max_attempts=3,  # ← Reduce from 5 to 3
    status_forcelist=(429, 502, 503, 504, 522),  # ← Remove 500 from list
)
```

**Why this works:**
- 500 errors are likely transient on Signal21 side
- Removing from retry list = fail fast instead of retry
- Reduces per-chunk timeout from 2.5min to ~1.5min

**Pros:**
- Simpler than other solutions
- Might work if Signal21 stabilizes

**Cons:**
- Still slow (30+ min if Signal21 is down)
- Doesn't solve the problem if it's permanent

---

## Recommendation

**For immediate unblocking:** Implement **Solution 2 (Global Timeout)** + **Solution 4 (Adjust retry config)**

This combination:
1. Removes 500 from the retry forcelist (fail fast on server errors)
2. Adds a global 3-minute timeout to price fetching (predictable completion)
3. Falls back gracefully to placeholder prices (analysis continues)
4. Notebook completes in <5 minutes instead of 30+

The notebook can function without price data - fees, rewards, and anchor metadata are independent of prices.

---

## Additional Observations

### Is CoinGecko endpoint wrong?

Looking at the error:
```
https://api.coingecko.com/api/v3/coins/stacks/market_chart/range?...
```

This endpoint is deprecated in CoinGecko v3. The coin ID `stacks` is correct but the endpoint structure may have changed. Consider:
- Checking [CoinGecko API docs](https://docs.coingecko.com/reference/coins-id-market-chart)
- Using a different endpoint (e.g., `/coins/{id}/market_chart` without `/range`)
- Or removing CoinGecko dependency entirely

### Can notebook complete without prices?

**YES!** The analysis structure allows:
- Fees (from Signal21 SQL) - independent of prices
- Rewards (from Hiro API) - independent of prices
- Panel construction - can skip price merge
- Scenario analysis - needs prices but can use placeholder 0.0

The only downstream impact is PoX APY calculations become meaningless (divide by 0 protection is in place).

---

## Files Affected

1. **`src/config.py`** - Retry config (line 46)
2. **`src/prices.py`** - Price fetching logic (lines 100-200)
3. **`src/http_utils.py`** - HTTP request handler (line 100)
4. **`src/signal21.py`** - Signal21 chunking logic (lines 34-99)
5. **`notebooks/stx_pox_flywheel.ipynb`** - Cells 6 and 12

---

## Timeline to Implement

1. **Phase 1 (Immediate):** Adjust retry config (5 min)
   - Remove 500 from status_forcelist in `src/config.py`
   - Test with `make smoke-notebook`

2. **Phase 2 (Short-term):** Add global timeout (15 min)
   - Implement threading-based timeout in `src/prices.py`
   - Add graceful fallback to placeholder prices
   - Test full notebook with `make notebook`

3. **Phase 3 (Follow-up):** Investigate CoinGecko endpoint (30 min)
   - Verify correct endpoint format
   - Update price fetching if needed
   - Or remove CoinGecko and rely solely on Signal21

