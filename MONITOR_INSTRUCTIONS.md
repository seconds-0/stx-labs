# Active Backfill Monitoring

## ✅ Backfill Status

**Your backfill is currently RUNNING:**
- Process ID: 75753
- Target: 180 days of transaction history
- Log file: `out/backfill.log`

## 🖥️ Start the Monitor (in a second terminal)

Open a new terminal window/tab and run:

```bash
cd /Users/alexanderhuth/Code/stx-labs
python scripts/monitor_backfill.py
```

### Monitor Features

The monitor displays:
- ✅ **Real-time progress bar** with percentage complete
- 📊 **Live database stats** (rows, wallets, date coverage)
- ⏱️ **Time elapsed** and estimated time remaining
- 📝 **Recent log entries** from the backfill process
- 🔄 **Auto-refresh** every 10 seconds
- 🎨 **Color-coded output** for easy reading

### Monitor Options

```bash
# Default monitoring (refreshes every 10s)
python scripts/monitor_backfill.py

# Faster refresh (every 5s)
python scripts/monitor_backfill.py --refresh-interval 5

# Custom target days
python scripts/monitor_backfill.py --target-days 180

# Combined
python scripts/monitor_backfill.py --target-days 180 --refresh-interval 5
```

### Stop Monitoring

Press `Ctrl+C` to stop the monitor display.

**Note:** Stopping the monitor does NOT stop the backfill - it only stops displaying the updates. The backfill continues running in the background.

## 📊 Quick Status Check (without monitor)

If you just want a one-time status check:

```bash
make backfill-status
```

## 📜 View Raw Logs

To see the raw backfill output:

```bash
# Follow logs in real-time
tail -f out/backfill.log

# View last 50 lines
tail -50 out/backfill.log

# View all logs
less out/backfill.log
```

## 🛑 Stop Backfill

If you need to stop the backfill:

```bash
# Option 1: Using make
make backfill-stop

# Option 2: Kill by PID
kill 75753

# Option 3: Kill all backfill processes
pkill -f backfill_wallet_history.py
```

**Safe to restart:** The backfill can be stopped at any time and will resume from where it left off when restarted.

## 🔄 Restart Backfill (if stopped)

```bash
# Foreground
make backfill-wallet

# Background (recommended)
make backfill-bg
```

## Expected Timeline

For 180-day backfill:
- **Duration:** 45-120 minutes (typically ~1 hour)
- **Iterations:** 10-30 iterations
- **Final DB size:** ~20-50 MB
- **Rate:** ~3-10 MB per 30 days of history

Progress updates appear after each iteration (typically every 2-5 minutes).

## After Completion

Once the monitor shows "✓ BACKFILL COMPLETE":

1. **Stop the monitor** (Ctrl+C)
2. **Regenerate dashboards:**
   ```bash
   python scripts/build_dashboards.py --force-refresh
   ```
3. **View results:**
   - Open `public/wallet/index.html` in browser
   - Check that wallet counts are in the hundreds/thousands

## Troubleshooting

### Monitor shows "Database not yet created"
- Normal for first minute while backfill initializes
- Wait 30-60 seconds and the database will appear

### Monitor shows "No log output yet"
- Log file may be buffering (Python buffers stdout by default)
- Check if process is running: `ps -p 75753`
- Monitor will update once data starts flowing

### Monitor shows "NOT RUNNING"
- Backfill may have completed
- Run `make backfill-status` to check
- Or check logs: `tail out/backfill.log`

### Progress seems slow
- Normal - each iteration can take 2-5 minutes
- API rate limiting and network latency affect speed
- Subsequent runs are faster due to HTTP caching

## Files and Locations

```
out/
├── backfill.log    # Full backfill output log
└── backfill.pid    # Process ID file

data/cache/
└── wallet_metrics.duckdb  # Growing database (watch size increase)

scripts/
├── backfill_wallet_history.py   # Main backfill script
├── check_backfill_status.py     # Quick status checker
└── monitor_backfill.py           # Real-time monitor (YOU RUN THIS)
```

## Quick Commands Summary

```bash
# In second terminal - START THE MONITOR
python scripts/monitor_backfill.py

# One-time status check
make backfill-status

# View raw logs
tail -f out/backfill.log

# Stop monitoring (Ctrl+C)
# Stop backfill
make backfill-stop

# Restart backfill
make backfill-bg
```

---

**Current Status:** ✅ Backfill is RUNNING (PID 75753)

**Next Step:** Run the monitor in a second terminal:
```bash
python scripts/monitor_backfill.py
```
