"""Macro correlation helpers for STX/BTC analysis."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable, Sequence

import pandas as pd

from . import macro_data, prices

EXCLUDED_COLUMNS: set[str] = {"date", "stx_usd", "btc_usd"}
DEFAULT_MAX_LAG_DAYS = 14

INDICATOR_LABELS: dict[str, str] = {
    "sp500_close": "S&P 500 Close",
    "sp500_pct_change": "S&P 500 Δ%",
    "unemployment_rate": "US Unemployment Rate",
    "fed_funds_rate": "Fed Funds Rate",
    "treasury_10y": "10Y Treasury Yield",
    "vix_close": "VIX Index",
    "usdt_supply": "USDT Supply",
    "usdt_daily_change": "USDT Daily Δ",
    "usdc_supply": "USDC Supply",
    "usdc_daily_change": "USDC Daily Δ",
    "dxy_close": "US Dollar Index (DXY)",
    "gold_close": "Gold Futures",
}


def _compute_corr(
    target: pd.Series,
    feature: pd.Series,
    *,
    method: str = "pearson",
) -> float:
    if method == "spearman":
        return target.rank(method="average").corr(
            feature.rank(method="average"), method="pearson"
        )
    return target.corr(feature, method=method)


def build_macro_correlation_panel(
    start_date: str,
    end_date: str,
    *,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Return merged STX price ratios and macro indicators aligned on date."""
    macro_panel = macro_data.load_macro_panel(
        start_date, end_date, force_refresh=force_refresh
    )
    if macro_panel.empty:
        macro_panel = pd.DataFrame(columns=["date"])
    macro_panel = macro_panel.copy()
    macro_panel["date"] = pd.to_datetime(macro_panel["date"])

    start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=UTC)
    price_panel = prices.load_price_panel(
        start_dt,
        end_dt,
        frequency="1d",
        force_refresh=force_refresh,
    )
    price_panel["date"] = price_panel["ts"].dt.date
    price_cols = price_panel[["date", "stx_usd", "btc_usd", "stx_btc"]].copy()
    price_cols["date"] = pd.to_datetime(price_cols["date"])

    merged = price_cols.merge(macro_panel, on="date", how="outer")
    merged["date"] = pd.to_datetime(merged["date"])
    return merged.sort_values("date").reset_index(drop=True)


def _indicator_columns(panel: pd.DataFrame, columns: Sequence[str] | None = None) -> list[str]:
    if columns:
        return [col for col in columns if col in panel.columns]
    return [
        col
        for col in panel.columns
        if col not in EXCLUDED_COLUMNS and col != "stx_btc" and panel[col].notna().any()
    ]


def compute_indicator_correlations(
    panel: pd.DataFrame,
    *,
    target_col: str = "stx_btc",
    columns: Sequence[str] | None = None,
    method: str = "pearson",
) -> pd.DataFrame:
    """Return correlation coefficients between STX/BTC and each indicator."""
    if panel.empty or target_col not in panel:
        return pd.DataFrame(columns=["indicator", "correlation"])
    indicators = _indicator_columns(panel, columns)
    results: list[dict[str, object]] = []
    for col in indicators:
        subset = panel[[target_col, col]].dropna()
        if subset.empty or subset[col].nunique() < 3:
            continue
        corr = _compute_corr(subset[target_col], subset[col], method=method)
        results.append({"indicator": col, "correlation": corr})
    return pd.DataFrame(results)


def compute_lagged_correlations(
    panel: pd.DataFrame,
    *,
    feature: str,
    target_col: str = "stx_btc",
    max_lag_days: int = DEFAULT_MAX_LAG_DAYS,
    method: str = "pearson",
) -> pd.DataFrame:
    """Return correlation values across +/- lag days for a given indicator."""
    if panel.empty or feature not in panel or target_col not in panel:
        return pd.DataFrame(columns=["lag_days", "correlation"])
    base = panel[[target_col, feature]].dropna()
    if base.empty:
        return pd.DataFrame(columns=["lag_days", "correlation"])

    results: list[dict[str, float]] = []
    series_target = base[target_col]
    series_feature = base[feature]
    for lag in range(-max_lag_days, max_lag_days + 1):
        shifted = series_feature.shift(lag)
        aligned = (
            pd.concat([series_target, shifted], axis=1)
            .dropna()
            .rename(columns={feature: "feature"})
        )
        if aligned.empty or aligned["feature"].nunique() < 3:
            continue
        corr = _compute_corr(aligned[target_col], aligned["feature"], method=method)
        if pd.isna(corr):
            continue
        results.append({"lag_days": lag, "correlation": corr})
    return pd.DataFrame(results)


def summarize_indicator_correlations(
    panel: pd.DataFrame,
    *,
    target_col: str = "stx_btc",
    columns: Sequence[str] | None = None,
    max_lag_days: int = DEFAULT_MAX_LAG_DAYS,
) -> pd.DataFrame:
    """Summarize Pearson/Spearman + best lag correlation for each indicator."""
    indicator_cols = _indicator_columns(panel, columns)
    rows: list[dict[str, object]] = []
    for col in indicator_cols:
        subset = panel[[target_col, col]].dropna()
        if len(subset) < 10 or subset[col].nunique() < 3:
            continue
        pearson = _compute_corr(subset[target_col], subset[col], method="pearson")
        spearman = _compute_corr(subset[target_col], subset[col], method="spearman")

        lag_df = compute_lagged_correlations(
            panel,
            feature=col,
            target_col=target_col,
            max_lag_days=max_lag_days,
        )
        if lag_df.empty:
            best_lag = 0
            best_corr = pearson
        else:
            lag_df["abs_corr"] = lag_df["correlation"].abs()
            lag_df = lag_df.sort_values(
                ["abs_corr", "lag_days"], ascending=[False, True]
            )
            best_row = lag_df.iloc[0]
            best_lag = int(best_row["lag_days"])
            best_corr = float(best_row["correlation"])

        latest_value = panel[col].dropna().iloc[-1] if panel[col].notna().any() else None
        rows.append(
            {
                "indicator": col,
                "label": INDICATOR_LABELS.get(col, col),
                "pearson": pearson,
                "spearman": spearman,
                "best_lag_days": best_lag,
                "best_lag_correlation": best_corr,
                "latest_value": latest_value,
                "abs_pearson": abs(pearson) if pearson is not None else 0.0,
            }
        )

    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary
    return (
        summary.sort_values("abs_pearson", ascending=False)
        .drop(columns=["abs_pearson"])
        .reset_index(drop=True)
    )
