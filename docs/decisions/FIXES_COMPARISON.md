# Notebook Hang Fixes - Detailed Comparison

## Problem Statement

Notebook hangs at Cell 6 (18% progress) for 2-3 minutes due to failing price API calls with exponential backoff retry logic.

## Solution Comparison Matrix

| Aspect | Solution 1: Timeout + Config | Solution 2: Cache-Only | Solution 3: Reduce Retries |
|--------|--------|---------|---------|
| **Hang Time** | 45s (timeout) | 0s | 60-90s |
| **Time to Implement** | 15 min | 5 min | 2 min |
| **Code Changes** | 2 files | 1 file | 1 file |
| **Complexity** | Medium | Low | Very Low |
| **Preserves Prices** | Yes (if fast) | No | Yes (if fast) |
| **Production Ready** | Yes | No | Maybe |
| **Fallback Quality** | Good (placeholder) | Bad (zeros) | Fair |
| **Works Offline** | Yes | Yes | Depends |
| **Notebook Completeness** | High | High | High |
| **Analysis Quality** | Good | Fair | Good |

---

## Detailed Solution Analysis

### Solution 1: Global Timeout + Remove 500 from Retry List

**What it does:**
- Removes HTTP 500 from retry forcelist (fail fast on server errors)
- Adds 3-minute global timeout to price fetching
- Falls back to placeholder prices (0.0) if timeout or error

**Implementation Complexity:** Medium
- Need to add new function to `src/prices.py`
- Need to modify `load_price_panel()` call signature
- Need to modify `src/config.py` retry config

**How it works:**

```
User runs notebook
  ↓
Cell 6: prices.load_price_panel() starts
  ├─ Fetch STX-USD (in thread with 180s timeout)
  │ ├─ CoinGecko fails (404)
  │ ├─ Fall back to Signal21
  │ ├─ Signal21 returns 500
  │ ├─ Don't retry 500 (removed from forcelist)
  │ ├─ Fail fast (< 5 seconds)
  │ └─ Return placeholder (0.0 prices)
  ├─ Fetch BTC-USD (same process)
  └─ Complete in ~45 seconds
  ↓
Cell 7+: Continue with placeholder prices ✓
```

**Advantages:**
- Predictable timing
- Graceful degradation
- Clear error messages
- Can still get prices if APIs are fast
- Production-quality code

**Disadvantages:**
- Requires code changes in 2 files
- Medium implementation effort
- Price data = 0.0 when APIs slow/fail

**When to use:**
- Production environment
- Long-term fix
- Want graceful fallback

---

### Solution 2: Cache-Only Mode

**What it does:**
- Skip all API calls for prices
- Return placeholder 0.0 immediately
- Useful for testing, offline work

**Implementation Complexity:** Low
- Single conditional in `src/prices.py`
- Controlled via environment variable
- No signature changes needed

**How it works:**

```
User sets: PRICE_CACHE_ONLY=1
  ↓
Cell 6: prices.load_price_panel() starts
  ├─ Check PRICE_CACHE_ONLY env var
  ├─ YES → Skip all API calls
  └─ Return placeholder (0.0) immediately (< 1s)
  ↓
Cell 7+: Continue with placeholder prices ✓
```

**Advantages:**
- Fastest (30 seconds per symbol)
- Minimal code changes
- Works offline
- Easy to enable/disable
- Good for testing

**Disadvantages:**
- No price data at all
- Analysis quality poor without prices
- Not suitable for production
- APY calculations invalid

**When to use:**
- Development/testing
- Offline environments
- Quick testing
- Not for actual analysis

---

### Solution 3: Reduce Retry Attempts from 5 to 3

**What it does:**
- Change one number in retry config
- Fail faster if APIs don't respond
- Reduces exponential backoff cycles

**Implementation Complexity:** Very Low
- One-line change in `src/config.py`
- No function changes
- No signature changes

**How it works:**

```
User runs notebook (config.py max_attempts=3)
  ↓
Cell 6: prices.load_price_panel() starts
  ├─ CoinGecko fails (404)
  ├─ Signal21 returns 500
  ├─ Retry: attempt 1, 2, 3 (only 3 instead of 5)
  ├─ Fail after 3 attempts
  ├─ Per-chunk time: ~90s instead of 150s
  └─ Fall back to placeholder
  ↓
Cell 7+: Continue with placeholder prices ✓
```

**Advantages:**
- Simplest implementation (1 line)
- Minimal risk
- Works with existing code
- Better than current (90s vs 150s per chunk)

**Disadvantages:**
- Still slow (might take 2+ min)
- May fail on transient errors
- Not a complete solution
- Still subject to retry pyramid

**When to use:**
- Quick fix while planning better solution
- Supplement to Solution 1
- Testing/development

---

## Hybrid Approach: Solution 1 + Solution 3

**Best of both worlds:**

1. Remove 500 from forcelist (fail fast on server errors)
2. Add global timeout (predictable completion)
3. Optionally reduce max_attempts to 3 (faster overall)

**Timeline after all three:**
- Cell 6: 30-45 seconds (timeout or fast failure)
- Cell 7-12: 30 seconds
- Total: 2 minutes instead of 30+ minutes

**Implementation effort:** 15 minutes total

---

## Testing Plan for Solution 1

### Phase 1: Config Change (2 min)
```bash
# Edit src/config.py line 46
# Remove 500 from status_forcelist

git diff src/config.py
# Should show: - (429, 500, 502, 503, 504, 522)
#              + (429, 502, 503, 504, 522)
```

### Phase 2: Smoke Test (5 min)
```bash
make smoke-notebook
# Watch for hang time reduction
# Expected: ~1 min instead of 2-3 min
# Expected output: warnings about 500 errors, placeholder prices
```

### Phase 3: Code Addition (10 min)
```bash
# Edit src/prices.py
# Add fetch_price_series_with_timeout() function
# Update load_price_panel() to use it

git diff src/prices.py | head -50
# Should show new function definition
```

### Phase 4: Full Run (7 min)
```bash
make notebook
# Watch for full completion
# Expected: 5-7 min total (vs 30+ min before)
# Check outputs: ls -lh out/
```

### Phase 5: Validation
```bash
# Verify cache was created
ls -lh data/cache/prices/
# Should show STX-USD.parquet, BTC-USD.parquet

# Check notebook output
grep -i "warning\|error\|timeout" out/notebook.log | head -20
# Should see price fetching fallback warnings
```

---

## Decision Matrix

Choose solution based on your needs:

**Need it ASAP (< 5 min):** → Solution 2 (Cache-Only)
- Trade: No price data, but notebook runs

**Need good fix (15 min, production-ready):** → Solution 1 (Timeout)
- Trade: Some price data loss, but graceful fallback

**Quick fix while you decide (2 min):** → Solution 3 (Reduce Retries)
- Trade: Still slow, but better than nothing

**Best approach (15 min, comprehensive):** → Solution 1 + 3
- Remove 500 from retry list
- Add global timeout
- Reduce max_attempts to 3
- Result: Fast, reliable, production-quality

---

## Implementation Recommendation

**Immediate Action (2 min):**
```python
# src/config.py line 46
status_forcelist=(429, 502, 503, 504, 522),  # Removed 500
```

**Short-term (15 min):**
```python
# src/prices.py - Add timeout wrapper function
# Use threading.Thread with timeout
# Fall back to placeholder on timeout
```

**Why this order:**
1. Quick fix buys time (reduces hang to ~90s)
2. Proper fix eliminates hang entirely (45s with timeout)
3. Combined approach gives best results

**Expected impact:**
- Immediate: Notebook faster, still might hang
- After short-term: Notebook reliable, 2-min total
- User experience: No more perceived "hanging"

