# Wallet Value – Beads Plan (Epics, Issues, Dependencies)

Source of truth for scope/rationale: see `docs/wallet_value_plan.md`.

This file enumerates every epic and task as beads issues with acceptance criteria and dependency intent. The bd CLI now contains the live issues; use the commands below to inspect status.

## How to View/Work the Plan
- List everything: `bd list`
- JSON for programmatic use: `bd list --json`
- Ready (unblocked): `bd ready`
- Dependency tree for an epic: `bd dep tree "Epic: Wallet Value MVP" --json`
- Open an issue: `bd edit <issue-id>` or `bd show <issue-id>`

Notes
- If you see warnings about an old global daemon or multiple databases, run `bd doctor` and consider `bd daemon` inside this repo. The plan was seeded in the local `.beads` database.

## Epics
- Epic: Repo Hygiene & Environment (Wallet Value)
- Epic: Wallet Value MVP
- Epic: Activation Filter Refinement
- Epic: sBTC Funded Signal
- Epic: Derived Activity Value & Incentives (WALTV)
- Epic: App Mapping & Reporting
- Epic: Performance & Reliability
- Epic: Dashboard UX Polish
- Epic: Data Governance & Scheduling
- Epic: Documentation & Handoff

## Epic: Repo Hygiene & Environment (P1)
- Sync .env across all worktrees
  - Acceptance: All worktrees contain `.env` with `HIRO_API_KEY`; `./scripts/sync_env.sh` verified.
  - Steps: run sync script; `ls -la .env`; `cat` .env in each worktree; commit nothing.
- Ensure venv is up to date in target worktree
  - Acceptance: `make setup` completes; `make test` imports succeed.
- Baseline CI sanity (tests + lint)
  - Acceptance: `make test` passes; `make lint` runs (repo-wide lint warnings acceptable).

## Epic: Wallet Value MVP (P1)
- Adopt wallet_value pipeline API
  - Acceptance: `compute_value_pipeline(max_days=60)` returns non-empty frames with backfilled data.
- Verify Hiro balances endpoint caching for funded classification
  - Acceptance: repeated calls hit cache (files under `data/raw/hiro_address_balances_*` updated once per TTL).
- Backfill wallet transactions (365 days)
  - Acceptance: DuckDB `min(block_time) <= now-365d`; wallet_count above baseline; backfill logs show progress.
- Validate STX/BTC price panel coverage
  - Acceptance: `prices.load_price_panel(start,end)` covers full activity range; no fatal gaps.
- Generate dashboards (wallet, value, macro)
  - Acceptance: `public/wallet/index.html`, `public/value/index.html`, `public/macro/index.html` render correctly.
- Tests green (>=80% coverage baseline)
  - Acceptance: `make test` passes; `tests/test_wallet_value.py` passes.

Dependencies
- Backfill depends on: Sync .env, Ensure venv
- Price panel depends on: Backfill
- Dashboards depend on: Price panel
- Tests green depends on: Dashboards

## Epic: Activation Filter Refinement (P2)
- Decide non-trivial activation rule
  - Acceptance: rule approved and recorded in `docs/wallet_value_plan.md`.
- Implement activation filter in first-seen logic
  - Acceptance: `first_seen` excludes trivial txs per rule; unit tests updated.
- Recompute first_seen and cohorts
  - Acceptance: cache refreshed; cohort charts reflect rule; diffs documented.

Dependencies
- Implement filter depends on: Decide rule, Backfill
- Recompute first_seen depends on: Implement filter

## Epic: sBTC Funded Signal (P2)
- Research sBTC mint event detection
  - Acceptance: ABI/function signatures and event shapes identified.
- Capture contract_id/function in ingestion
  - Acceptance: DuckDB `transactions` includes contract_id/function for `contract_call` txs.
- Add sBTC minted threshold to funded classification
  - Acceptance: wallets with sBTC mint ≥ 0.001 BTC qualify as funded; tests cover examples.

Dependencies
- Capture contract details depends on: Research sBTC
- Funded-by-sBTC depends on: Capture contract details

## Epic: Derived Activity Value & Incentives (P2)
- Decide derived value attribution method
  - Acceptance: method approved and documented (first-touch/equal-share/etc.).
- Aggregate downstream fees by contract post-activation
  - Acceptance: table/view summarizing downstream fees per activation_contract and window; tests validate aggregation.
- Apply WALTV = NV + derived − incentives
  - Acceptance: WALTV columns in windows output and visualized; tests pass.
- Ingest incentives (off-chain) for WALTV offsets
  - Acceptance: incentives data joined to wallets; WALTV subtracts values.

Dependencies
- Aggregate downstream fees depends on: Decide attribution, Capture contract details
- WALTV depends on: Aggregate downstream fees
- Incentives depends on: Decide attribution

## Epic: App Mapping & Reporting (P3)
- Create contract→app mapping
  - Acceptance: mapping file checked in; lookups covered by tests.
- Add app-level funnels and value views
  - Acceptance: dashboard sections show per-app funnels and NV/WALTV; rank top apps by value.

Dependencies
- App dashboards depend on: App mapping, Capture contract details

## Epic: Performance & Reliability (P2)
- Tune backfill throughput and stability
  - Acceptance: sustained pages/min, throttling avoided; documented recommended flags.
- Validate price fallback behavior
  - Acceptance: CoinGecko failure triggers Signal21 fallback; errors clearly surfaced if both fail.

Dependencies
- Both depend on: Backfill

## Epic: Dashboard UX Polish (P2)
- Add conversion funnel visualization
  - Acceptance: funded→active→value conversion visible with clear tooltips.
- Add price join method toggle (nearest vs start-of-day)
  - Acceptance: NV recalculates; default remains nearest; performance acceptable.
- Polish tooltips and copy for KPI definitions
  - Acceptance: copy aligned with `docs/wallet_value_plan.md`.

Dependencies
- All depend on: Dashboards generated

## Epic: Data Governance & Scheduling (P3)
- Define cache retention policy and cleanup scripts
  - Acceptance: retention documented; cleanup scripts in place and safe.
- Add scheduled dashboard refresh
  - Acceptance: nightly/weekly job runs deltas; basic monitoring/logging exists.

Dependencies
- Scheduled refresh depends on: Dashboards generated, Retention policy

## Epic: Documentation & Handoff (P2)
- Keep wallet_value_plan.md updated
  - Acceptance: doc reflects activation rule and WALTV v2 decisions; reviewed quarterly.
- Add operator runbook for backfills and dashboards
  - Acceptance: `docs/runbook_wallet_value.md` contains steps and troubleshooting; team can run without assistance.

Dependencies
- Runbook depends on: Dashboards generated

