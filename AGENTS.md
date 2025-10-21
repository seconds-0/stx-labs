# Repository Guidelines

## Project Structure & Module Organization
- `notebooks/` – primary Jupyter notebooks, including `stx_pox_flywheel.ipynb`.
- `src/` – reusable Python modules (data clients, transforms, scenario logic).
- `tests/` – pytest suite mirroring `src/` layout.
- `data/raw/` – cached API payloads; keep out of version control.
- `out/` – generated parquet, CSV, and chart artifacts.
- `.beads/` – issue tracker state; never edit manually.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate` – create/enter isolated environment.
- `pip install -r requirements.txt` – install notebook + helper dependencies.
- `jupyter lab` – launch local development environment.
- `pytest` – run automated tests (fast, default suite).
- `pytest --maxfail=1 --cov=src` – coverage-focused smoke before PRs.
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
- Track all work through beads CLI (`bd`); avoid markdown TODOs.
- Respect cache directories: wipe `data/raw/` selectively, never commit secrets or API keys.
- For hosted execution, follow `docs/colab.md` to run notebooks in Google Colab with secrets managed via the Colab Secrets API.
