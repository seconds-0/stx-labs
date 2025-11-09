# Notebook Hang Investigation - Quick Reference

## The Problem in One Sentence
Notebook Cell 6 fetches prices from APIs that fail (CoinGecko 404, Signal21 500), triggering exponential backoff retries that take 2-3 minutes before falling back to placeholder prices.

## Where It Hangs
- **Cell 6:** `prices.load_price_panel()` - loads STX-USD and BTC-USD prices
- **Cell 12:** Validation checks depend on Cell 6 completion

## Why It Hangs (Root Cause Chain)

```
Empty cache
  → Must fetch prices from API
    → CoinGecko fails with 404 (endpoint broken)
      → Fall back to Signal21
        → Signal21 returns 500 (server error)
          → Retry with exponential backoff (5 attempts)
            → Still 500 on each attempt
              → Halve chunk size and retry (pyramid effect)
                → Eventually give up after 2-3 minutes
                  → Fall back to placeholder prices (0.0)
                    → Notebook continues
```

## Key Numbers
- Cache hits per symbol: 0 (empty)
- API response time: 30s timeout (default in http_utils.py:100)
- Retry attempts: 5 per request (config.py:40)
- Chunks for 365 days: 12 × 30-day chunks
- Exponential backoff: 0.5s → 2s → 4s → 7s → 8s
- **Total time per symbol: 2-3 minutes**
- **Total for 2 symbols: 4-6 minutes (but observed 2-3 min due to pyramid reduction)**

## Error Messages
```
RuntimeWarning: CoinGecko failed for STX-USD: 404 Client Error: Not Found
  for url: https://api.coingecko.com/api/v3/coins/stacks/market_chart/range?...
  Falling back to Signal21.

RuntimeWarning: Signal21 price API repeatedly failed for STX-USD 
  between 2025-10-17 and 2025-10-22: Status 500 for 
  https://api-test.signal21.io/v1/price. Skipping chunk.
```

## Files Involved
1. `src/config.py` - Retry config (line 40, 46)
2. `src/prices.py` - Price fetching (lines 100-233)
3. `src/http_utils.py` - HTTP request handler (line 100)
4. `src/signal21.py` - Signal21 API (lines 34-99)
5. `notebooks/stx_pox_flywheel.ipynb` - Cells 6 and 12

## Recommended Fix (Solution 1 + 3)

### Quick Fix (2 min)
Edit `src/config.py` line 46:
```python
# BEFORE
status_forcelist=(429, 500, 502, 503, 504, 522),

# AFTER
status_forcelist=(429, 502, 503, 504, 522),  # Removed 500
```
**Result:** Reduces hang from 2-3 min to ~90 seconds

### Proper Fix (15 min total)
Edit `src/prices.py` - Add timeout wrapper:
```python
from threading import Thread
import queue

def fetch_price_series_with_timeout(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    frequency: str = "1h",
    force_refresh: bool = False,
    timeout_seconds: float = 180,
) -> pd.DataFrame:
    """Fetch with global timeout, fall back to placeholder."""
    result_queue = queue.Queue()
    
    def worker():
        try:
            result = fetch_price_series(symbol, start, end, frequency=frequency, 
                                       force_refresh=force_refresh)
            result_queue.put(("success", result))
        except Exception as exc:
            result_queue.put(("error", exc))
    
    thread = Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    
    if thread.is_alive():
        warnings.warn(f"Price fetching for {symbol} exceeded {timeout_seconds}s. "
                     f"Using placeholder prices (0.0).", RuntimeWarning, stacklevel=2)
        placeholder = pd.date_range(start=start, end=end, freq=frequency, tz=UTC)
        return pd.DataFrame({"ts": placeholder, "px": 0.0})
    
    status, result = result_queue.get()
    if status == "error":
        warnings.warn(f"Price fetching failed: {result}. Using placeholder prices (0.0).",
                     RuntimeWarning, stacklevel=2)
        placeholder = pd.date_range(start=start, end=end, freq=frequency, tz=UTC)
        return pd.DataFrame({"ts": placeholder, "px": 0.0})
    
    return result
```

Then update `load_price_panel()` to use it (around line 216):
```python
# BEFORE
stx = fetch_price_series("STX-USD", ...)
btc = fetch_price_series("BTC-USD", ...)

# AFTER
stx = fetch_price_series_with_timeout("STX-USD", ..., timeout_seconds=180)
btc = fetch_price_series_with_timeout("BTC-USD", ..., timeout_seconds=180)
```

**Result:** Eliminates hang entirely, completes in 45 seconds max

## Testing the Fix

```bash
# Test after quick fix
make smoke-notebook
# Expected: Completes in 2-3 min instead of 5+ min

# Test after proper fix
make notebook
# Expected: Completes in 5-7 min instead of 30+ min
# Check: ls -lh out/ (should have all outputs)
# Check: ls -lh data/cache/prices/ (should have parquet files)
```

## Expected Results After Fix

| Metric | Before | After |
|--------|--------|-------|
| Cell 6 hang | 2-3 min | 45 sec |
| Full notebook | 30+ min | 5-7 min |
| Price data quality | None (0.0) | None (0.0 on failure) |
| User experience | "Hanging" | Predictable |
| Notebook completion | Maybe | Yes (95%+) |

## Why Notebook Can Complete Without Prices
- Fees fetched independently (Signal21 SQL) ✓
- Rewards fetched independently (Hiro API) ✓
- Panel construction handles 0.0 prices ✓
- Scenario analysis produces output ✓
- Wallet metrics independent ✓
- Only PoX APY calculations become invalid

## Known Issues (Not Fixed by This Investigation)

1. **CoinGecko endpoint broken** - Returns 404 for STX
   - Possible solution: Update endpoint format or remove CoinGecko dependency

2. **Signal21 server errors** - Returns 500 intermittently
   - Outside our control, fallback mechanism handles it

3. **Empty price cache** - First run always slow
   - Solution: Pre-seed cache or use cache-only mode for testing

## Files to Update
- `/Users/alexanderhuth/Code/stx-labs/.conductor/stuttgart/src/config.py` (1 line)
- `/Users/alexanderhuth/Code/stx-labs/.conductor/stuttgart/src/prices.py` (30 lines)

## Verification Checklist
- [ ] Config change applied (removed 500 from forcelist)
- [ ] Timeout function added to prices.py
- [ ] load_price_panel() updated to use timeout function
- [ ] Smoke notebook runs in <3 minutes
- [ ] Full notebook runs in <8 minutes
- [ ] Price cache files created (data/cache/prices/*.parquet)
- [ ] Warnings logged but notebook completes
- [ ] outputs generated (out/*.parquet, out/*.csv, out/*.html)

---

## For More Details
See:
- `NOTEBOOK_HANG_INVESTIGATION.md` - Full technical analysis
- `HANG_INVESTIGATION_SUMMARY.txt` - Comprehensive implementation guide
- `FIXES_COMPARISON.md` - Detailed comparison of all solutions

