# Scripts Directory

| Script | Status | Notes |
| --- | --- | --- |
| `backfill_wallet_history.py` | Active pipeline | Primary wallet history ingestor (see `docs/runbooks/backfill.md`). |
| `check_backfill_status.py` | Active helper | Prints DuckDB stats + coverage progress. |
| `monitor_backfill.py` | Active helper | Long-running monitor for tmux/backfill sessions. |
| `build_dashboards.py` | Active pipeline | Generates wallet/value/macro dashboards. |
| `validate_wallet_metrics.py` | Active helper | Sanity checks on cached wallet metrics. |
| `sync_env.sh` | Active helper | Copies `.env` into every worktree. |
| `watch_notebook.sh` | Active helper | Tails notebook logs. |
| `backfill_tmux.sh`, `backfill_health_check.sh` | Operational | Convenience wrappers around the backfill pipeline. |
| `seed_wallet_value_beads.py` | Legacy | Used once to seed beads DB; kept for auditability. |

Guidelines:
- Add new automation under `scripts/` and document it here.
- Clearly mark one-off or deprecated helpers so contributors know what is safe to modify.
- Prefer wiring make targets or runbooks to the active scripts instead of duplicating commands elsewhere.
