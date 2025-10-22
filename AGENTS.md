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
