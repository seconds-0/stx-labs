# Reset Plan: Stacks PoX Flywheel Notebook

## 1. Clarify Objectives & Scope
- **Primary output:** deterministic Jupyter notebook + headless script that produces tenure-level panel, scenarios, and artifacts using historical data as far back as APIs reliably allow.
- **Execution modes:** prioritize **local JupyterLab** (make targets) with Colab as optional fallback. All instructions, tooling, and tests must assume local-first operation.
- **Data coverage:** target 365 days by default. Expand to full history only when APIs prove reliable; provide switches for shorter spans (30/90/180 days) and cached snapshots.

## 2. Environment & Workflow Foundations
1. **Lock local workflow**
   - Ensure `make setup`, `make lab`, `make test`, and `make notebook` cover all developer actions.
   - Validate notebook runs from repo root without path edits.
2. **Optional Colab path**
   - Maintain setup cell but flag as “best effort”; warn when using public Signal21 endpoints with limited reliability.

## 3. Data Acquisition Strategy
1. **Signal21 prices**
   - Default to 30-day chunks with adaptive halving.
   - After N (e.g., 3) failed retries on the minimal chunk, log warning and skip.
   - Persist fetched data to `data/cache/prices_<symbol>.parquet`; reuse cache before hitting API.
   - Provide CLI/Make target `make refresh-prices` to rebuild cache explicitly.
   - Define fallback provider (e.g., CoinGecko) with matching schema for long-term resilience.
2. **Signal21 fees**
   - Similar caching & chunking for SQL queries; store parquet outputs.
   - Parameterize date window to avoid full-history pulls unless opt-in.
3. **Hiro PoX data**
   - Batch with pagination and caching; surface rate-limit handling.
4. **Configuration**
   - Centralize default horizons in `src/config.py` with env overrides (e.g., `DEFAULT_HISTORY_DAYS`).

## 4. Notebook Restructure
1. **Section order**
   - Intro, environment checks, configuration summary (printing key parameters & cache status).
   - Data acquisition cells refer to cached files first, then fetch if missing/force-refresh.
   - Scenario & visualization cells operate on cached/loaded data to decouple from API runs.
2. **Diagnostics**
   - Add status outputs (chunks attempted, skipped spans, final coverage).
   - Guard rails: assert non-empty frames, raise actionable messages when data missing.
3. **Artifacts**
   - Save canonical parquet/CSV + HTML summary.
   - Integrate papermill parameters (date range, force refresh) at top.

## 5. Testing & Validation
1. **Unit tests**
   - Mock API responses; validate chunk splitting, cache reuse, scenario math.
   - Add regression fixture for price chunk splitting.
2. **Integration smoke**
   - `make test-notebook` (papermill with constrained window) to ensure end-to-end flow works offline using cached snapshots.
3. **Snapshots**
   - Optionally maintain sanitized sample dataset in `tests/fixtures/` for deterministic runs.

## 6. Documentation & Communication
1. **README update**
   - Summarize project, local setup, key make targets, data refresh workflow, known API limitations.
2. **docs/local.md & docs/colab.md**
   - Reference caching & fallback strategies, highlight default 365-day horizon.
3. **Changelog / beads**
   - Track tasks for each workstream (caching, fallback provider, notebook restructure, tests, docs, README).

## 7. Task Breakdown (Beads Backlog)
1. **Environment & Docs**
   - Update README with reset summary and workflows.
   - Align AGENTS instructions with local-first approach.
2. **Caching & Config**
   - Implement price cache layer + fallback provider.
   - Add fee & rewards caching, env-driven defaults.
3. **Notebook Refactor**
   - Rebuild data acquisition section to use caches.
   - Add diagnostics and parameter summary cell.
4. **Testing**
   - Extend unit tests for chunking/cache.
   - Add papermill smoke test.
5. **Cleanup**
   - Remove or gate Colab-specific logic to optional path.

## 8. Risks & Mitigations
- **API instability:** rely on cached artifacts & alternate provider.
- **Data drift:** timestamp caches with metadata; allow manual refresh.
- **Developer confusion:** clear docs, make targets, and configuration prints in notebook.

## 9. Next Steps
1. Align on default history window (suggest 365 days).
2. Approve cache directory structure (`data/cache/`).
3. Create bead issues for each task above.
4. Execute plan in priority order: environment/docs → caching → notebook → tests → polish.
