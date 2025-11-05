# Repository Guidelines

## Project Structure & Module Organization
- `notebooks/` – primary Jupyter notebooks, including `stx_pox_flywheel.ipynb`.
- `src/` – reusable Python modules (data clients, transforms, scenario logic).
- `tests/` – pytest suite mirroring `src/` layout.
- `data/raw/` – cached API payloads; keep out of version control.
- `out/` – generated parquet, CSV, and chart artifacts.
- `.beads/` – issue tracker state; never edit manually.

## Build, Test, and Development Commands
- `make setup` – create/enter virtualenv and install dependencies.
- `make lab` – launch JupyterLab from repo root (preferred interactive flow).
- `make test` – run automated tests (fast, default suite).
- `make lint` – format/lint via black + ruff.
- `make notebook` – papermill execution to `out/stx_pox_flywheel_run.ipynb`.
- `bd ready --json` – list unblocked beads issues prior to picking tasks.

## Coding Style & Naming Conventions
- Python formatted with `black` (PEP 8, 88-char lines) and linted via `ruff`.
- Favor type hints in `src/`, docstrings for public functions, and descriptive module names (`prices_client.py`, `pox_scenarios.py`).
- Notebook cells should import from `src/`, avoid ad-hoc logic duplication.

## Testing Guidelines
- All new logic requires accompanying pytest coverage under `tests/` using `test_<module>.py`.
- Mock external HTTP calls (Signal21, Hiro) with fixtures; never hit live APIs in unit tests.
- Maintain ≥80% line coverage; document exceptions in PR description.

## Commit & Pull Request Guidelines
- Use Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`) for clarity and release tooling.
- Scope commits narrowly; include data or notebook artifacts only when necessary and reproducible.
- PRs must reference bead IDs (`bd-###`), describe validation steps, and attach key screenshots (plots) when visuals change.
- Ensure CI (pytest + formatting) passes before requesting review.

## Agent-Specific Instructions
- Always execute the notebook locally (papermill or make targets) and confirm end-to-end success before reporting completion; surface any failures with logs.
- Track all work through beads CLI (`bd`); avoid markdown TODOs.
- Respect cache directories: wipe `data/raw/` or `data/cache/` selectively, never commit secrets or API keys.
- Preferred workflow is local JupyterLab (see `docs/local.md` for full setup). Colab (`docs/colab.md`) is optional and should rely on cached artifacts when APIs are unstable.

## Git Worktree Management

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
