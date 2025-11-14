#!/usr/bin/env python3
"""Precompute wallet + ROI aggregates so dashboard builds can reuse them."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import dashboard_cache


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wallet-max-days",
        type=int,
        default=365,
        help="History window (days) for wallet/ROI aggregates (default: 365).",
    )
    parser.add_argument(
        "--wallet-windows",
        type=int,
        nargs="+",
        default=[15, 30, 60, 90],
        help="Wallet dashboard retention windows (default: 15 30 60 90).",
    )
    parser.add_argument(
        "--roi-windows",
        type=int,
        nargs="+",
        default=[15, 30, 60, 90, 180],
        help="ROI dashboard windows (default: 15 30 60 90 180).",
    )
    parser.add_argument(
        "--wallet-db-path",
        type=Path,
        help="Optional DuckDB path override (defaults to data/cache/wallet_metrics.duckdb).",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Drop cached transactions before refreshing aggregates.",
    )
    parser.add_argument(
        "--ensure-wallet-balances",
        action="store_true",
        help="Refresh funded balance snapshots while rebuilding the cache.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    meta = dashboard_cache.refresh_dashboard_cache(
        max_days=args.wallet_max_days,
        wallet_windows=args.wallet_windows,
        roi_windows=args.roi_windows,
        force_refresh=args.force_refresh,
        wallet_db_path=args.wallet_db_path,
        ensure_wallet_balances=args.ensure_wallet_balances,
    )
    print(
        f"[dashboard-cache] Generated at {meta.generated_at.strftime('%Y-%m-%d %H:%M UTC')} "
        f"for max_days={meta.max_days}, wallet_windows={meta.wallet_windows}, roi_windows={meta.roi_windows}"
    )


if __name__ == "__main__":
    main()
