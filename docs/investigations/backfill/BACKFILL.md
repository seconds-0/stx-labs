# Wallet Transaction History Backfill

## Overview

The wallet transaction history backfill process populates the local DuckDB cache with historical transaction data from the Hiro API. This data is essential for accurate wallet growth metrics in dashboards.

**Why backfill matters:**
- Dashboard metrics (wallet counts, cohorts, retention) rely on transaction history
- Without backfill, dashboards only show recent activity (last 7-30 days)
- Full 180-day backfill provides complete picture of wallet growth trends

**What gets backfilled:**
- All Stacks blockchain transactions via Hiro `/extended/v1/tx` endpoint
- Stored in `data/cache/wallet_metrics.duckdb` (DuckDB database)
- Also caches raw HTTP responses in `data/raw/` for faster re-runs

## Quick Start

### Option 1: Automated Backfill (Recommended)

```bash
# Check current status
make backfill-status

# Run backfill in foreground (can interrupt with Ctrl+C, safe to restart)
make backfill-wallet

# OR run in background (recommended for long backfills)
make backfill-bg        # Launch in background
make backfill-tail      # Monitor logs (Ctrl+C to stop following)
make backfill-status    # Check progress anytime
make backfill-stop      # Stop background process if needed
```

### Option 2: Manual Execution

```bash
# Direct script execution with default 180 days
python scripts/backfill_wallet_history.py

# Custom target (e.g., 365 days)
python scripts/backfill_wallet_history.py --target-days 365

# With more iterations and longer delay
python scripts/backfill_wallet_history.py --target-days 365 --max-iterations 100 --delay 10
```

### Option 3: tmux/screen Session (For Very Long Runs)

```bash
# Start tmux session
tmux new -s wallet-backfill

# Run backfill
make backfill-wallet TARGET_DAYS=365

# Detach: Ctrl+B then D
# Reattach: tmux attach -t wallet-backfill
```

## How It Works

### Two-Phase Architecture

The backfill uses a smart two-phase approach:

1. **Phase 1 (Recent):** Fetches recent transactions working backward from today
   - Fast initial population
   - Gets you operational quickly

2. **Phase 2 (Historical):** Backfills older data to reach target date
   - Runs automatically after Phase 1 completes
   - Picks up from oldest transaction in database

### Automatic Resumption

The backfill script is **idempotent** and **resumable**:
- Can be safely interrupted at any time (Ctrl+C)
- Always picks up where it left off
- Checks database state before each iteration
- Stops automatically when target date is reached

### Iteration Pattern

Each iteration:
1. Checks current database min/max timestamps
2. Calls `wallet_metrics.ensure_transaction_history()`
3. Monitors progress (rows, wallets, date coverage)
4. Repeats until target date reached or max iterations hit
5. Provides detailed logging throughout

## Understanding Progress

### Status Output

```bash
$ make backfill-status
================================================================================
WALLET BACKFILL STATUS
================================================================================
Database: data/cache/wallet_metrics.duckdb
Size: 8.3 MB

Total transactions: 37,967
Unique wallets: 1,769

Earliest transaction: 2025-10-30 22:12:26 UTC
Latest transaction: 2025-11-07 18:21:16 UTC

Target: 180 days back to 2025-05-11
Coverage: 7 days (3.9%)

⏳ BACKFILL IN PROGRESS - 172 days remaining
```

### Interpreting Results

- **Total transactions**: Row count in database
- **Unique wallets**: Distinct sender addresses seen
- **Earliest transaction**: How far back you've backfilled
- **Coverage**: Progress toward target (days and percentage)
- **Status icons**:
  - ⏳ = In progress, keep running
  - ✅ = Complete, target date reached
  - ❌ = Not started or empty database

## Expected Performance

### Timing Estimates

| Target Days | Expected Duration | Iterations | Database Size |
|-------------|-------------------|------------|---------------|
| 30 days     | 5-15 minutes      | 2-5        | ~3-5 MB       |
| 90 days     | 20-60 minutes     | 5-15       | ~10-20 MB     |
| 180 days    | 45-120 minutes    | 10-30      | ~20-50 MB     |
| 365 days    | 2-4 hours         | 20-60      | ~50-100 MB    |

**Factors affecting speed:**
- Hiro API rate limits and response times
- Network latency
- Transaction volume in target period
- HTTP cache hits (faster on re-runs)

### Progress Monitoring

During backfill, you'll see output like:

```
================================================================================
ITERATION 3: Starting backfill (max_days=180)
================================================================================

✓ Iteration 3 completed in 142.3s

Current status: Rows: 45,123 | Unique wallets: 2,345 | Earliest transaction: 2025-10-15 14:22:11
Progress: 23/180 days (12.8%)

Waiting 5s before next iteration...
```

## Configuration Options

### Make Variables

```bash
# Change target days (default: 180)
make backfill-wallet TARGET_DAYS=365
make backfill-status TARGET_DAYS=365

# Logs and PID files (usually don't need to change)
make backfill-bg BACKFILL_LOG=my_backfill.log
```

### Script Arguments

```bash
python scripts/backfill_wallet_history.py --help

Options:
  --target-days DAYS      Number of days to backfill (default: 180)
  --max-iterations N      Maximum iterations before stopping (default: 50)
  --force-refresh         Ignore HTTP cache, always fetch fresh data
  --delay SECONDS         Delay between iterations (default: 5)
```

### Common Scenarios

```bash
# Quick 30-day backfill (testing)
python scripts/backfill_wallet_history.py --target-days 30

# Full year with high iteration limit
python scripts/backfill_wallet_history.py --target-days 365 --max-iterations 100

# Force refresh (bypass HTTP cache)
python scripts/backfill_wallet_history.py --force-refresh

# Faster iterations (use cautiously, may hit rate limits)
python scripts/backfill_wallet_history.py --delay 2
```

## Troubleshooting

### Problem: Backfill stops before reaching target

**Symptoms:**
- Script completes but shows "MAX ITERATIONS REACHED"
- Target date not yet reached

**Solutions:**
```bash
# Just re-run - it will resume from where it stopped
make backfill-wallet

# Or increase max iterations
python scripts/backfill_wallet_history.py --max-iterations 100
```

### Problem: API errors or timeouts

**Symptoms:**
- "⚠ Consecutive failures: 3/3"
- Script stops after multiple failed attempts

**Solutions:**
1. **Wait and retry** - Hiro API may be temporarily unavailable
2. **Check API key** - Ensure `HIRO_API_KEY` is set in `.env`
3. **Network issues** - Verify internet connectivity
4. **Increase delay** - Give API more breathing room:
   ```bash
   python scripts/backfill_wallet_history.py --delay 10
   ```

### Problem: Database locked error

**Symptoms:**
- "database is locked" error message

**Solutions:**
- Ensure only one backfill process is running at a time
- Close any open DuckDB connections (JupyterLab notebooks, other scripts)
- Check for zombie processes: `ps aux | grep backfill`

### Problem: Slow progress

**Symptoms:**
- Each iteration takes >5 minutes
- Very small incremental progress

**Possible causes:**
1. **API rate limiting** - Normal, just takes time
2. **Cache misses** - First run is always slower
3. **Network latency** - Check internet speed
4. **Low transaction volume** - Older periods may have fewer transactions

**What to do:**
- Be patient, subsequent runs will be faster (HTTP cache)
- Consider running in background: `make backfill-bg`
- Monitor but don't interrupt unnecessarily

### Problem: Completion status but dashboards show low numbers

**Symptoms:**
- Status shows "✅ BACKFILL COMPLETE"
- But dashboards show suspiciously low wallet counts (<100)

**Solutions:**
```bash
# Regenerate dashboards with full refresh
python scripts/build_dashboards.py --force-refresh

# Or run full notebook
make smoke-notebook
```

## Integration with Dashboards

### After Backfill Completes

Once the backfill reaches your target date:

```bash
# Option 1: Quick dashboard rebuild (30 seconds)
python scripts/build_dashboards.py

# Option 2: Force full refresh (3-5 minutes, more accurate)
python scripts/build_dashboards.py --force-refresh

# Option 3: Full notebook run (45-60 minutes, all analysis)
make notebook
```

### Dashboard Output

Dashboards will be generated at:
- `public/wallet/index.html` - Wallet growth metrics
- `public/macro/index.html` - Macro correlations
- `public/index.html` - Landing page

### Verifying Dashboard Data

After regenerating dashboards, check:
1. **Wallet counts** - Should show hundreds to thousands (not <100)
2. **Date ranges** - Should cover full backfill period
3. **Cohort analysis** - Should show retention across multiple cohorts

## Advanced Usage

### Running Multiple Backfills in Parallel

**Not recommended** - can cause database locking issues and waste API calls.

If you absolutely need parallel execution:
1. Use different target date ranges
2. Modify scripts to use separate database files
3. Merge databases manually afterward (advanced)

### Custom Date Ranges

The backfill always works backward from today. To backfill a specific historical range:

```python
# Custom script approach (advanced)
from src import wallet_metrics
from datetime import datetime, timedelta, timezone

# Calculate custom max_days
target_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
max_days = (datetime.now(timezone.utc) - target_date).days

wallet_metrics.ensure_transaction_history(max_days=max_days)
```

### Monitoring via Code

```python
# Check status programmatically
import duckdb
from pathlib import Path

db_path = Path("data/cache/wallet_metrics.duckdb")
conn = duckdb.connect(str(db_path), read_only=True)

result = conn.execute("""
    SELECT
        COUNT(*) as rows,
        COUNT(DISTINCT sender_address) as wallets,
        MIN(block_time) as earliest,
        MAX(block_time) as latest
    FROM transactions
""").fetchone()

print(f"Rows: {result[0]:,}")
print(f"Wallets: {result[1]:,}")
print(f"Range: {result[2]} to {result[3]}")
```

## Files and Artifacts

### Created by Backfill

```
data/
├── cache/
│   ├── wallet_metrics.duckdb          # Main DuckDB database (2-100 MB)
│   └── wallet_metrics/
│       └── first_seen_wallets.parquet # Wallet first-seen cache
└── raw/
    └── hiro_transactions_*.json        # HTTP cache (transient, can delete)

out/
├── backfill.log                        # Background execution log
└── backfill.pid                        # Background process PID
```

### Cache Management

```bash
# Clear HTTP cache only (forces fresh API calls)
rm -rf data/raw/hiro_transactions_*.json

# Clear DuckDB (start backfill from scratch)
rm -f data/cache/wallet_metrics.duckdb

# Full clean (WARNING: loses all cached data)
make clean
```

## Best Practices

1. **Run in background** for long backfills (>30 days)
2. **Check status regularly** but don't interrupt unnecessarily
3. **Let it complete** - interrupting and restarting wastes API calls
4. **Monitor logs** - look for error patterns, not just completion
5. **Verify dashboards** - always check dashboard output after backfill
6. **Use HTTP cache** - don't force-refresh unless necessary
7. **Be patient** - 180-day backfill can take 1-2 hours, that's normal

## Related Documentation

- `README.md` - Project overview and quick start
- `CLAUDE.md` - Agent instructions and architecture
- `docs/wallet_backfill_analysis.md` - Deep technical reference (from Explore agent)
- `docs/BACKFILL_AUTOMATION_GUIDE.md` - Detailed automation patterns
- `src/wallet_metrics.py` - Implementation source code

## Getting Help

If you encounter issues not covered here:

1. Check logs: `tail -50 out/backfill.log`
2. Check database status: `make backfill-status`
3. Review error messages for specific API errors
4. Consult `docs/wallet_backfill_analysis.md` for technical details
5. Check `.env` file has `HIRO_API_KEY` set
6. Verify `make setup` was run successfully

## Quick Reference

```bash
# Essential commands
make backfill-status    # Check progress
make backfill-wallet    # Run backfill (foreground)
make backfill-bg        # Run backfill (background)
make backfill-tail      # Monitor logs
make backfill-stop      # Stop background process

# After completion
python scripts/build_dashboards.py --force-refresh

# Clean start
rm -f data/cache/wallet_metrics.duckdb
make backfill-wallet
```
