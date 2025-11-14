"""Helpers for building the ROI one-pager dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Sequence

import pandas as pd

from . import wallet_metrics, wallet_value

RETENTION_CURVE_WINDOWS: tuple[int, ...] = (1, 15, 30, 60, 90, 180)


@dataclass(frozen=True)
class RoiInputs:
    activity: pd.DataFrame
    first_seen: pd.DataFrame
    retention: pd.DataFrame
    windows_agg: pd.DataFrame
    classification: pd.DataFrame
    retention_segmented: pd.DataFrame
    retention_segmented_cumulative: pd.DataFrame
    funded_activation: pd.DataFrame
    data_start: pd.Timestamp


@dataclass(frozen=True)
class RetentionPoint:
    window_days: int
    retention_pct: float
    eligible_users: int


def _cohort_sizes(first_seen: pd.DataFrame) -> pd.Series:
    if first_seen.empty:
        return pd.Series(dtype=int)
    df = first_seen.copy()
    df["activation_date"] = pd.to_datetime(df["first_seen"], utc=True).dt.floor("D")
    cohort = df.groupby("activation_date")["address"].nunique()
    cohort.name = "cohort_size"
    return cohort


def build_inputs(
    *,
    max_days: int,
    windows: Sequence[int] = (15, 30, 60, 90, 180),
    force_refresh: bool = False,
    wallet_db_path: Path | None = None,
    skip_history_sync: bool = False,
    ensure_balances: bool = False,
    include_classification: bool = False,
) -> RoiInputs:
    """Load all data required for the ROI dashboard."""
    if not skip_history_sync:
        wallet_metrics.ensure_transaction_history(
            max_days=max_days, force_refresh=force_refresh
        )
    activity = wallet_metrics.load_recent_wallet_activity(
        max_days=max_days, db_path=wallet_db_path
    )
    first_seen = wallet_metrics.update_first_seen_cache(activity)
    retention = wallet_metrics.compute_retention(
        activity,
        first_seen,
        windows,
        mode="active_band",
    )

    thresholds = wallet_value.ClassificationThresholds()
    if ensure_balances and not first_seen.empty:
        activation = wallet_value.compute_activation(first_seen)
        cutoff_ts = datetime.now(UTC) - timedelta(days=max_days)
        recent_addresses = activation[
            activation["activation_time"] >= cutoff_ts
        ]["address"].astype(str)
        if not recent_addresses.empty:
            wallet_metrics.ensure_wallet_balances(
                recent_addresses.tolist(),
                as_of_date=datetime.now(UTC).date(),
                funded_threshold_stx=thresholds.funded_stx_min,
                db_path=wallet_db_path,
            )

    price_panel = wallet_value.load_price_panel_for_activity(
        activity, force_refresh=force_refresh
    )
    windows_agg = wallet_value.compute_wallet_windows(
        activity,
        first_seen,
        price_panel,
        windows=windows,
    )
    if include_classification:
        classification = wallet_value.classify_wallets(
            first_seen=first_seen,
            activity=activity,
            windows_agg=windows_agg,
            thresholds=thresholds,
            wallet_db_path=wallet_db_path,
        )
    else:
        classification = pd.DataFrame(
            columns=["address", "activation_date", "funded", "active_30d", "value_30d"]
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
        {int(w) for w in windows if int(w) > 0} | set(RETENTION_CURVE_WINDOWS)
    )
    retention_segmented_cumulative = wallet_metrics.compute_segmented_retention_panel(
        activity,
        first_seen,
        segmented_windows,
        funded_activation=funded_activation,
        value_flags=value_flags,
        db_path=wallet_db_path,
    )
    retention_segmented = wallet_metrics.compute_segmented_retention_panel(
        activity,
        first_seen,
        segmented_windows,
        funded_activation=funded_activation,
        value_flags=value_flags,
        db_path=wallet_db_path,
        mode="active_band",
        persist_path=wallet_metrics.SEGMENTED_RETENTION_SURVIVAL_PATH,
        persist_db=False,
    )
    return RoiInputs(
        activity=activity,
        first_seen=first_seen,
        retention=retention,
        windows_agg=windows_agg,
        classification=classification,
        retention_segmented=retention_segmented,
        retention_segmented_cumulative=retention_segmented_cumulative,
        funded_activation=funded_activation,
        data_start=wallet_metrics.METRICS_DATA_START,
    )


def waltv_survivors_only(windows_agg: pd.DataFrame) -> pd.DataFrame:
    """Return survivors-only WALTV aggregates per cohort/window."""
    if windows_agg.empty or "active_in_window" not in windows_agg.columns:
        return pd.DataFrame(
            columns=[
                "activation_date",
                "window_days",
                "survivor_wallets",
                "survivor_fee_stx_sum",
                "avg_waltv_survivors_stx",
            ]
        )
    df = windows_agg[windows_agg["active_in_window"]].copy()
    if df.empty:
        return pd.DataFrame(
            columns=[
                "activation_date",
                "window_days",
                "survivor_wallets",
                "survivor_fee_stx_sum",
                "avg_waltv_survivors_stx",
            ]
        )
    if not pd.api.types.is_datetime64_any_dtype(df["activation_date"]):
        df["activation_date"] = pd.to_datetime(df["activation_date"], utc=True)
    grouped = (
        df.groupby(["activation_date", "window_days"])
        .agg(
            survivor_wallets=("address", "count"),
            survivor_fee_stx_sum=("fee_stx_sum", "sum"),
        )
        .reset_index()
    )
    grouped["avg_waltv_survivors_stx"] = grouped["survivor_fee_stx_sum"] / grouped[
        "survivor_wallets"
    ]
    return grouped


def expected_waltv_180(
    windows_agg: pd.DataFrame,
    first_seen: pd.DataFrame,
    *,
    horizon_days: int = 180,
    recent_activation_days: int = 180,
) -> float:
    """Return cohort-size weighted WALTV (labeled NV in the UI) for fully matured cohorts."""
    if windows_agg.empty or first_seen.empty:
        return 0.0
    horizon_df = windows_agg[windows_agg["window_days"] == horizon_days].copy()
    if horizon_df.empty:
        return 0.0
    if not pd.api.types.is_datetime64_any_dtype(horizon_df["activation_date"]):
        horizon_df["activation_date"] = pd.to_datetime(
            horizon_df["activation_date"], utc=True
        )
    cohort_sizes = _cohort_sizes(first_seen)
    horizon_totals = (
        horizon_df.groupby("activation_date")["fee_stx_sum"].sum().reset_index()
    )
    merged = horizon_totals.merge(
        cohort_sizes.rename("cohort_size"),
        on="activation_date",
        how="left",
    ).dropna(subset=["cohort_size"])
    if merged.empty:
        return 0.0
    today = pd.Timestamp(datetime.now(UTC)).floor("D")
    start_date = today - pd.Timedelta(days=horizon_days + recent_activation_days)
    end_date = today - pd.Timedelta(days=horizon_days)
    # Only include cohorts that have fully matured (>= horizon_days old) but
    # whose activation is still part of the recent inflow window so the KPI
    # stays relevant for current acquisition decisions.
    merged = merged[
        (merged["activation_date"] >= start_date)
        & (merged["activation_date"] <= end_date)
    ]
    if merged.empty:
        return 0.0
    numerator = (merged["fee_stx_sum"]).sum()
    denominator = merged["cohort_size"].sum()
    if not denominator:
        return 0.0
    return float(numerator / denominator)


def summarize_waltv_by_window(
    windows_agg: pd.DataFrame, first_seen: pd.DataFrame
) -> pd.DataFrame:
    """Return cohort-size-weighted WALTV averages (all wallets).

    The dashboard currently labels these values as NV because WALTV == NV until
    derived value/incentives are implemented. Remove this note and restore the
    WALTV label once that work lands.
    """
    if windows_agg.empty or first_seen.empty:
        return pd.DataFrame(
            columns=[
                "activation_date",
                "window_days",
                "cohort_size",
                "avg_waltv_all_stx",
                "total_fee_stx",
            ]
        )
    df = windows_agg.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["activation_date"]):
        df["activation_date"] = pd.to_datetime(df["activation_date"], utc=True)
    cohort_sizes = _cohort_sizes(first_seen)
    totals = (
        df.groupby(["activation_date", "window_days"])["fee_stx_sum"]
        .sum()
        .reset_index()
    )
    totals = totals.merge(
        cohort_sizes.rename("cohort_size"),
        on="activation_date",
        how="left",
    ).dropna(subset=["cohort_size"])
    totals["avg_waltv_all_stx"] = totals["fee_stx_sum"] / totals["cohort_size"]
    totals = totals.rename(columns={"fee_stx_sum": "total_fee_stx"})
    return totals


def active_base_breakdown(
    activity: pd.DataFrame,
    first_seen: pd.DataFrame,
    *,
    trailing_days: int = 30,
    young_threshold_days: int = 180,
) -> dict[str, float]:
    """Return wallet/fee splits for active wallets by age buckets."""
    if activity.empty or first_seen.empty:
        return {
            "young_wallets": 0,
            "legacy_wallets": 0,
            "young_fee_stx": 0.0,
            "legacy_fee_stx": 0.0,
        }
    as_of = pd.Timestamp(datetime.now(UTC)).floor("D")
    cutoff = as_of - pd.Timedelta(days=trailing_days)
    recent = activity[activity["activity_date"] >= cutoff].copy()
    if recent.empty:
        return {
            "young_wallets": 0,
            "legacy_wallets": 0,
            "young_fee_stx": 0.0,
            "legacy_fee_stx": 0.0,
        }
    activation = wallet_value.compute_activation(first_seen)
    merged = recent.merge(
        activation[["address", "activation_date"]],
        on="address",
        how="left",
    )
    merged["fee_stx"] = merged["fee_ustx"].astype(float) / wallet_value.MICROSTX_PER_STX
    young_cutoff = as_of - pd.Timedelta(days=young_threshold_days)
    merged["activation_date"] = pd.to_datetime(merged["activation_date"], utc=True)
    merged["is_young"] = merged["activation_date"] >= young_cutoff
    wallet_groups = (
        merged.groupby(["address", "is_young"])["fee_stx"]
        .sum()
        .reset_index()
    )
    young_wallets = int(
        wallet_groups.loc[wallet_groups["is_young"], "address"].nunique()
    )
    legacy_wallets = int(
        wallet_groups.loc[~wallet_groups["is_young"], "address"].nunique()
    )
    fee_summary = (
        merged.groupby("is_young")["fee_stx"].sum().rename("fee_stx").reset_index()
    )
    young_fee = float(
        fee_summary.loc[fee_summary["is_young"], "fee_stx"].sum()
        if not fee_summary.empty
        else 0.0
    )
    legacy_fee = float(
        fee_summary.loc[~fee_summary["is_young"], "fee_stx"].sum()
        if not fee_summary.empty
        else 0.0
    )
    return {
        "young_wallets": young_wallets,
        "legacy_wallets": legacy_wallets,
        "young_fee_stx": young_fee,
        "legacy_fee_stx": legacy_fee,
    }


def retention_curve_points(
    panel: pd.DataFrame,
    *,
    windows: Sequence[int],
    segments: Sequence[str] | None = None,
) -> dict[str, list[RetentionPoint]]:
    """Return retention curve points per segment for the requested windows."""

    if panel.empty or not windows:
        return {}

    window_set = sorted({int(w) for w in windows if int(w) > 0})
    if not window_set:
        return {}

    subset = panel[
        panel["window_days"].isin(window_set)
        & panel["retention_pct"].notna()
        & panel["eligible_users"].notna()
    ].copy()
    if subset.empty:
        return {}

    segments_to_use = list(segments) if segments else sorted(subset["segment"].unique())
    result: dict[str, list[RetentionPoint]] = {}
    for segment in segments_to_use:
        seg_rows = subset[subset["segment"] == segment].sort_values("window_days")
        if seg_rows.empty:
            continue
        points: list[RetentionPoint] = []
        for row in seg_rows.itertuples():
            eligible = int(getattr(row, "eligible_users", 0) or 0)
            if eligible <= 0:
                continue
            points.append(
                RetentionPoint(
                    window_days=int(row.window_days),
                    retention_pct=float(row.retention_pct),
                    eligible_users=eligible,
                )
            )
        if points:
            result[segment] = points
    return result


def retention_snapshot_summary(
    panel: pd.DataFrame,
    *,
    windows: Sequence[int],
    base_segment: str = "All",
    value_window: int = 30,
) -> dict[str, object]:
    """Summarize funded-only retention for KPI cards."""

    series_map = retention_curve_points(
        panel,
        windows=windows,
        segments=(base_segment, "Value", "Non-value"),
    )
    base_points = series_map.get(base_segment)
    if not base_points:
        return {}

    window_set = [int(w) for w in windows if int(w) > 0]
    metrics: dict[int, float] = {}
    for window in sorted(window_set):
        match = next((pt for pt in base_points if pt.window_days == window), None)
        if match:
            metrics[window] = match.retention_pct

    value_pair: dict[str, float | int | None] = {}
    if value_window:
        value_point = next(
            (pt for pt in series_map.get("Value", []) if pt.window_days == value_window),
            None,
        )
        non_value_point = next(
            (pt for pt in series_map.get("Non-value", []) if pt.window_days == value_window),
            None,
        )
        if value_point or non_value_point:
            value_pair = {
                "window_days": value_window,
                "value_pct": value_point.retention_pct if value_point else None,
                "non_value_pct": non_value_point.retention_pct if non_value_point else None,
            }

    return {
        "segment": base_segment,
        "eligible_users": base_points[0].eligible_users,
        "metrics": metrics,
        "value_pair": value_pair,
    }
