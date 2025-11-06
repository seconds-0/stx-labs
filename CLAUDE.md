# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository analyzes the Stacks Proof-of-Transfer (PoX) economic flywheel by linking:
- Wallet growth metrics (transaction history, cohort retention, fees via Hiro API)
- Miner BTC bids (Hiro burnchain rewards API)
- PoX stacker yields and APY calculations
- Stacks transaction fees (on-chain data via Signal21 SQL)
- STX/BTC pricing over historical burn block heights (tenures)

**Primary output**: Tenure-level panel data with scenario analysis showing how fee uplifts affect BTC commitments and stacker yields.

**Execution modes**: Local JupyterLab (preferred), Papermill headless runs, optional Google Colab.

## Essential Commands

### Development Setup
```bash
make setup           # Create .venv and install requirements.txt
make lab             # Launch JupyterLab (preferred interactive workflow)
```

**Environment**: Copy `.env.example` to `.env` and set `HIRO_API_KEY`. The `src.config` module loads it automatically.

### Testing & Quality
```bash
make test            # Run pytest suite (offline-friendly with mocks)
make lint            # Format with black + ruff
make smoke-notebook  # Quick 30-day test run with caching only
```

### Notebook Execution
```bash
make notebook        # Full papermill run (45-60 min default, saves to out/)
make notebook-bg     # Run papermill in background with logging
make notebook-tail   # Follow background execution logs
make notebook-status # Check if background run is still active
make notebook-stop   # Stop background papermill execution
```

### Cache Management
```bash
make refresh-prices  # Delete cached price parquet files
make clean          # Remove all cached data and outputs (data/raw/, out/)
```

## Architecture & Code Structure

### Module Organization

```
src/
├── config.py           # Centralized paths, API bases, retry config, DEFAULT_HISTORY_DAYS
├── http_utils.py       # HTTP layer with retry, exponential backoff, file-based JSON caching
├── cache_utils.py      # Parquet read/write helpers
├── hiro.py            # Hiro Stacks API (rewards, block metadata, PoX cycles, transactions, pagination)
├── wallet_metrics.py   # Wallet growth analytics (Hiro tx history → DuckDB → cohort metrics)
├── signal21.py         # Signal21 API (prices, SQL queries with adaptive 30→15→5 day chunking)
├── prices.py          # Multi-provider price fetching (CoinGecko primary, Signal21 fallback)
├── fees.py            # Transaction fee aggregation with adaptive SQL chunking
├── panel_builder.py   # Join components, compute rho (sats_committed/reward_value), derive flags
└── scenarios.py       # Generate sensitivity tables (fee uplifts → BTC commitments → APY)

notebooks/
└── stx_pox_flywheel.ipynb  # Main analysis notebook (papermill-compatible)

tests/
└── test_*.py          # Pytest suite mirroring src/ structure
```

### Data Flow

1. **Data Acquisition** (with caching):
   - **Wallet Metrics**: Hiro `/extended/v1/tx` (transaction history) → DuckDB cache (`data/cache/wallet_metrics.duckdb`) + parquet
   - **Rewards**: Hiro `/burnchain/rewards` (paginated) → `data/cache/hiro/*.parquet`
   - **Metadata**: Hiro `/block/by_burn_block_height/{h}` (lazy-fetched anchors) + `/pox/cycles`
   - **Prices**: CoinGecko (primary, 85-day chunks) → Signal21 (fallback, 30-day adaptive chunks) → `data/cache/prices/*.parquet`
   - **Fees**: Signal21 SQL queries (chunked by time, adaptive on 500 errors) → `data/cache/signal21/fees_by_tenure_*.parquet`

   **Note**: Wallet metrics is fully independent of Signal21 and CoinGecko - uses Hiro API only.

2. **Panel Construction** (`panel_builder.py`):
   - Left-join anchors + fees + rewards on `burn_block_height`
   - Merge prices via `merge_asof` (nearest timestamp)
   - Compute derived metrics: `rho` = sats_committed / reward_value_sats (clipped 0–2)
   - Add flags: `coinbase_flag`, `rho_flag_div0`

3. **Scenario Analysis** (`scenarios.py`):
   - For each fee uplift (+10%, +25%, +50%, +100%, +200%):
     - Compute new rewards, delta fees, extra transactions
     - For each rho candidate: BTC commitment = rho × reward_value
     - Calculate APY impact: (per_cycle_btc / stacked_supply) × 365/14 × 100

4. **Outputs**:
   - Tenure panel (Parquet + CSV)
   - Scenario tables (CSV)
   - Visualizations (Plotly HTML)

### Key Architecture Patterns

### API Usage Hierarchy

**IMPORTANT**: Always prefer Hiro API for Stacks blockchain data. Only use other providers when Hiro doesn't offer the needed functionality.

**Primary Data Source - Hiro API** (https://api.hiro.so):
- ✅ **Transaction history** (`/extended/v1/tx`) - canonical source for wallet metrics
- ✅ **Burnchain rewards** (`/extended/v1/burnchain/rewards`) - miner BTC commits
- ✅ **Block metadata** (`/extended/v1/block/by_burn_block_height/{h}`) - anchor blocks
- ✅ **PoX cycles** (`/extended/v2/pox/cycles`) - stacking periods
- ✅ **Most reliable** - stable, well-documented, required for core functionality
- ⚠️ Requires `HIRO_API_KEY` in environment

**Secondary - CoinGecko** (https://api.coingecko.com/api/v3):
- Use for: STX/BTC price history when Hiro doesn't provide it
- Reliability: Good for historical prices
- Rate limits: 10-50 calls/min (free tier)

**Tertiary - Signal21** (https://api-test.signal21.io):
- Use ONLY when absolutely necessary:
  - SQL queries for custom fee aggregations (if Hiro can't provide)
  - Price data fallback (if CoinGecko fails)
- ⚠️ **Known issues**: Unreliable, frequent 500 errors, slow responses
- ⚠️ **Avoid for production** - use only as last-resort fallback

**Design principle**: If you can get data from Hiro, use Hiro. Minimize Signal21 usage.

**Caching Strategy**:
- **File-based**: JSON in `data/raw/` (raw API responses), Parquet in `data/cache/` (cleaned data)
- **Deterministic keys**: SHA256 hash of (method, URL, params, body)
- **TTL support**: Optional expiration (default 1 hour for API responses)
- **Graceful fallback**: On cache invalid or API failure, use secondary provider or cached data

**Error Handling & Resilience**:
- **Transient errors**: 429, 500–504, 522 → exponential backoff with jitter (config: `DEFAULT_RETRY_CONFIG`)
- **Adaptive chunking**: On API limits/500 errors, halve request window (30→15→5 days) and retry
- **Fallback chain**: CoinGecko → Signal21 → Placeholder for prices; cached data always preferred over failure

**HTTP Layer** (`http_utils.py`):
- `cached_json_request()` abstracts retry, caching, session management
- `TransientHTTPError` for retryable failures
- `RequestOptions` dataclass for configuring timeouts, retry behavior, cache TTL

### Configuration Management

**Centralized config** (`src/config.py`):
```python
# Paths
DATA_DIR = Path("data")
CACHE_DIR = DATA_DIR / "cache"
OUT_DIR = Path("out")

# API Endpoints
SIGNAL21_BASE = "https://api-test.signal21.io"  # env: SIGNAL21_BASE override
HIRO_BASE = "https://api.hiro.so"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Retry policy (exponential backoff, jitter, max attempts)
DEFAULT_RETRY_CONFIG = RetryConfig(
    wait_min_seconds=0.5,
    wait_max_seconds=8.0,
    max_attempts=5,
    status_forcelist=(429, 500, 502, 503, 504, 522),
)

# Default analysis horizon
DEFAULT_HISTORY_DAYS = 365  # env: DEFAULT_HISTORY_DAYS
```

**Environment variables** (via `.env`):
- `HIRO_API_KEY` (required)
- `SIGNAL21_BASE` (optional override)
- `DEFAULT_HISTORY_DAYS` (optional window)

**Notebook parameters** (papermill-compatible):
- `HISTORY_DAYS`: Days to pull (default from config)
- `FORCE_REFRESH`: Bypass cache and fetch fresh data

## Testing Approach

### Test Structure
```
tests/
├── test_caching.py          # Cache hit/miss for prices, fees, rewards
├── test_http_utils.py       # HTTP retry logic, caching layer
├── test_panel_builder.py    # Panel joins, rho computation, cycle annotation
└── test_scenarios.py        # Scenario table generation
```

### Testing Patterns
- **Mocking**: Use `monkeypatch` fixtures to replace API calls with stubs
- **Cache isolation**: Temporary directories per test
- **No live API calls**: All external services mocked in unit tests
- **Integration smoke test**: `make smoke-notebook` runs 30-day window with `force_refresh=False` (cache-only)

### Coverage Requirements
- All new logic requires pytest coverage (`tests/test_<module>.py`)
- Mock external HTTP calls (Signal21, Hiro) with fixtures
- Maintain ≥80% line coverage; document exceptions in PR

## Development Workflow

### Issue Tracking with Beads

This project uses [bd (beads)](https://github.com/steveyegge/beads) for issue tracking:

```bash
bd ready --json                # List unblocked issues before picking tasks
bd create "Title" -t task|feature|bug -p 0-4 --json  # Create issue
bd update <id> --status in_progress --json          # Claim work
bd close <id> --reason "Done" --json                # Complete issue
bd list --json                                       # List all issues
```

**State tracking**: `.beads/issues.jsonl` is version-controlled; never edit manually.

### Commit Guidelines

- **Conventional Commits**: Use `feat:`, `fix:`, `docs:`, `refactor:`, `test:`
- **Bead references**: Include bead IDs (`bd-###`) in commit descriptions
- **Scope commits narrowly**: Avoid mixing unrelated changes
- **Keep secrets out**: Never commit `.env`, API keys, or sensitive data

### Pull Request Process

1. Reference bead ID in PR description
2. Describe validation steps (e.g., "ran `make notebook`, checked outputs")
3. Attach screenshots when visuals change
4. Ensure CI passes (`make test` + `make lint`)
5. Close bead after merge: `bd close <id> --reason "Merged in PR #N"`

## Agent-Specific Instructions

### Pre-completion Verification

**CRITICAL**: Always execute the notebook locally before reporting completion:
- Use `make notebook` or `make smoke-notebook`
- Verify end-to-end success (no exceptions, outputs generated)
- If failures occur, surface logs and investigate before claiming completion

### Cache Management

- **Selective clearing**: Use `make refresh-prices` to drop price caches only
- **Full reset**: Use `make clean` to wipe all cached data and outputs
- **Never commit**: `data/raw/`, `data/cache/`, `out/` stay local (see `.gitignore`)

### Preferred Workflow

1. **Local JupyterLab** (see `docs/local.md` for full setup) is the primary interactive environment
2. **Papermill** for headless/CI execution
3. **Colab** (see `docs/colab.md`) is optional and should rely on cached artifacts when APIs are unstable

### When Working on Data Fetching

- **Respect retry logic**: Don't bypass `http_utils.cached_json_request()`
- **Test fallbacks**: Verify secondary providers work when primary fails
- **Adaptive chunking**: When adding new endpoints, implement window halving for large date ranges
- **Cache invalidation**: Use TTL appropriately (short for volatile data, longer for historical)

### When Working on Analysis

- **Operate on DataFrames**: `panel_builder.py` and `scenarios.py` should not call APIs directly
- **Document assumptions**: Especially for derived metrics like `rho` (commitment ratio)
- **Validate scenarios**: Ensure uplift percentages and APY calculations match product requirements

## Background Execution Best Practices

**IMPORTANT**: Maximize efficiency by running long-running tasks in the background whenever possible.

### When to Use Background Execution

**ALWAYS use background execution for:**
- Full notebook runs (`make notebook-bg` instead of `make notebook`)
- Any task that takes >30 seconds
- Data fetching operations that don't require immediate feedback
- Test suites that produce pass/fail results
- Build processes

**Use foreground execution for:**
- Interactive debugging
- Single cell execution where you need immediate output
- Quick validation commands (<10 seconds)

### Background Execution Commands

```bash
# Notebook execution
make notebook-bg     # Launch papermill in background, logs to out/notebook.log
make notebook-tail   # Follow logs in real-time (tail -f out/notebook.log)
make notebook-status # Check if background process is still running
make notebook-stop   # Terminate background execution

# Generic background pattern for any command
<command> > output.log 2>&1 &  # Run in background, redirect output
tail -f output.log              # Monitor progress
jobs                            # List background jobs
kill %1                         # Kill job #1
```

### Monitoring Background Processes

**Best practices:**
1. **Always log to a file**: Use `tee` or redirect to capture output for later review
2. **Check completion**: Use `BashOutput` tool or `jobs` command to verify status
3. **Verify outputs**: After completion, check that expected files were created
4. **Review logs**: Always examine logs for warnings/errors even if process succeeded

**Example workflow:**
```bash
# 1. Start background task
make notebook-bg

# 2. Monitor progress (optional, can continue other work)
make notebook-tail  # Ctrl+C to stop following

# 3. Check if still running
make notebook-status

# 4. After completion, verify outputs
ls -lh out/         # Check files were created
tail -50 out/notebook.log  # Review final log lines
```

### Agent Workflow Guidance

**When working on tasks:**
1. **Launch background processes immediately** for long-running operations
2. **Continue with other work** while processes run (e.g., update documentation, review code)
3. **Use `BashOutput` tool** to check progress without blocking
4. **Batch independent tasks**: Launch multiple background processes in parallel when possible
5. **Report progress**: Inform user that process is running in background and estimated completion time

**Example pattern:**
```
User: "Run the full notebook and update the docs"
Assistant:
1. Launches `make notebook-bg` (3-4 min estimated)
2. Immediately starts updating docs while notebook runs
3. Checks notebook completion with BashOutput
4. Verifies outputs after both tasks complete
```

### Common Pitfalls to Avoid

❌ **Don't**: Run `make notebook` and wait idle for 3-4 minutes
✅ **Do**: Run `make notebook-bg` and continue with other tasks

❌ **Don't**: Run sequential commands when they can be parallelized
✅ **Do**: Launch independent background processes simultaneously

❌ **Don't**: Forget to check background process completion
✅ **Do**: Use `make notebook-status` or BashOutput before declaring completion

❌ **Don't**: Ignore background process logs
✅ **Do**: Review logs even when exit code is 0 (warnings matter)

## Documentation References

- `README.md` – Quick start, project goals, caching strategy
- `AGENTS.md` – Contribution workflow (beads, commits, testing)
- `docs/reset-plan.md` – Stabilization roadmap and objectives
- `docs/local.md` – Detailed local JupyterLab workflow
- `docs/colab.md` – Optional hosted workflow
- `@PRD.md` – Original product requirements (scope, metrics, data requirements)

## Code Quality Standards

- **Formatting**: Black (88-char lines)
- **Linting**: Ruff (import sorting, F-string checks, unused imports)
- **Type hints**: Encouraged in `src/`, especially for public APIs
- **Docstrings**: Required for public functions in `src/`
- **Notebook hygiene**: Import from `src/`, avoid ad-hoc logic duplication in cells
