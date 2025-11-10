# Repository Guidelines

## 1. Mission, KPIs, and Data Sources
- **North Star:** Grow fee-denominated Network Value (NV) so PoX yields remain competitive and Stacks becomes the default BTC execution layer. Wallet funnels (funded → active → value) and WALTV (wallet-adjusted LTV) are our shared KPI set.
- **Key docs:**  
  - Strategy & plan: `docs/wallet_value_plan.md`, `docs/beads_wallet_value.md`  
  - Runbooks: `docs/runbooks/backfill.md`, `docs/runbooks/wallet_value.md`, `docs/runbooks/cache_maintenance.md`  
  - Operational policies: `docs/ops/README.md` (links to AGENT/monitoring/worktree refs)  
  - Decision history: `docs/decisions/README.md` (PRDs, retros, reviews)  
  - Investigations archive: `docs/investigations/*`
- **Modules to know:**  
  - `src/wallet_metrics.py` – Hiro ingestion + DuckDB cache  
  - `src/wallet_value.py` – NV/WALTV windows, classification, CPA helpers  
  - `src/pox_yields.py` – PoX cycle summaries for dashboard linkage  
  - `scripts/build_dashboards.py` – wallet/macro/value dashboards (HTML)  
  - `scripts/backfill_wallet_history.py` & helpers – long-running ingestion  
  - `scripts/README.md` documents every automation script and status.

## 2. Standard Commands & Tooling

| Task | Command / Notes |
| --- | --- |
| Bootstrap env | `make setup` (creates `.venv`, installs requirements) |
| Launch JupyterLab | `make lab` |
| Run notebook (full) | `make notebook` (papermill to `out/stx_pox_flywheel_run.ipynb`) |
| Smoke notebook (30d) | `make smoke-notebook` |
| Tests / lint | `make test`, `make lint` |
| Wallet status | `python scripts/check_backfill_status.py --target-days 365` |
| Backfill (foreground) | `python scripts/backfill_wallet_history.py --target-days 365 --max-pages 5000 --max-iterations 0` |
| Backfill (background/tmux) | `./scripts/backfill_tmux.sh start` or `make backfill-tmux` |
| Wallet value dashboard | `python scripts/build_dashboards.py --value-only --wallet-max-days 365 --wallet-windows 15 30 60 90 --wallet-db-snapshot --cpa-target-stx 5` |
| Full dashboards | `python scripts/build_dashboards.py --wallet-max-days 365 --wallet-db-snapshot --public-dir public` |
| Sync `.env` | `./scripts/sync_env.sh` |
| Beads CLI | `bd ready`, `bd show <id>`, `bd update <id> --status ...` |

**Dashboard tips**
- `--wallet-db-snapshot` clones `wallet_metrics.duckdb` for read-only runs when the main backfill holds a lock.
- `--value-only` skips the wallet/macro dashboards to focus on WALTV updates.
- `--cpa-target-stx` controls the WALTV payback panels (default 5 STX). Document the chosen target in PRs.

**Backfill workflow**
1. Confirm `.env` present (HIRO_API_KEY) via `./scripts/sync_env.sh`.
2. Run `scripts/backfill_wallet_history.py` (use tmux + `caffeinate` for >12h jobs).  
3. Monitor with `python scripts/check_backfill_status.py` or `make backfill-status`.  
4. After completion run dashboards + `make smoke-notebook` or `make notebook`.
5. Use `make refresh-prices` or `docs/runbooks/cache_maintenance.md` for cache hygiene.

## 3. Coding + Testing Expectations
- Follow Black (88 cols) + Ruff; add type hints/docstrings to public APIs.
- Every new module/function must have pytest coverage (`tests/test_<module>.py`). Mock external APIs (Hiro, Signal21).
- WALTV features: accompany dashboard changes with unit tests in `tests/test_wallet_value.py`.
- Keep WALTV vs CPA assumptions explicit in PR description (target STX, snapshot usage, etc.).
- Never hit live APIs from tests; rely on fixtures/stubs.

## 4. Git, Beads, and Worktrees
- Use Conventional Commits with bead IDs (e.g., `feat: add wallet value KPIs (bd-123)`).
- Keep commits narrow; data artifacts only when reproducible.
- Track work in beads CLI. `bd ready` before picking tasks; update status when delivering.
- **Worktrees:** see “Git Worktree Management” below. Critical: `.env` and caches are not shared; run `./scripts/sync_env.sh` after creating or before merging.
- Prefer feature branches per bead (`git checkout -b feat/value-dashboard-aug`). Push early/often.

## 5. Agent Checklist
1. Run `bd ready` → pick issue → branch.
2. Ensure `.env` + `.venv` exist; `make setup`.
3. For wallet work: check DuckDB coverage (`check_backfill_status`). If lacking, coordinate long backfill run.
4. Implement + tests (`make test`). For dashboards, regenerate HTML locally (value-only snapshot allowed if backfill active).
5. Update docs/runbooks when workflows change (README + relevant files).
6. Provide summary, validation commands, and next steps in final response.

## 6. Git Worktree Management
(unchanged, but crucial for multi-branch workflows.)

This project uses **git worktrees** to work on multiple branches simultaneously. Each worktree is a separate working directory with its own branch checkout.

### Worktree Locations

```
/Users/alexanderhuth/Code/stx-labs/           # Main repo (usually feature branch)
/Users/alexanderhuth/Code/stx-labs/.conductor/
├── stuttgart/  # Main branch worktree
├── kuwait/     # Feature branch worktree
└── yokohama/   # (example - may not exist)
```

### Critical: Untracked Files Don't Sync Between Worktrees

**Git worktrees share commit history but NOT untracked files.** These files must be manually synced:

| File/Directory | Gitignored? | Must Sync? | Why |
|----------------|-------------|------------|-----|
| **`.env`** | ✅ Yes | **🔴 CRITICAL** | Contains API keys (HIRO_API_KEY). Required for all operations. |
| `.venv/` | ✅ Yes | ⚠️ Optional | Can rebuild with `make setup` |
| `data/cache/` | ✅ Yes | ⚠️ Optional | Speeds up notebook runs; can regenerate |
| `out/` | ✅ Yes | ❌ No | Regenerated outputs |

### Pre-Merge Checklist

**BEFORE merging a worktree branch into main:**

1. ✅ **Verify `.env` exists in target worktree**
   ```bash
   # If merging feature → main, check main worktree has .env
   ls -la /Users/alexanderhuth/Code/stx-labs/.conductor/stuttgart/.env
   # If missing, copy from main repo or another worktree
   ```

2. ✅ **Test in the target worktree**
   ```bash
   cd /Users/alexanderhuth/Code/stx-labs/.conductor/stuttgart
   make setup  # Ensure venv is up to date
   make test   # Verify tests pass
   ```

3. ✅ **Verify no uncommitted changes in target**
   ```bash
   git status  # Should be clean or only have tracked changes
   ```

### Post-Merge Checklist

**AFTER merging and before running anything:**

1. ✅ **Verify `.env` still exists**
   ```bash
   cat .env  # Should show HIRO_API_KEY and other vars
   # If missing, restore from main repo or another worktree
   ```

2. ✅ **Rebuild dependencies if `requirements.txt` changed**
   ```bash
   make setup  # Recreates venv and installs new deps
   ```

3. ✅ **Run tests to confirm merge didn't break anything**
   ```bash
   make test
   ```

4. ✅ **Optional: Run smoke test**
   ```bash
   make smoke-notebook  # 30-day quick validation
   ```

### Helper: Syncing `.env` Across Worktrees

Use the provided script to sync `.env` to all worktrees:

```bash
# Run from any worktree or main repo
./scripts/sync_env.sh
```

Or manually copy:

```bash
# Copy from main repo to all worktrees
cp /Users/alexanderhuth/Code/stx-labs/.env \
   /Users/alexanderhuth/Code/stx-labs/.conductor/stuttgart/.env

cp /Users/alexanderhuth/Code/stx-labs/.env \
   /Users/alexanderhuth/Code/stx-labs/.conductor/kuwait/.env
```

### Common Pitfalls & Solutions

**Problem**: After merge, getting `HIRO_API_KEY` not found errors
- **Cause**: `.env` file missing from worktree
- **Fix**: Copy `.env` from main repo or another worktree

**Problem**: Tests fail after merge with import errors
- **Cause**: `requirements.txt` changed but venv not updated
- **Fix**: Run `make setup` to rebuild venv

**Problem**: Notebook hangs on API calls after merge
- **Cause**: May be unrelated to merge - check Signal21/API status
- **Fix**: Check if wallet metrics (Hiro-only) works: `python scripts/validate_wallet_metrics.py`

**Problem**: Can't checkout main in main repo (error: already used by worktree)
- **Cause**: Main branch is checked out in Stuttgart worktree
- **Fix**: Work in the Stuttgart worktree instead, or remove/recreate it

### Quick Reference: Managing Worktrees

```bash
# List all worktrees
git worktree list

# Create new worktree
git worktree add .conductor/newbranch -b branch-name

# Remove worktree (must be in different worktree or main repo)
git worktree remove .conductor/stuttgart

# Prune stale worktree references
git worktree prune
```

### Agent Workflow: Merging Between Worktrees

When asked to merge work from one worktree to another:

1. **Before starting**: Check if `.env` exists in target worktree
2. **If missing**: Copy `.env` from main repo before proceeding
3. **After merge**: Immediately verify `.env` still exists
4. **Run tests**: Always run `make test` post-merge
5. **Document**: Note in commit message if `.env` was restored

**Example commit message:**
```
fix: restore .env after worktree merge

The .env file was missing after merging feature-branch into main.
Restored from main repo to ensure HIRO_API_KEY is available.
```
