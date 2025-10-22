# Local Jupyter Workflow

## 1. Environment Setup
- Requires Python 3.11+. Recommended layout keeps dependencies isolated in `.venv/`.
- Run from the repo root:
  ```bash
  make setup
  ```
- Copy `.env.example` (if present) or create `.env` with `HIRO_API_KEY=<your-key>` and other secrets. `src.config` loads this automatically.

## 2. Launching JupyterLab
- Start the notebook server inside the virtual environment:
  ```bash
  source .venv/bin/activate
  jupyter lab              # or: make lab
  ```
- Always launch from the repository root (`make lab` does this automatically); the notebook now chdirs to the project root so imports resolve without manual tweaking.
- Open `notebooks/stx_pox_flywheel.ipynb`. All imports resolve relative to the repo, so run top-to-bottom without extra path tweaks.

## 3. Running Tests & Formatting
- Execute the unit tests from the repo root:
  ```bash
  make test
  ```
- Optional lint/format (if editing source code):
  ```bash
  make lint
  ```

## 4. Regenerating Outputs
- Notebook writes artifacts to `./out/` and caches API pulls under `./data/raw/` + `./data/cache/`. Remove stale caches if needed:
  ```bash
  rm -rf data/raw/* data/cache/* out/*
  ```
- Re-run notebook to recreate exports (Parquet, CSV, charts).

## 5. Headless Execution (optional)
- Use `papermill` when you need scheduled or reproducible runs without the UI:
  ```bash
  make notebook
  ```
- Attach parameters via `-p NAME VALUE` if you want different windows or toggles.
- Quick smoke run (30-day window, no refresh):
  ```bash
  make smoke-notebook
  ```

## 6. Git Workflow
- Standard sequence:
  ```bash
  git pull --ff-only
  # make edits / run notebook
  git status
  git add <files>
  git commit -m "..."
  git push
  ```
- Use beads (`bd ready`, `bd update`) to track work; `.beads/issues.jsonl` stays under version control automatically.
- If API rate limits or 500 errors appear when using full history, temporarily set `USE_FULL_HISTORY = False` and choose a narrower `START_DATE`; Signal21's public test endpoint can struggle with multi-year ranges.
