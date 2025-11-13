# Wallet Value Runbook

Step-by-step instructions for computing wallet funnel metrics, WALTV, and
refreshing the dashboards described in `docs/wallet_value_plan.md`.

---

## 1. Prerequisites

- `.env` present in the active worktree with `HIRO_API_KEY` and `COIN_GECKO_KEY`
  (`./scripts/sync_env.sh` will copy it to every worktree).
- Virtualenv bootstrapped via `make setup`.
- DuckDB backfill covering at least 365 days (run `docs/runbooks/backfill.md`).

---

## 2. Refresh the Value Pipeline

```bash
source .venv/bin/activate
python scripts/build_dashboards.py \
  --wallet-max-days 365 \
  --wallet-windows 15 30 60 90 \
  --force-refresh    # optional when prices/hiro caches must be invalidated
```

This command:
1. Ensures wallet activity is up to date (Hiro tx cache).
2. Loads STX/BTC price panel for the full window.
3. Computes Network Value (NV) + WALTV windows.
4. Classifies wallets (funded, active, value).
5. Writes HTML dashboards to `out/value` (or `public/value` if publishing).

### 2a. Build the ROI One-Pager

See `docs/roi_one_pager_spec.md` for full definitions. The dashboard can run standalone (skipping wallet/value/macro) or alongside the standard build.

```bash
python scripts/build_dashboards.py \
  --one-pager-only \
  --wallet-max-days 365 \
  --roi-windows 15 30 60 90 180 \
  --wallet-db-snapshot \
  --cac-file data/external/cac_by_channel.csv \
  --channel-map-file data/external/address_channel_map.csv \
  [--ensure-wallet-balances]
```

Flags:
- `--one-pager-only` limits the run to `public/roi/index.html`. Omit it to build ROI plus the normal dashboards.
- `--roi-windows` controls the activation horizons for retention + WALTV tiles (defaults to `15 30 60 90 180`).
- `--cac-file` / `--channel-map-file` feed the payback table; when omitted the page falls back to breakeven CPA guidance.
- `--incentives-file` (optional) validates incentive inputs ahead of future tiles.
- `--ensure-wallet-balances` forces a funded snapshot refresh for recent wallets (useful before deploying, but omit it if Hiro limits are tight—the ROI math doesn't require funded classification today).

Outputs land in `out/roi_dashboard.html` and copy to `public/roi/index.html` when `--public-dir` is left at its default.

---

## 3. Validation Checklist

1. `make test` – unit tests including `tests/test_wallet_value.py`.
2. `make lint` – formatting + ruff.
3. Optional: `make notebook` to ensure the PoX notebook ingests updated caches.
4. Spot-check `public/value/index.html` (or artifact directory) locally.

---

## 4. Operational Notes

- **Price panel gaps:** If CoinGecko fails, Signal21 fallback is automatic. Use
  `--force-refresh` to retry a failed panel download.
- **Balance lookups:** `fetch_address_balances` caches responses for 6 hours in
  `data/raw/hiro_address_balances_*`. Avoid force-refreshing balances unless a
  data issue is suspected.
- **Windows:** Default `(15, 30, 60, 90)` but the module supports arbitrary
  positive integers. Keep 30 in the list for funnel classification.
- **Dash destination:** By default the script writes into `public/`. To keep the
  repo clean, prefer generating into `out/public` and deploying from there.
- **Backfill still running?** Use `--value-only --wallet-db-snapshot` to clone
  the DuckDB file and skip `ensure_transaction_history`, e.g.:

  ```bash
  python scripts/build_dashboards.py --value-only --wallet-db-snapshot --wallet-max-days 365 --cpa-target-stx 5
  ```

  The snapshot is deleted automatically after the run.
- **CPA Target:** `--cpa-target-stx` controls the payback panel threshold (default 5 STX).
- **Dashboard Content:** The value dashboard now surfaces:
- KPI header (30d NV, WALTV stats, funded→value conversion, PoX APY snapshot).
  - PoX APY uses per-cycle STX/BTC averages so the percentage is BTC-denominated and comparable to alternative yields.
  - Trailing KPIs: Last‑30/60/90 (calendar-anchored) avg/median, alongside WALTV‑30/60/90 (activation-anchored) with deltas.
  - Network trend (30d rolling NV vs fees).
  - ROI/CPA panels for 30/60/90d WALTV relative to the CPA target.
  - PoX linkage chart/table showing miner BTC commits vs APY.
  - WALTV window comparison table for 30/60/90d cohorts.

---

## 5. Troubleshooting

| Issue | Fix |
| --- | --- |
| `KeyError: 'stx_btc'` | Ensure price panel returned data; rerun with `--force-refresh` |
| `HIRO API` errors | Confirm API key in `.env`, rerun `./scripts/sync_env.sh`, respect rate limits |
| Empty dashboard tables | Backfill insufficient; rerun wallet history runbook |
| High latency | Reduce `--wallet-max-days` temporarily or drop older windows |

---

## 6. Related Docs

- Strategy & definitions: `docs/wallet_value_plan.md`
- Beads plan: `docs/beads_wallet_value.md`
- Backfill playbook: `docs/runbooks/backfill.md`
