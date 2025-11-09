## Comparing Blockchain Activity to Mobile CPI/CPA Models — Wallet Value Plan

This document captures the plan, implementation, and runbook for modeling the economic value of newly funded wallets on Stacks using mobile CPI/CPA-style concepts (activation → conversion → value). It is intended to guide iteration and keep the scope clear and pragmatic.

### Summary
- Compute Network Value (NV) per wallet as on-chain STX fees converted to BTC using historical STX/BTC prices.
- Compute Wallet Adjusted LTV (WALTV) per activation cohort over windows (15/30/60/90/180). In v1, WALTV ≈ NV (i.e., no incentives/derived value yet).
- Classify wallets into funnel stages: funded → active → value, with thresholds tuned to filter faucet/bot activity.
- Produce a dark-themed HTML dashboard for funnel conversion and WALTV distributions; fully rerunnable with cached deltas.

### KPIs & Definitions
- Activation Event: first canonical, successful wallet transaction (can be tightened later to “non-trivial” types)
- NV (Network Value): Σ(fee_stx × STX/BTC_at_tx_time)
- WALTV: NV + derived activity value − incentives (v1: derived/incentives = 0)
- Classes (initial thresholds)
  - Funded Wallet: current `STX balance ≥ 10` (sBTC mint ≥ 0.001 BTC planned)
  - Active Wallet: `≥ 3 tx in first 30 days` from activation
  - Value Wallet: `WALTV-30 ≥ 1 STX in fees`

### What We Reuse vs What We Added
We intentionally build on existing infrastructure to avoid duplication:

Reused (already in repo)
- Hiro ingest + DuckDB cache: `src/wallet_metrics.py` (transaction pagination and storage)
- Price caching and panel merge: `src/prices.py` (CoinGecko primary, Signal21 fallback)
- HTTP retry + cache: `src/http_utils.py`
- Dashboard framework: `scripts/build_dashboards.py` (HTML writer, Plotly rendering)

Added (small, focused extensions)
- Wallet value pipeline: `src/wallet_value.py`
  - `compute_activation` → activation timestamps per wallet
  - `load_price_panel_for_activity` → hourly STX/BTC over activity window
  - `compute_wallet_windows` → per-wallet NV/fee aggregates over windows from activation
  - `classify_wallets` → funded/active/value flags using configurable thresholds
  - `compute_value_pipeline` → end-to-end for dashboards
- Hiro balances endpoint: `src/hiro.py:fetch_address_balances(address)` (cached)
- Value dashboard: `scripts/build_dashboards.py:build_value_dashboard(...)`
- Tests: `tests/test_wallet_value.py` (NV/window calc + classification)

Conclusion
- We are not rebuilding core ingestion, caching, or visualization; we’re extending them with a targeted module and a few hooks. The approach is simple and incremental, not overengineered.

### Architecture / Flow
1) Ingest canonical transactions → DuckDB (reused)  
2) Load hourly STX/BTC price panel covering activity dates (reused)  
3) Join fee events to nearest price → NV per tx  
4) Aggregate per wallet from activation across windows (15/30/60/90/180)  
5) Classify wallets: funded (balance), active (tx count), value (WALTV-30 fees)  
6) Render funnel + WALTV dashboards (reused HTML shell)

### Implementation Details
- Activation derived from first-seen cache (canonical successful tx). We can later constrain to “non-trivial” tx types.
- NV uses nearest timestamp match to STX/BTC. Zero/interpolation handling already covered by `prices.load_price_panel`.
- Classification uses cached Hiro balances for funded flag; cap lookups to avoid heavy API usage.
- WALTV v1 equals fee-denominated NV; derived value and incentives are planned extensions.
- Everything is delta-friendly: HTTP + parquet + DuckDB caches avoid re-pulling historical data.

### Runbook
Prereqs
- Ensure `.env` includes `HIRO_API_KEY`. Use `./scripts/sync_env.sh` to propagate across worktrees.
- Setup venv + deps: `make setup`

Backfill (recommended first run)
- `python scripts/backfill_wallet_history.py --target-days 180`
- Status: `make backfill-status`

Build dashboards
- `python scripts/build_dashboards.py --wallet-max-days 180 --value-windows 15 30 60 90`
- Outputs:
  - Wallet Growth: `public/wallet/index.html`
  - Wallet Value: `public/value/index.html`
  - Macro: `public/macro/index.html`

Notebook validation (optional, per repo workflow)
- Quick: `make smoke-notebook` (30-day window)
- Full: `make notebook`

### Risks & Caveats
- Funded classification currently uses current balance snapshot (not historical at activation). For higher fidelity, add inflow/sBTC mint detection around activation.
- sBTC minted threshold planned: requires parsing contract calls/events.
- Derived activity value (downstream fees from contracts) and incentive offsets are v2 features.

### Next Enhancements (v2)
- Enrich ingestion with `contract_call.contract_id` and function name; attribute derived value by downstream fee activity on interacted contracts (first-touch vs shared allocation).
- Parse sBTC mint events for “funded by sBTC” signal.
- Join wallet-level incentives (off-chain CSV/JSON) to subtract costs from WALTV.
- App-level reporting with contract→app mapping; per-app funnel + NV.

### Validation
- All tests pass: `make test` (74 passed at time of writing).
- Unit tests for the new module: `tests/test_wallet_value.py`.

---

## FAQ

Q1. Are we rebuilding any critical infrastructure?  
A. No. We reuse ingestion (Hiro→DuckDB), price caching, and dashboard scaffolding. New code is small and targeted to value modeling and classification.

Q2. Is there stuff in the repo we can use?  
A. Yes: `wallet_metrics` for tx history, `prices` for historical pricing, `http_utils` for retries/caching, and `build_dashboards.py` for HTML generation. We extended these rather than replacing them.

Q3. Is this simple and straightforward, or overengineered?  
A. It’s intentionally straightforward:
- Minimal new module (`wallet_value`) using existing caches.
- Light extension to `hiro.py` for balances.
- One additional dashboard function.
- WALTV v1 = NV to avoid premature complexity; derived/incentives are planned separately.

