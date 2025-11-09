# Cache Maintenance Runbook

Short guide for reclaiming disk when cached API payloads balloon.

## 1. Inspect Sizes

```bash
du -h -d1 data
du -h -d1 data/raw
du -h -d1 data/cache
```

Focus on:
- `data/raw/hiro_transactions_*` (HTTP JSON cache)
- `data/raw/hiro_address_balances_*`
- `data/cache/prices/*.parquet`
- `data/cache/wallet_metrics.duckdb`

## 2. Safe Cleanup Steps

1. **Drop raw HTTP caches older than N days**
   ```bash
   find data/raw -type f -mtime +45 -print -delete
   ```
   Next run rehydrates only the missing windows.

2. **Purge price cache**
   ```bash
   make refresh-prices
   ```

3. **Rebuild wallet metrics DB**
   - Only when corruption is suspected.
   - Delete `data/cache/wallet_metrics.duckdb` and rerun the backfill runbook.

4. **Clear generated outputs**
   ```bash
   rm -rf out/*
   ```

## 3. Things to Avoid

- Never commit `data/raw/*`, `data/cache/*`, or `.env` copies.
- Don’t delete DuckDB while a backfill process is running—stop the job first.
- Avoid wiping cached prices mid-notebook run to prevent inconsistent panels.

## 4. When to Run

- Disk usage exceeds ~80% of quota.
- Cached data is obviously stale (e.g., price panel missing new days).
- Prior to sharing a sanitized repo snapshot.

