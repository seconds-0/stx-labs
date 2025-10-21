# Stacks PoX Flywheel Notebook – Product Requirements Document

## 1. Overview
- **Working Title:** Stacks PoX Flywheel: Fees → Miner Rewards → BTC Bids → PoX Yields (Signal21 + Hiro)
- **Purpose:** Deliver a reproducible Jupyter notebook that quantifies the Stacks Proof-of-Transfer (PoX) flywheel by linking fees, miner rewards, BTC bids, and PoX yields across historical tenures.
- **Primary Output:** Parameterized analysis notebook with exported artifacts (CSV/Parquet, charts, scenario tables) suitable for research and investor communications.

## 2. Objectives
- Aggregate on-chain and market data (Signal21 + Hiro) into a tenure-level panel keyed by Bitcoin burn block height.
- Produce baseline metrics and sensitivity scenarios that illuminate how fee dynamics influence miner BTC commits and stacker APY.
- Package results in reusable datasets, plots, and documentation so analysts can rerun or extend the study with minimal friction.

## 3. Target Users & Use Cases
- **Core users:** Stacks ecosystem analysts, treasury managers, and research contributors.
- **Use cases:** Investor reporting, economic modeling, PoX incentive design validation, monitoring fee growth vs. miner bidding.

## 4. Success Metrics
- Notebook executes end-to-end without manual intervention against default date windows.
- Generated tenure panel includes required columns and passes validation checks (no missing burn heights, coinbase verification ok).
- Scenario engine outputs the mandated +10/25/50/100/200% tables with ΔF, ΔN, BTC commits, and APY shifts.
- Charts render cleanly and exported artifacts exist under `./data/` and `./out/`.

## 5. Scope
### In Scope
- Historical pull of STX/BTC prices, fees, PoX rewards, and tenure metadata.
- Construction of hourly price series and tenure-level aggregates.
- Scenario modeling with configurable fee and rho assumptions.
- Visualization (scatter, time series, histogram) and data exports.
- Documentation cells covering methodology, references, and rerun guidance.

### Out of Scope
- Real-time streaming or dashboard deployment.
- Pool-level stacker attribution, KYC, or wallet clustering.
- Automated alerts or production pipelines.

## 6. Inputs & Configuration
- `W = [30, 90, 180]` day rolling windows (user-adjustable).
- API bases: `SIGNAL21_BASE`, `HIRO_BASE`.
- Authentication: `HIRO_API_KEY` via environment variable; attach header `X-API-Key`.
- Assumption toggles (`COINBASE_STX`, `FEE_PER_TX_STX`, `RHO_RANGE`, `stacked_supply_stx`) defined in a dedicated config cell.
- Date horizon parameters default to the full available history (notebook pulls as far back as Signal21/Hiro data allow) with optional start/end overrides for targeted analysis.

## 7. Data Requirements
### Signal21
- `/v1/price` for STX-USD, BTC-USD (generate STX/BTC; hourly resample).
- `/v1/sql-v2` for:
  - `core.txs` (fee data, canonical tx filtering).
  - `core.blocks` (burn block mapping).
  - Aggregation queries delivering fees per tenure and empirical fee-per-tx stats.

### Hiro Stacks API
- `/extended/v1/burnchain/rewards` for PoX BTC payouts (aggregate by `burn_block_height`).
- `/extended/v1/block/by_burn_block_height/{h}` for tenure anchor metadata.
- `/extended/v2/pox/cycles` for cycle boundaries.
- Optional: `/extended/v1/tx/block_height/{height}` for fee reconciliation, `/v2/fees/transfer`, `/extended/v2/mempool/fees` for context.

## 8. Functional Requirements
- **Schema discovery helpers** run cached `SELECT * ... LIMIT 5` probes (stored for reuse).
- **Robust fetch layer** with configurable retries (exponential backoff, jitter) honoring per-endpoint rate limits.
- **Caching:** Local raw JSON/CSV storage under `./data/raw/` with file naming keyed by endpoint + params; include TTL/force refresh switch.
- **Price processing:** Merge STX and BTC price series, compute hourly `stx_btc`, forward-fill gaps, align with tenure timestamps.
- **Fees aggregation:** Primary path via Signal21 SQL; fallback to Hiro tx enumeration. Compute per-tenure totals, tx counts, empirical fee/tx statistics per window.
- **PoX rewards:** Sum sats per `burn_block_height`, count recipients, map to cycles.
- **Tenure panel:** Join anchor metadata, fees, rewards, and nearest-price; derive reward totals, value in sats, rho (clipped 0–2), coinbase verification flag.
- **Scenario engine:** For each uplift `u` and `rho` scenario:
  - Compute increased reward, incremental fees (ΔF), extra transactions (ΔN), implied BTC commits (`commit_sats`), per-cycle totals, APY effect using configurable `stacked_supply_stx`.
  - Export scenario tables to CSV/Parquet.
- **Visualization suite:** Time series (fees, commits, rho), scatter with regression, histograms and rolling summaries; aesthetic defaults (labels, legend, date formatting).
- **Validation suite:** Assertions for missing tenures, coinbase deviations, zero-fee tenures, price alignment; random sample audit displayed.
- **Documentation cells:** Overview, methods, assumptions, citations (markdown with links to Signal21/Hiro/Stacks references), rerun instructions.

## 9. Non-Functional Requirements
- Reproducible environment (`requirements.txt` or `pip install` cell); optional `ruff`/`black` formatting mention.
- Deterministic outputs given identical inputs (cache invalidation optional).
- Runtime target: under 10 minutes for default windows on commodity laptop (optimize pagination size, parallelization optional but avoid rate-limit breach).
- Clear error messaging with actionable hints (e.g., missing API key, rate-limit).
- Notebook designed to be run headless (`papermill` compatible)—avoid interactive widgets unless optional.

## 10. Notebook Structure
1. Intro & Objectives (markdown, references, TOC).
2. Config & Dependencies (imports, env validation).
3. Utility Functions (fetching, caching, pagination, logging).
4. Schema Discovery (executed once; caches results).
5. Data Acquisition (prices, fees, rewards, anchor metadata, cycles).
6. Data Processing & Joins.
7. Metrics & Validations.
8. Scenario Analysis.
9. Visualization.
10. Artifacts & Save Outputs.
11. Next Steps / Extension Ideas.

## 11. Risks & Mitigations
- **API rate limits:** Implement exponential backoff, adjustable page sizes, and optional sleep intervals.
- **Schema drift:** Notebook probes schema at runtime and fails fast with descriptive suggestions.
- **Incomplete tenure coverage:** Validation step flags missing burn heights and optionally re-fetches gaps.
- **Coinbase changes (post SIP updates):** Auto-verify coinbase per tenure; surface warnings if not 1000 STX.
- **Large data volumes:** Parameterize date windows, allow chunked processing, store intermediate parquet files.

## 12. Enhancement Log (beyond original brief)
- Added explicit default date windows and guidance for adjusting to data retention.
- Incorporated rate-limit etiquette (max page size hints, retry policy config).
- Suggested cached schema discovery and documentation of known dataset names.
- Coinbase verification with anomaly alerts to guard against protocol changes.
- Expanded data quality assertions (missing heights, zero-fee tenures, reward gaps).
- Introduced configurable `stacked_supply_stx` to translate BTC commits into APY deltas.
- Formalized caching strategy with TTL and force-refresh options.
- Specified visualization polish (axis formatting, rolling windows callouts).
- Structured notebook with intro, TOC, and “Next Steps” cell for future extensions.
- Recommended optional lightweight tests for helper functions to ensure maintainability.

- Python ≥3.10, `requests`, `pandas` or `polars`, `python-dateutil`, `pyarrow`, `plotly` (primary charting) with optional `matplotlib`, `numpy`, optional `tenacity` for retries.
- Local filesystem write access to `./data/` and `./out/`.
- Optional tooling: `dotenv` for config, `pytest` for helper validation.

## 14. Documentation & References
- Cite API docs in notebook intro (Signal21 API, Hiro Stacks API, Stacks fee formula, QuickNode mempool references).
- Inline comments limited to complex transformations; rely on markdown narrative for broader context.

## 15. Testing Expectations
- Implement lightweight `pytest` coverage for critical helpers (fetching, pagination, scenario calculations).
- Supplement with in-notebook assertions for data integrity checks.

## 16. Deployment Strategy
- **Local development:** Standard Jupyter environment (VS Code, local JupyterLab).
- **Recommended hosted option:** Publish notebook + requirements in a GitHub repo and configure a Deepnote project that syncs to the repo. Deepnote supports secrets management for `HIRO_API_KEY`, offers shareable interactive sessions, and keeps parity with local dev via git sync. Alternatives such as GitHub Codespaces or Google Colab remain viable backups.
- Provide instructions in README/markdown cell for launching the Deepnote workspace and syncing outputs back to the repo.

## 17. Resolved Questions
- **Date range:** Notebook should default to pulling the entire available historical span; windows are adjustable as needed.
- **Runtime/data limits:** No explicit constraints; still target sub-10-minute execution for usability.
- **Visualization stack:** Default to Plotly for shareable interactivity; retain Matplotlib as optional fallback.
- **Scenario inputs:** Derive `stacked_supply_stx` and other live metrics from latest data pulls (Signal21/Hiro) and expose overrides for manual tuning.
- **Deployment:** Local-first workflow complemented by a shared Deepnote workspace (or similar) for online execution and collaboration.
- **Testing:** Include basic automated tests (pytest) alongside notebook assertions.
- **Future scope:** Focus on holistic Stacks economic flywheel; mempool analytics and pool-level attribution not required in current release.
