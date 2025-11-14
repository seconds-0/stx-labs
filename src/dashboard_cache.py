"""Cache heavy dashboard aggregates so builds can read precomputed data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Sequence

import pandas as pd

from . import config as cfg
from . import roi
from . import wallet_metrics
from . import wallet_value
from .cache_utils import read_parquet, write_parquet

CACHE_VERSION = "v1"
CACHE_DIR = cfg.CACHE_DIR / "dashboard_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
META_PATH = CACHE_DIR / f"meta_{CACHE_VERSION}.json"

WALLET_ACTIVITY_PATH = CACHE_DIR / f"wallet_activity_{CACHE_VERSION}.parquet"
WALLET_FIRST_SEEN_PATH = CACHE_DIR / f"wallet_first_seen_{CACHE_VERSION}.parquet"
WALLET_NEW_PATH = CACHE_DIR / f"wallet_new_wallets_{CACHE_VERSION}.parquet"
WALLET_ACTIVE_PATH = CACHE_DIR / f"wallet_active_wallets_{CACHE_VERSION}.parquet"
WALLET_RETENTION_PATH = CACHE_DIR / f"wallet_retention_cumulative_{CACHE_VERSION}.parquet"
WALLET_RETENTION_ACTIVE_PATH = CACHE_DIR / f"wallet_retention_active_band_{CACHE_VERSION}.parquet"
WALLET_FEE_PATH = CACHE_DIR / f"wallet_fee_per_wallet_{CACHE_VERSION}.parquet"

ROI_WINDOWS_PATH = CACHE_DIR / f"roi_windows_agg_{CACHE_VERSION}.parquet"
ROI_CLASSIFICATION_PATH = CACHE_DIR / f"roi_classification_{CACHE_VERSION}.parquet"


@dataclass(frozen=True)
class DashboardCacheMeta:
    generated_at: datetime
    max_days: int
    wallet_windows: tuple[int, ...]
    roi_windows: tuple[int, ...]


def _write_meta(meta: DashboardCacheMeta) -> None:
    payload = {
        "generated_at": meta.generated_at.isoformat(),
        "max_days": meta.max_days,
        "wallet_windows": list(meta.wallet_windows),
        "roi_windows": list(meta.roi_windows),
    }
    META_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_metadata() -> DashboardCacheMeta | None:
    if not META_PATH.exists():
        return None
    payload = json.loads(META_PATH.read_text(encoding="utf-8"))
    generated_at = datetime.fromisoformat(payload["generated_at"])
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)
    return DashboardCacheMeta(
        generated_at=generated_at,
        max_days=int(payload["max_days"]),
        wallet_windows=tuple(int(w) for w in payload["wallet_windows"]),
        roi_windows=tuple(int(w) for w in payload["roi_windows"]),
    )


def refresh_dashboard_cache(
    *,
    max_days: int,
    wallet_windows: Sequence[int],
    roi_windows: Sequence[int],
    force_refresh: bool = False,
    wallet_db_path: Path | None = None,
    ensure_wallet_balances: bool = False,
) -> DashboardCacheMeta:
    """Recompute wallet + ROI aggregates and persist them to parquet files."""

    wallet_windows = tuple(sorted({int(w) for w in wallet_windows if int(w) > 0}))
    roi_windows = tuple(sorted({int(w) for w in roi_windows if int(w) > 0}))

    wallet_metrics.ensure_transaction_history(
        max_days=max_days,
        force_refresh=force_refresh,
    )
    activity = wallet_metrics.load_recent_wallet_activity(
        max_days=max_days,
        db_path=wallet_db_path,
    )
    first_seen = wallet_metrics.update_first_seen_cache(activity)

    window_origin = datetime.now(UTC) - timedelta(days=max_days)
    summary_start = pd.Timestamp(window_origin).floor("D")
    new_wallets = wallet_metrics.compute_new_wallets(first_seen, summary_start)
    active_wallets = wallet_metrics.compute_active_wallets(activity, summary_start)

    retention_cumulative = wallet_metrics.compute_retention(
        activity,
        first_seen,
        wallet_windows,
        mode="cumulative",
    )
    retention_active_band = wallet_metrics.compute_retention(
        activity,
        first_seen,
        wallet_windows,
        mode="active_band",
    )
    fee_per_wallet = wallet_metrics.compute_fee_per_wallet(
        activity,
        first_seen,
        wallet_windows,
    )

    thresholds = wallet_value.ClassificationThresholds()
    if ensure_wallet_balances and not first_seen.empty:
        activation_df = wallet_value.compute_activation(first_seen)
        recent_cutoff = datetime.now(UTC) - timedelta(days=max_days)
        recent_addresses = activation_df[
            activation_df["activation_time"] >= recent_cutoff
        ]["address"].astype(str)
        if not recent_addresses.empty:
            wallet_metrics.ensure_wallet_balances(
                recent_addresses.tolist(),
                as_of_date=datetime.now(UTC).date(),
                funded_threshold_stx=thresholds.funded_stx_min,
                db_path=wallet_db_path,
            )

    price_panel = wallet_value.load_price_panel_for_activity(
        activity,
        force_refresh=force_refresh,
    )
    windows_agg = wallet_value.compute_wallet_windows(
        activity,
        first_seen,
        price_panel,
        windows=roi_windows,
    )
    classification = wallet_value.classify_wallets(
        first_seen=first_seen,
        activity=activity,
        windows_agg=windows_agg,
        thresholds=thresholds,
        wallet_db_path=wallet_db_path,
    )

    if not first_seen.empty:
        wallet_metrics.ensure_activation_day_funded_snapshots(
            first_seen,
            lookback_days=min(7, max_days),
            funded_threshold_stx=thresholds.funded_stx_min,
            db_path=wallet_db_path,
        )
    funded_activation = wallet_metrics.collect_activation_day_funding(
        first_seen,
        db_path=wallet_db_path,
        persist=True,
    )
    value_flags = wallet_metrics.compute_value_flags(activity, first_seen)
    segmented_windows = sorted(
        {int(w) for w in roi_windows} | set(int(w) for w in roi.RETENTION_CURVE_WINDOWS)
    )
    wallet_metrics.compute_segmented_retention_panel(
        activity,
        first_seen,
        segmented_windows,
        funded_activation=funded_activation,
        value_flags=value_flags,
        db_path=wallet_db_path,
    )
    wallet_metrics.compute_segmented_retention_panel(
        activity,
        first_seen,
        segmented_windows,
        funded_activation=funded_activation,
        value_flags=value_flags,
        db_path=wallet_db_path,
        mode="survival",
        persist_path=wallet_metrics.SEGMENTED_RETENTION_SURVIVAL_PATH,
        persist_db=False,
    )

    write_parquet(WALLET_ACTIVITY_PATH, activity)
    write_parquet(WALLET_FIRST_SEEN_PATH, first_seen)
    write_parquet(WALLET_NEW_PATH, new_wallets)
    write_parquet(WALLET_ACTIVE_PATH, active_wallets)
    write_parquet(WALLET_RETENTION_PATH, retention_cumulative)
    write_parquet(WALLET_RETENTION_ACTIVE_PATH, retention_active_band)
    write_parquet(WALLET_FEE_PATH, fee_per_wallet)
    write_parquet(ROI_WINDOWS_PATH, windows_agg)
    write_parquet(ROI_CLASSIFICATION_PATH, classification)

    meta = DashboardCacheMeta(
        generated_at=datetime.now(UTC),
        max_days=max_days,
        wallet_windows=wallet_windows,
        roi_windows=roi_windows,
    )
    _write_meta(meta)
    return meta


def _safe_read(path: Path) -> pd.DataFrame | None:
    df = read_parquet(path)
    if df is None:
        return None
    return df


def _df_or_empty(path: Path) -> pd.DataFrame:
    df = _safe_read(path)
    if df is None:
        return pd.DataFrame()
    return df


def load_wallet_bundle_from_cache() -> tuple[wallet_metrics.WalletMetricsBundle, pd.DataFrame] | tuple[None, None]:
    """Return cached wallet bundle + active-band retention if available."""

    required_paths = [
        WALLET_ACTIVITY_PATH,
        WALLET_FIRST_SEEN_PATH,
        WALLET_NEW_PATH,
        WALLET_ACTIVE_PATH,
        WALLET_RETENTION_PATH,
        WALLET_FEE_PATH,
    ]
    if not all(path.exists() for path in required_paths):
        return None, None

    bundle = wallet_metrics.WalletMetricsBundle(
        activity=_df_or_empty(WALLET_ACTIVITY_PATH),
        first_seen=_df_or_empty(WALLET_FIRST_SEEN_PATH),
        new_wallets=_df_or_empty(WALLET_NEW_PATH),
        active_wallets=_df_or_empty(WALLET_ACTIVE_PATH),
        retention=_df_or_empty(WALLET_RETENTION_PATH),
        fee_per_wallet=_df_or_empty(WALLET_FEE_PATH),
    )
    retention_active = _df_or_empty(WALLET_RETENTION_ACTIVE_PATH)
    return bundle, retention_active


def load_roi_inputs_from_cache() -> roi.RoiInputs | None:
    """Return cached ROI inputs when all artefacts are present."""

    required_paths = [
        WALLET_ACTIVITY_PATH,
        WALLET_FIRST_SEEN_PATH,
        ROI_WINDOWS_PATH,
        ROI_CLASSIFICATION_PATH,
    ]
    if not all(path.exists() for path in required_paths):
        return None

    activity = _df_or_empty(WALLET_ACTIVITY_PATH)
    first_seen = _df_or_empty(WALLET_FIRST_SEEN_PATH)
    retention_active = _df_or_empty(WALLET_RETENTION_ACTIVE_PATH)
    windows_agg = _df_or_empty(ROI_WINDOWS_PATH)
    classification = _df_or_empty(ROI_CLASSIFICATION_PATH)
    retention_segmented = wallet_metrics.load_retention_segmented_survival()
    retention_segmented_cumulative = wallet_metrics.load_retention_segmented()
    funded_activation = wallet_metrics.collect_activation_day_funding(
        first_seen,
        persist=False,
    )
    return roi.RoiInputs(
        activity=activity,
        first_seen=first_seen,
        retention=retention_active,
        windows_agg=windows_agg,
        classification=classification,
        retention_segmented=retention_segmented,
        retention_segmented_cumulative=retention_segmented_cumulative,
        funded_activation=funded_activation,
        data_start=wallet_metrics.METRICS_DATA_START,
    )
