# Stacks PoX Flywheel Analysis

This repository builds a reproducible tenure-level view of the Stacks Proof-of-Transfer (PoX) flywheel—linking Stacks transaction fees, miner BTC bids, and stacker yields—with emphasis on reliable local execution.

## Project Goals
- Aggregate Stacks on-chain data (fees, rewards, anchor metadata) alongside STX/BTC pricing.
- Produce reusable artifacts: joined panels, scenario tables, CSV/Parquet exports, and charts.
- Support headless runs (papermill) and interactive analysis (JupyterLab) with robust caching and fallbacks.

## Quick Start (Local-First)
```bash
make setup         # create virtualenv + install deps
make lab           # launch JupyterLab from repo root
```

Notebook: `notebooks/stx_pox_flywheel.ipynb`. Run top-to-bottom; configuration cells print active parameters. Minutes-long API pulls cache to `data/cache/` so re-runs are quick and resilient.

### Environment Notes
- Copy `.env.example` to `.env` (or set env vars) and provide `HIRO_API_KEY`. `src.config` loads it automatically.
- Adjust analysis horizon via the notebook parameters or papermill CLI arguments (`make notebook` runs with defaults).

## Data Strategy
- **Primary APIs:** Hiro Stacks API for on-chain metadata; CoinGecko for prices with Signal21 as fallback.
- **Caching:** All expensive pulls write to `data/cache/`. Use `make refresh-prices` to drop cached price parquet files (pair with `make notebook` to rebuild).
- **Fallbacks:** If a provider is unreachable, the notebook surfaces warnings and continues with cached data or alternate sources.

## Useful Commands
```bash
make test             # pytest suite (offline-friendly via mocks/fixtures)
make lint             # black + ruff
make notebook         # papermill execution saving to out/stx_pox_flywheel_run.ipynb
make smoke-notebook   # papermill smoke run (30-day window, cache only)
make notebook-bg      # launch papermill in background, log to out/notebook.log
make notebook-status  # check on background run PID
make notebook-tail    # follow the notebook log
make refresh-prices   # delete cached price parquet files

# Wallet transaction history backfill (for dashboard metrics)
make backfill-status  # check current backfill progress
make backfill-wallet  # run backfill (foreground, default 180 days)
make backfill-bg      # run backfill in background with logging
make backfill-tail    # follow backfill logs
make backfill-stop    # stop background backfill process
```

> **Generated assets:** HTML dashboards live under `public/` after running
> `scripts/build_dashboards.py`. Treat them as build artefacts; rerun the script
> instead of editing the files directly.

Need to refresh the value dashboard while the long backfill is still writing?
Use the snapshot options:

```bash
python scripts/build_dashboards.py --value-only --wallet-db-snapshot
```

This copies `wallet_metrics.duckdb` to a temp file, skips the history sync, and
cleans up automatically.

## Documentation Map
- `docs/runbooks/backfill.md` – canonical wallet history backfill SOP.
- `docs/runbooks/wallet_value.md` – end-to-end wallet funnel/value refresh steps.
- `docs/runbooks/cache_maintenance.md` – how to prune stale cached data safely.
- `docs/ops/README.md` – links to AGENT guidelines, monitoring, worktree tips.
- `docs/decisions/` – PRDs, retros, review notes.
- `docs/investigations/` – historical deep dives (backfill, notebook hangs, etc.).
- `docs/local.md` / `docs/colab.md` – local & hosted workflow details.
- `docs/reset-plan.md` – stabilization roadmap.

## Contribution Guidelines
- Use beads (`bd ready`, `bd update`) to track work.
- Follow Conventional Commits (`feat:`, `fix:`, `docs:`…); include bead IDs in descriptions.
- Keep secrets out of Git; `.env`, caches, and outputs stay local.
