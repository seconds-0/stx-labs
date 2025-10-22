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
- **Primary APIs:** Hiro Stacks API for on-chain metadata; alternative for prices (e.g., CoinGecko) with Signal21 support as optional.
- **Caching:** All expensive pulls write to `data/cache/`. Use `make refresh-prices` / `make refresh-data` (to be added) to invalidate caches intentionally.
- **Fallbacks:** If a provider is unreachable, the notebook surfaces warnings and continues with cached data or alternate sources.

## Useful Commands
```bash
make test         # pytest suite (offline-friendly via mocks/fixtures)
make lint         # black + ruff
make notebook     # papermill execution saving to out/stx_pox_flywheel_run.ipynb
make smoke-notebook  # papermill smoke run (30-day window, cache only)
```

## Documentation
- `docs/reset-plan.md` – high-level roadmap for stabilization.
- `docs/local.md` – detailed local workflow (setup, caching, papermill).
- `docs/colab.md` – optional hosted workflow if Colab is needed.

## Contribution Guidelines
- Use beads (`bd ready`, `bd update`) to track work.
- Follow Conventional Commits (`feat:`, `fix:`, `docs:`…); include bead IDs in descriptions.
- Keep secrets out of Git; `.env`, caches, and outputs stay local.
