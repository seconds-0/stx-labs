# Uninterruptible Backfill Guide - Tmux Edition

**Purpose**: Run 365-day wallet transaction history backfill without interruption, even if SSH disconnects or terminal closes.

**TL;DR**: Use `make backfill-tmux` to start an uninterruptible backfill session that survives SSH disconnects and prevents macOS sleep.

---

## Quick Start (Copy-Paste Ready)

### 1. Start the 365-day backfill

```bash
# From project root
make backfill-tmux
```

**What happens:**
- Creates a tmux session named `stx-backfill`
- Starts backfill with caffeinate (prevents sleep)
- Opens live monitor in bottom pane
- Runs until 365 days of history is fetched (hours)

### 2. Detach and let it run

**Press: `Ctrl+B` then `D`**

The process continues running in the background, safe from:
- SSH disconnects
- Terminal closures
- macOS sleep (caffeinate prevents it)

### 3. Check progress later

```bash
# Quick status check (non-intrusive)
make backfill-status

# Or more detailed health check
make backfill-health

# Or view recent logs
make backfill-tmux-logs
```

### 4. Reattach to the session

```bash
# Reconnect to see live progress
make backfill-tmux
```

**Press: `Ctrl+B` then `D` to detach again**

### 5. When complete

```bash
# Stop the session
make backfill-tmux-stop

# Verify completion
make backfill-status
```

Expected output when complete:
```
Progress: 365/365 days (100.0%)
Status: Complete
```

---

## Understanding the Setup

### Tmux Session Layout

```
┌─────────────────────────────────────────────────────────────┐
│ Top Pane (60%): Backfill Runner                            │
│                                                             │
│ - Runs backfill_wallet_history.py with caffeinate         │
│ - Shows iteration progress, API calls, row counts         │
│ - Updates after each iteration                            │
│ - Logs to: out/backfill.log                               │
├─────────────────────────────────────────────────────────────┤
│ Bottom Pane (40%): Live Monitor                           │
│                                                             │
│ - Auto-refreshing dashboard (every 10s)                   │
│ - Shows: progress bar, row count, wallet count, ETA       │
│ - Displays recent log entries (colorized)                 │
│ - Non-intrusive, read-only monitoring                     │
└─────────────────────────────────────────────────────────────┘
```

### Backfill Parameters (Makefile Defaults)

```makefile
TARGET_DAYS     = 365      # Days of history to fetch
MAX_PAGES       = 5000     # Max API pages per iteration
MAX_ITERATIONS  = 0        # 0 = infinite (runs until target reached)
```

**Override example:**
```bash
# Fetch 180 days instead
make backfill-tmux TARGET_DAYS=180

# Limit to 10 iterations (for testing)
make backfill-tmux MAX_ITERATIONS=10
```

### Why Tmux + Caffeinate?

**Tmux provides:**
- Session persistence (survives SSH disconnects)
- Multi-pane layout (runner + monitor)
- Reattachable sessions (connect from anywhere)
- Process isolation (won't die with terminal)

**Caffeinate provides:**
- Prevents macOS from sleeping during long-running process
- Uses `-i` flag: prevents idle sleep
- Automatically terminates when backfill completes

**Combined:** Rock-solid uninterruptible execution for multi-hour backfills.

---

## Common Workflows

### Scenario 1: Start backfill, walk away

```bash
# Start the backfill
make backfill-tmux

# Wait for it to start (see first iteration begin)
# Then detach: Ctrl+B, D

# Go do other things (hours)...

# Later: check if done
make backfill-status
```

### Scenario 2: SSH remote execution

```bash
# On remote server via SSH
ssh user@server
cd /path/to/stx-labs

# Start tmux backfill
make backfill-tmux

# Detach: Ctrl+B, D
# Disconnect SSH: exit

# Later: reconnect and check
ssh user@server
cd /path/to/stx-labs
make backfill-tmux  # Reattaches to existing session
```

### Scenario 3: Monitor progress periodically

```bash
# Start backfill
make backfill-tmux
# Detach: Ctrl+B, D

# Every 30 minutes, check progress
make backfill-status

# Or view recent activity
make backfill-tmux-logs

# Or comprehensive health check
make backfill-health
```

### Scenario 4: Troubleshooting stuck backfill

```bash
# Check if process is alive and making progress
make backfill-health

# If stalled, view logs
make backfill-tmux-logs

# Attach to see live activity
make backfill-tmux

# If truly stuck, restart
make backfill-tmux-stop
make backfill-tmux-start
```

---

## Available Commands

### Primary Commands

| Command | Description | When to Use |
|---------|-------------|-------------|
| `make backfill-tmux` | Start or attach to session | **Most common** - smart mode |
| `make backfill-status` | Quick progress check | Check completion % without attaching |
| `make backfill-health` | Comprehensive health check | Verify process is alive and making progress |
| `make backfill-tmux-logs` | View recent logs | Quick peek without attaching |

### Advanced Commands

| Command | Description | When to Use |
|---------|-------------|-------------|
| `make backfill-tmux-start` | Force create new session | Explicitly start (fails if already exists) |
| `make backfill-tmux-attach` | Force attach to existing | Explicitly attach (fails if not running) |
| `make backfill-tmux-stop` | Stop the session | Clean shutdown when done or stuck |
| `make backfill-tmux-status` | Show tmux session details | Debug session state |

### Tmux Navigation (Inside Session)

| Keys | Action |
|------|--------|
| `Ctrl+B` then `D` | **Detach** (most important!) |
| `Ctrl+B` then `↑/↓` | Switch between panes |
| `Ctrl+B` then `[` | Scroll mode (use arrow keys, `q` to exit) |
| `Ctrl+B` then `z` | Zoom current pane (toggle fullscreen) |

---

## Expected Timeline

**For 365-day backfill starting from scratch:**

| Metric | Estimate |
|--------|----------|
| **Duration** | 8-16 hours |
| **Iterations** | 100-200 iterations |
| **Total rows** | 1.5M - 2.5M transactions |
| **Database size** | 400-600 MB |
| **API calls** | 10,000+ calls |

**Progress indicators:**
- First 30 min: ~50-100 days coverage (recent data, fast)
- Hour 2-4: Slows down (more data per day historically)
- Hour 4+: Steady pace as it works backwards
- Final hours: May slow as it reaches data limits

**Check progress every 1-2 hours to ensure steady state.**

---

## Troubleshooting

### Issue: "Session already exists"

**Symptom:**
```
Session 'stx-backfill' already exists. Use 'attach' to reconnect.
```

**Solution:**
```bash
# Attach to existing session
make backfill-tmux

# Or if you want to restart fresh:
make backfill-tmux-stop
make backfill-tmux-start
```

### Issue: "tmux is not installed"

**Symptom:**
```
tmux is not installed. Install with: brew install tmux
```

**Solution:**
```bash
# macOS
brew install tmux

# Ubuntu/Debian
sudo apt-get install tmux

# Then retry
make backfill-tmux
```

### Issue: Process appears stalled

**Symptom:**
- No progress in 10+ minutes
- Log file not updating
- Health check reports "STALLED"

**Diagnosis:**
```bash
# Check health
make backfill-health

# View recent logs
make backfill-tmux-logs

# Attach to see live activity
make backfill-tmux
```

**Common causes:**
1. **API rate limiting** - Wait 5-10 min, should resume
2. **Network issues** - Check connectivity
3. **Database lock** - Check if another process is accessing DB

**Solution:**
```bash
# If truly stuck after 15+ min
make backfill-tmux-stop
sleep 5
make backfill-tmux-start
```

### Issue: Cannot attach after SSH reconnect

**Symptom:**
```
Session 'stx-backfill' does not exist
```

**Diagnosis:**
```bash
# List all tmux sessions
tmux ls

# Check if process is running anyway
make backfill-status
```

**Possible causes:**
1. Session was killed (server reboot, OOM)
2. Tmux server crashed (rare)
3. Wrong working directory

**Solution:**
```bash
# If process is dead, restart
make backfill-tmux-start

# If you see the session with `tmux ls` but can't attach:
tmux attach -t stx-backfill
```

### Issue: Backfill completes but still < 365 days

**Symptom:**
```
Progress: 180/365 days (49.0%)
Status: Completed iterations but target not reached
```

**Explanation:**
- Not enough historical data in blockchain/API
- First transaction ever might be < 365 days ago
- Normal if blockchain is younger than target

**Solution:**
```bash
# Check what's actually available
make backfill-status

# If min date is reasonable (e.g., genesis block), you're done
# If you want more, increase max pages or iterations:
make backfill-tmux TARGET_DAYS=365 MAX_PAGES=10000 MAX_ITERATIONS=0
```

---

## Integration with Other Tools

### After Backfill Completes

```bash
# 1. Verify data quality
make backfill-status
python scripts/check_backfill_status.py --target-days 365

# 2. Build dashboards with full history
python scripts/build_dashboards.py --force-refresh

# 3. Run analysis notebook
make notebook

# 4. Run tests
make test

# 5. Check code quality
make lint
```

### Scheduled Backfill (Cron)

To run incremental backfills nightly:

```bash
# Add to crontab (crontab -e)
0 2 * * * cd /path/to/stx-labs && make backfill-wallet TARGET_DAYS=7 >> out/cron_backfill.log 2>&1
```

**Note:** Use `backfill-wallet` (foreground) for cron, not `backfill-tmux` (interactive).

---

## Best Practices

### Do:
✅ Use `make backfill-tmux` for long-running backfills
✅ Detach with `Ctrl+B D` instead of closing terminal
✅ Check progress every 1-2 hours with `make backfill-status`
✅ Let it run overnight (caffeinate prevents sleep)
✅ Verify completion before building dashboards

### Don't:
❌ Kill the terminal without detaching (use `Ctrl+B D` first)
❌ Run multiple backfill sessions simultaneously (database lock)
❌ Interrupt mid-iteration (let it finish current iteration)
❌ Assume it's done without checking status
❌ Forget to stop the session when complete

---

## FAQ

**Q: How do I know when it's done?**

A: Run `make backfill-status`. When you see:
```
Progress: 365/365 days (100.0%)
Status: Complete
```

**Q: Can I use my terminal for other things while backfill runs?**

A: Yes! That's the point of tmux. Detach with `Ctrl+B D` and the backfill continues in the background.

**Q: What if my SSH connection drops?**

A: No problem. The tmux session keeps running. Just SSH back in and run `make backfill-tmux` to reattach.

**Q: Does caffeinate work on Linux?**

A: No, caffeinate is macOS-only. On Linux, tmux alone is sufficient (Linux doesn't auto-sleep during active processes).

**Q: Can I run this on a remote server?**

A: Yes! This setup is designed for remote execution. SSH in, start the tmux session, detach, disconnect SSH. Process continues.

**Q: How much disk space does 365 days need?**

A: Approximately 400-600 MB for the DuckDB database, plus 100-200 MB for cache files.

**Q: What happens if I lose power / server reboots?**

A: The backfill stops. When you restart, run `make backfill-tmux` again. It will resume from where it left off (incremental backfill).

**Q: Can I speed it up?**

A: Increase `MAX_PAGES` to fetch more per iteration:
```bash
make backfill-tmux MAX_PAGES=10000
```
But be careful - larger pages can trigger API rate limits.

---

## Comparison: Tmux vs Background vs Foreground

| Feature | Foreground | Background (`-bg`) | Tmux (This Guide) |
|---------|------------|-------------------|-------------------|
| Survives terminal closure | ❌ | ✅ | ✅ |
| Survives SSH disconnect | ❌ | ⚠️ (depends) | ✅ |
| Prevents macOS sleep | ❌ | ✅ (caffeinate) | ✅ (caffeinate) |
| Live monitoring | ✅ | ❌ | ✅ (dual-pane) |
| Reattachable | ❌ | ❌ | ✅ |
| Process isolation | ❌ | ⚠️ | ✅ |
| **Recommended for 365d** | ❌ | ⚠️ | **✅** |

**Verdict:** Use **tmux** for any backfill > 1 hour or on remote servers.

---

## Next Steps

1. **Start the backfill:**
   ```bash
   make backfill-tmux
   ```

2. **Detach and wait:**
   - Press `Ctrl+B` then `D`
   - Let it run for 8-16 hours

3. **Check progress periodically:**
   ```bash
   make backfill-status
   ```

4. **When complete, build dashboards:**
   ```bash
   python scripts/build_dashboards.py --force-refresh
   ```

5. **Run analysis:**
   ```bash
   make notebook
   ```

---

## Additional Resources

- **Existing backfill docs:**
  - `docs/README_BACKFILL.md` - Navigation guide
  - `docs/BACKFILL_AUTOMATION_GUIDE.md` - Implementation details
  - `docs/wallet_backfill_quick_ref.md` - Code snippets

- **Scripts:**
  - `scripts/backfill_wallet_history.py` - Main backfill script
  - `scripts/monitor_backfill.py` - Real-time monitoring dashboard
  - `scripts/check_backfill_status.py` - Quick status check
  - `scripts/backfill_tmux.sh` - Tmux wrapper (this guide)
  - `scripts/backfill_health_check.sh` - Health monitoring

- **Tmux resources:**
  - [Tmux Cheat Sheet](https://tmuxcheatsheet.com/)
  - [Tmux Book](https://leanpub.com/the-tao-of-tmux/read)

---

**Last Updated:** November 9, 2025
**Author:** Claude Code (Anthropic)
**Status:** Production Ready ✓
