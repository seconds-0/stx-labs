# Wallet Metrics Backfill Documentation

Complete analysis and automation guide for the wallet metrics transaction history backfill process.

## Quick Navigation

### For Understanding the Process
- **[EXPLORATION_SUMMARY.md](./EXPLORATION_SUMMARY.md)** - Executive summary of findings (read this first!)
- **[wallet_backfill_analysis.md](./wallet_backfill_analysis.md)** - Deep technical reference (10 detailed sections)

### For Quick Lookup
- **[wallet_backfill_quick_ref.md](./wallet_backfill_quick_ref.md)** - Quick reference with code examples and diagrams

### For Building Automation
- **[BACKFILL_AUTOMATION_GUIDE.md](./BACKFILL_AUTOMATION_GUIDE.md)** - Step-by-step guide with production code

---

## Document Overview

### 1. EXPLORATION_SUMMARY.md (12 KB, 5-10 min read)
**Best for:** Understanding what was discovered and why it matters

Contents:
- Files analyzed and key insights
- Two-phase architecture explanation
- Pagination cursor system
- Resumption behavior
- DuckDB schema
- Critical design decisions
- Next steps for implementation

**Start here if:** You want the big picture without deep technical details.

---

### 2. wallet_backfill_analysis.md (16 KB, 15-20 min read)
**Best for:** Deep technical understanding of every component

10 Sections:
1. Function signature and parameters
2. Two-phase backfill architecture (detailed)
3. Pagination cursor logic with examples
4. DuckDB schema and caching
5. Checking cache state (queries included)
6. Retry and API limit behavior
7. Resumption and incremental behavior
8. Timeout and long-running behavior
9. Key parameters for automation
10. Common issues and troubleshooting

**Start here if:** You need to understand every detail or debug issues.

---

### 3. wallet_backfill_quick_ref.md (8 KB, 5-10 min reference)
**Best for:** Quick lookup while coding

Contents:
- Function call signatures
- Execution flow diagram (ASCII)
- Phase comparison table
- Key variables and configuration
- Cursor logic walkthrough with example values
- Status queries (copy-paste ready)
- Error handling patterns
- Monitoring progress calculations
- API behavior notes
- Resumption scenario walkthrough
- Common patterns with code

**Start here if:** You need a quick refresher or code snippet.

---

### 4. BACKFILL_AUTOMATION_GUIDE.md (16 KB, 20-30 min read)
**Best for:** Building automated monitoring and deployment

Contents:
- Executive summary
- Understanding the cursor system
- Stop conditions enumeration
- Step-by-step monitoring script building:
  - Progress checker function
  - Resumable backfill loop
  - Production monitoring script
- Detecting common issues
- Configuration parameters
- Performance expectations
- Deployment options (manual, cron, systemd)
- Integration with dashboard build
- Troubleshooting checklist
- Next steps

**Start here if:** You're ready to build automation.

---

## Recommended Reading Path

### Path 1: Quick Overview (15 minutes)
1. This README
2. EXPLORATION_SUMMARY.md
3. wallet_backfill_quick_ref.md

### Path 2: Complete Understanding (45 minutes)
1. This README
2. EXPLORATION_SUMMARY.md
3. wallet_backfill_analysis.md
4. BACKFILL_AUTOMATION_GUIDE.md

### Path 3: Implementation Focused (30 minutes)
1. BACKFILL_AUTOMATION_GUIDE.md (main guide)
2. wallet_backfill_quick_ref.md (code lookups)
3. wallet_backfill_analysis.md (for specific issues)

---

## Key Takeaways (TL;DR)

### What It Does
- Fetches Stacks transaction history from Hiro API
- Stores in DuckDB (`data/cache/wallet_metrics.duckdb`)
- Two-phase: recent data (Phase 1) + historical backfill (Phase 2)

### How to Use It
```python
from src.wallet_metrics import ensure_transaction_history

# Fetch last 180 days of transactions
ensure_transaction_history(max_days=180, force_refresh=False)

# Repeat until complete:
# Call 1: Fetches recent + backfills some historical
# Call 2: Gets new recent data + continues backfill
# Call 3: Finishes backfill
# Call 4+: Exits immediately (already complete)
```

### Why Automation Matters
- First run to 180 days: 45-120 minutes
- Hits max_pages (10,000) limit midway
- Must call repeatedly to complete
- Each call picks up where it left off
- Monitoring script tracks progress

### Simple Monitoring Loop
```python
while not is_complete(target_days=180):
    ensure_transaction_history(max_days=180, force_refresh=False)
    check_progress()
    sleep(30)
```

---

## Quick Facts

| Aspect | Value |
|--------|-------|
| **Database** | `data/cache/wallet_metrics.duckdb` |
| **Table** | `transactions` |
| **Page size** | 50 transactions (fixed) |
| **Max pages per run** | 10,000 (500K txs max) |
| **Retry backoff** | 0.5s → 8.0s exponential |
| **Request timeout** | 30 seconds |
| **Time for 180 days** | 45-120 minutes |
| **Phase 1 (recent)** | ~10% of time |
| **Phase 2 (historical)** | ~90% of time |
| **After complete** | <1 second (idempotent) |

---

## Common Queries

### Check Cache Status
```python
import duckdb

conn = duckdb.connect("data/cache/wallet_metrics.duckdb", read_only=True)
result = conn.execute("""
    SELECT 
        COUNT(*) as rows,
        MIN(block_time) as oldest,
        MAX(block_time) as newest
    FROM transactions
""").fetchone()
rows, oldest, newest = result
print(f"Rows: {rows:,} | Span: {(newest - oldest).days} days")
conn.close()
```

### Check Completion
```python
from datetime import datetime, timedelta, UTC
import pandas as pd

# Is 180-day backfill complete?
target = datetime.now(UTC) - timedelta(days=180)
is_complete = pd.Timestamp(oldest) <= pd.Timestamp(target)
print(f"Complete: {is_complete}")
```

---

## Files in This Suite

```
docs/
├── README_BACKFILL.md                      ← You are here
├── EXPLORATION_SUMMARY.md                  ← Start here for overview
├── wallet_backfill_analysis.md             ← Deep technical reference
├── wallet_backfill_quick_ref.md            ← Quick lookup guide
└── BACKFILL_AUTOMATION_GUIDE.md            ← Implementation guide
```

---

## Next Actions

1. **Read EXPLORATION_SUMMARY.md** to understand the discovery
2. **Review BACKFILL_AUTOMATION_GUIDE.md** to plan automation
3. **Reference wallet_backfill_quick_ref.md** while coding
4. **Consult wallet_backfill_analysis.md** for technical details
5. **Build and test** your monitoring script

All code examples are production-ready and can be copied directly.

---

## Questions?

Refer to the appropriate document:

| Question | Document |
|----------|----------|
| How does it work? | EXPLORATION_SUMMARY.md |
| What's the pagination logic? | wallet_backfill_analysis.md §3 |
| How do I check progress? | wallet_backfill_quick_ref.md |
| How do I build automation? | BACKFILL_AUTOMATION_GUIDE.md |
| What should I do if X fails? | wallet_backfill_analysis.md §10 |
| How do I deploy this? | BACKFILL_AUTOMATION_GUIDE.md (Deployment) |

---

**Last Updated:** November 7, 2025  
**Status:** Complete and ready for implementation
