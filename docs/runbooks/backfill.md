# Wallet Transaction History Backfill Runbook

Authoritative instructions for populating and maintaining the DuckDB wallet
history cache that powers all wallet growth and value dashboards.

---

## 1. Purpose & Inputs

- **Why:** Wallet funnels, value windows, and cohort charts all read from
  `data/cache/wallet_metrics.duckdb`. An incomplete backfill collapses the
  dashboards to the most recent days.
- **Sources:** Hiro `/extended/v1/tx` for canonical transactions plus cached
  HTTP payloads under `data/raw/hiro_transactions_*`.
- **Artifacts:** DuckDB table `transactions` (one row per tx) + parquet cache
  `wallet_metrics/first_seen_wallets.parquet`.

---

## 2. Quick Start Commands

```bash
# 0) Enter the virtualenv once per shell
source .venv/bin/activate

# 1) Check current coverage
python scripts/check_backfill_status.py --target-days 365

# 2) Run automated backfill (ctrl+c safe)
python scripts/backfill_wallet_history.py \
  --target-days 365 \        # horizon
  --max-pages 5000 \         # more per iteration = faster
  --max-iterations 0         # loop until target reached

# 3) Monitor progress in another shell
python scripts/check_backfill_status.py --target-days 365
```

### tmux / screen pattern (recommended for long runs)

```bash
tmux new -s wallet-backfill
source .venv/bin/activate
python scripts/backfill_wallet_history.py --target-days 365 --max-iterations 0
# detach: Ctrl+B, D
tmux attach -t wallet-backfill     # reattach later
```

---

## 3. Operational Tips

- **Resume behavior:** Script reuses DuckDB state; restarting simply continues
  from the oldest missing timestamp.
- **Lock errors:** If a previous run crashed and still holds a DuckDB lock,
  kill the stray PID (see stack trace) before relaunching.
- **Pagination:** Each iteration fetches 50 tx/page. Larger `--max-pages`
  accelerates backfills but stresses Hiro; balance against rate limits.
- **Force refresh:** Use `--force-refresh` only when caches are corrupt; it will
  re-request every page and should be avoided during normal ops.

---

## 4. Health Monitoring

| Command | What it shows |
| --- | --- |
| `python scripts/check_backfill_status.py --target-days 365` | rows, wallet count, min/max timestamps, % coverage |
| `make backfill-status` | same as above via Makefile wrapper |
| `ls -lh data/cache/wallet_metrics.duckdb` | sanity check DB size (hundreds of MB expected) |

Alert if coverage drops below policy (currently full 365d) or if the script
stalls for multiple iterations.

---

## 5. Post-Backfill Actions

1. Run wallet value pipeline / dashboards:
   ```bash
   python scripts/build_dashboards.py --wallet-max-days 365 --wallet-windows 15 30 60 90
   ```
2. Execute notebook smoke tests (`make smoke-notebook`) or full notebook
   (`make notebook`) per AGENTS instructions.
3. Regenerate public assets or artifacts as required (`make publish` if set up).

---

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `IO Error: Could not set lock` | stale DuckDB process | `ps aux | grep backfill` → `kill <pid>` and rerun |
| Coverage plateaus | `--max-pages` too low or Hiro throttling | rerun with higher `--max-pages`, monitor logs for HTTP 429 |
| Script exits immediately | DB missing or schema absent | run once without `--read-only`; `_ensure_schema` will recreate |
| Notebook uses stale data | price panel not refreshed | rerun `scripts/build_dashboards.py` with `--force-refresh` |

---

## 7. Data Hygiene

- `data/raw/hiro_transactions_*` grows quickly; it is safe to delete files
  older than 45 days if disk pressure rises (next run will rehydrate).
- Never commit files from `data/raw/` or `data/cache/`.
- Keep `.env` synced across worktrees before launching backfills
  (`./scripts/sync_env.sh`).

---

## 8. References

- Backfill implementation: `scripts/backfill_wallet_history.py`
- Status helper: `scripts/check_backfill_status.py`
- Wallet metrics ingestion: `src/wallet_metrics.py`
- Value pipeline & dashboards: `src/wallet_value.py`, `scripts/build_dashboards.py`

