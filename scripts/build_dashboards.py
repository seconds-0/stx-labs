#!/usr/bin/env python3
"""Generate standalone HTML dashboards for wallet growth and macro analysis."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from string import Template
from typing import Iterable, Sequence

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import macro_analysis
from src import macro_data
from src import pox_yields
from src import prices
from src import wallet_metrics
from src import wallet_value


LOGGER = logging.getLogger(__name__)
SUPPORTED_ROI_WINDOWS: tuple[int, ...] = (30, 60, 90)


NAV_LINKS: list[tuple[str, str, str]] = [
    ("wallet", "Wallet", "/wallet/index.html"),
    ("value", "Value", "/value/index.html"),
    ("macro", "Macro", "/macro/index.html"),
    ("coinbase", "Coinbase", "/coinbase/index.html"),
    ("coinbase_replacement", "Coinbase Replacement", "/coinbase_replacement/index.html"),
    ("scenarios", "Scenarios", "/scenarios/index.html"),
]

BODY_RE = re.compile(r"<body[^>]*>(?P<body>.*)</body>", re.S | re.I)
STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.S | re.I)

COINBASE_CALC_STYLE = """
<style>
.coinbase-wrapper {
  max-width: 960px;
  margin: 0 auto;
  background: #161b2e;
  border: 1px solid #2f354a;
  border-radius: 12px;
  padding: 2rem;
  color: #f5f6fa;
}
.coinbase-wrapper h1,
.coinbase-wrapper h2,
.coinbase-wrapper h3 {
  color: #70e1ff;
}
.coinbase-wrapper .subtitle {
  color: #b5bfd9;
  margin-bottom: 1.5rem;
}
.coinbase-wrapper .baseline {
  background: #101522;
  border-left: 4px solid #70e1ff;
  padding: 1rem;
  margin-bottom: 1.5rem;
}
.coinbase-wrapper .baseline-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 1rem;
  margin-top: 1rem;
}
.coinbase-wrapper .baseline-stat {
  color: #b5bfd9;
  font-size: 0.9rem;
}
.coinbase-wrapper .baseline-stat strong {
  font-size: 1.25rem;
  color: #f5f6fa;
}
.coinbase-wrapper .presets {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}
.coinbase-wrapper .preset-btn {
  flex: 1;
  min-width: 140px;
  padding: 0.9rem 1.2rem;
  border-radius: 8px;
  border: 1px solid #2f354a;
  background: linear-gradient(135deg, #1f2840, #101522);
  color: #f5f6fa;
  cursor: pointer;
  transition: border-color 0.2s, transform 0.2s;
}
.coinbase-wrapper .preset-btn:hover {
  border-color: #70e1ff;
  transform: translateY(-1px);
}
.coinbase-wrapper .preset-btn .target {
  font-size: 1.2rem;
  font-weight: 600;
}
.coinbase-wrapper .preset-btn .desc {
  color: #b5bfd9;
  font-size: 0.8rem;
}
.coinbase-wrapper .slider-group {
  margin-bottom: 1.75rem;
}
.coinbase-wrapper .slider-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
  font-size: 0.95rem;
  color: #b5bfd9;
}
.coinbase-wrapper .slider-value {
  font-size: 1.35rem;
  font-weight: 600;
  color: #70e1ff;
  border: 1px solid #2f354a;
  border-radius: 6px;
  padding: 0.2rem 0.6rem;
  background: #101522;
}
.coinbase-wrapper input[type="range"] {
  width: 100%;
  height: 6px;
  border-radius: 3px;
  background: #2f354a;
}
.coinbase-wrapper input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #70e1ff;
  border: 2px solid #101522;
}
.coinbase-wrapper .results {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1rem;
  margin-bottom: 1.5rem;
}
.coinbase-wrapper .result-card {
  background: #101522;
  border: 1px solid #2f354a;
  border-radius: 10px;
  padding: 1rem;
  text-align: center;
}
.coinbase-wrapper .result-value {
  font-size: 2rem;
  font-weight: 600;
  color: #70e1ff;
}
.coinbase-wrapper .result-label {
  color: #b5bfd9;
  font-size: 0.9rem;
  margin-top: 0.4rem;
}
.coinbase-wrapper .efficiency {
  color: #f5f6fa;
  font-size: 0.95rem;
  margin-bottom: 1rem;
}
.coinbase-wrapper .efficiency strong {
  color: #70e1ff;
}
.coinbase-wrapper .notes {
  color: #b5bfd9;
  font-size: 0.9rem;
  line-height: 1.5;
}
.coinbase-wrapper .notes li {
  margin-left: 1.2rem;
  margin-bottom: 0.4rem;
}
@media (max-width: 600px) {
  .coinbase-wrapper {
    padding: 1.25rem;
  }
  .coinbase-wrapper .slider-label {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.3rem;
  }
}
</style>
"""

PLOTLY_EMBED_STYLE = """
<style>
.plotly-embed {
  background: #161b2e;
  border: 1px solid #2f354a;
  border-radius: 12px;
  padding: 1.5rem;
  overflow: auto;
}
</style>
"""


def _write_html(
    output_path: Path,
    title: str,
    sections: Iterable[str],
    *,
    active_nav: str | None = None,
    last_updated: datetime | None = None,
) -> None:
    """Wrap the provided HTML snippets in a basic document and write to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = (last_updated or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M %Z")
    html = "\n".join(
        [
            "<!DOCTYPE html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8" />',
            '  <meta name="viewport" content="width=device-width, initial-scale=1" />',
            f"  <title>{title}</title>",
            '  <style type="text/css">',
            "    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; margin: 0 auto; padding: 2rem; max-width: 1100px; background: #101522; color: #f5f6fa; }",
            "    h1, h2 { color: #70e1ff; }",
            "    a { color: #70e1ff; }",
            "    .topnav { position: sticky; top: 0; z-index: 10; background: #0f1420; border-bottom: 1px solid #2f354a; margin: -2rem -2rem 1rem -2rem; padding: 0.75rem 2rem; }",
            "    .topnav a { margin-right: 1rem; color: #b5bfd9; text-decoration: none; font-size: 0.95rem; }",
            "    .topnav a:hover, .topnav a.active { color: #70e1ff; text-decoration: underline; }",
            "    .last-updated { font-size: 0.85rem; color: #7681a1; margin-bottom: 1.5rem; }",
            "    table { border-collapse: collapse; width: 100%; margin: 1.5rem 0; }",
            "    th, td { border: 1px solid #2f354a; padding: 0.5rem 0.75rem; text-align: left; }",
            "    th { background: #1f2840; }",
            "    tr:nth-child(even) { background: #161b2e; }",
            "    .section { margin-bottom: 3rem; }",
            "    .note { font-size: 0.9rem; color: #b5bfd9; margin-top: -1rem; margin-bottom: 1.5rem; }",
            "    .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; }",
            "    .kpi-card { background: #161b2e; padding: 1rem; border-radius: 8px; border: 1px solid #2f354a; }",
            "    .kpi-label { text-transform: uppercase; font-size: 0.75rem; color: #7f8bb3; letter-spacing: 0.05em; }",
            "    .kpi-value { font-size: 1.5rem; margin-top: 0.25rem; color: #f5f6fa; }",
            "    .kpi-subtext { font-size: 0.85rem; color: #7f8bb3; margin-top: 0.25rem; }",
            "  </style>",
            "</head>",
            "<body>",
            "<div class='topnav'>",
            "  <strong style='margin-right: 1rem; color:#f5f6fa;'>Stacks Analytics</strong>",
        ]
        + [
            f"  <a href='{href}'{' class=\"active\"' if active_nav == key else ''}>{label}</a>"
            for key, label, href in NAV_LINKS
        ]
        + [
            "</div>",
            f"<div class='last-updated'>Last updated {stamp}</div>",
            *sections,
            "</body>",
            "</html>",
        ]
    )
    output_path.write_text(html, encoding="utf-8")
    print(f"Wrote {output_path}")


def _extract_body_html(document: str) -> str:
    match = BODY_RE.search(document)
    content = match.group("body") if match else document
    return content.strip()


def _write_static_page(
    *,
    source_html: str,
    output_path: Path,
    title: str,
    active_nav: str,
    custom_style: str | None = None,
    wrapper_class: str | None = None,
    strip_existing_styles: bool = True,
) -> None:
    content = _extract_body_html(source_html)
    if strip_existing_styles:
        content = STYLE_RE.sub("", content)
    if wrapper_class:
        content = f"<div class='{wrapper_class}'>{content}</div>"
    sections: list[str] = []
    if custom_style:
        sections.append(custom_style)
    sections.extend(
        [
            "<div class='section'>",
            content,
            "</div>",
        ]
    )
    _write_html(
        output_path,
        title,
        sections,
        active_nav=active_nav,
        last_updated=datetime.now(UTC),
    )


def build_wallet_dashboard(
    *,
    output_path: Path,
    max_days: int,
    windows: Sequence[int],
    force_refresh: bool,
    wallet_db_path: Path | None = None,
    skip_history_sync: bool = False,
    last_updated: datetime | None = None,
) -> None:
    """Generate the wallet growth dashboard HTML using cached Hiro transactions."""
    generated_at = last_updated or datetime.now(UTC)
    if not skip_history_sync:
        wallet_metrics.ensure_transaction_history(
            max_days=max_days,
            force_refresh=force_refresh,
        )

    activity = wallet_metrics.load_recent_wallet_activity(
        max_days=max_days,
        db_path=wallet_db_path,
    )
    first_seen = wallet_metrics.update_first_seen_cache(activity)
    retention = wallet_metrics.compute_retention(
        activity,
        first_seen,
        windows,
    )
    fee_per_wallet = wallet_metrics.compute_fee_per_wallet(
        activity,
        first_seen,
        windows,
    )
    wallet_today = pd.Timestamp.now(tz="UTC").floor("D")
    window_origin = wallet_today - pd.Timedelta(days=max_days)
    new_wallets = wallet_metrics.compute_new_wallets(
        first_seen,
        window_origin,
    )
    active_wallets = wallet_metrics.compute_active_wallets(
        activity,
        window_origin,
    )

    summary_rows: list[dict[str, object]] = []
    for window in windows:
        window_start = wallet_today - pd.Timedelta(days=window - 1)
        if not new_wallets.empty:
            new_total = int(
                new_wallets.loc[
                    new_wallets["activation_date"] >= window_start, "new_wallets"
                ].sum()
            )
        else:
            new_total = 0

        if not activity.empty:
            active_total = int(
                activity.loc[
                    activity["block_time"] >= window_start, "address"
                ].nunique()
            )
        else:
            active_total = 0

        retention_slice = retention[
            retention["window_days"] == window
        ].sort_values("activation_date")
        retention_latest = retention_slice.iloc[-1] if not retention_slice.empty else None

        fee_slice = fee_per_wallet[
            fee_per_wallet["window_days"] == window
        ].sort_values("activation_date")
        fee_latest = fee_slice.iloc[-1] if not fee_slice.empty else None

        summary_rows.append(
            {
                "window_days": int(window),
                "new_wallets_trailing": new_total,
                "active_wallets_trailing": active_total,
                "retention_cohort_date": (
                    retention_latest.activation_date.strftime("%Y-%m-%d")
                    if retention_latest is not None
                    else "—"
                ),
                "retention_rate_pct": (
                    float(retention_latest.retention_rate) * 100
                    if retention_latest is not None and retention_latest.retention_rate is not None
                    else None
                ),
                "avg_fee_stx": (
                    float(fee_latest.avg_fee_stx)
                    if fee_latest is not None and fee_latest.avg_fee_stx is not None
                    else None
                ),
                "fee_cohort_date": (
                    fee_latest.activation_date.strftime("%Y-%m-%d")
                    if fee_latest is not None
                    else "—"
                ),
                "wallets_observed": (
                    int(fee_latest.wallets_observed)
                    if fee_latest is not None and fee_latest.wallets_observed is not None
                    else 0
                ),
            }
        )

    summary_df = pd.DataFrame(summary_rows).sort_values("window_days")
    summary_table_html = summary_df.fillna("—").to_html(index=False, classes="summary-table")

    # Add explanatory text for table metrics
    metric_definitions = """
<div style="background: #1f2840; padding: 1rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.9rem; line-height: 1.5;">
  <strong>Metric Definitions:</strong><br/>
  • <strong>new_wallets_trailing:</strong> Count of unique addresses that made their first transaction within the trailing window<br/>
  • <strong>active_wallets_trailing:</strong> Count of unique addresses with any transaction activity in the trailing window<br/>
  • <strong>retention_cohort_date:</strong> Most recent cohort date used for retention analysis<br/>
  • <strong>retention_rate_pct:</strong> Percentage of wallets from the cohort still active after the window period<br/>
  • <strong>avg_fee_stx:</strong> Average transaction fees paid per wallet (in STX) for the cohort<br/>
  • <strong>wallets_observed:</strong> Number of wallets with fee data available in the window
</div>"""

    daily_chart = pd.DataFrame()
    if not active_wallets.empty:
        daily_chart = active_wallets.rename(columns={"activity_date": "date"})
    if not new_wallets.empty:
        daily_new = new_wallets.rename(columns={"activation_date": "date"})
        daily_chart = (
            daily_chart.merge(daily_new, on="date", how="outer")
            if not daily_chart.empty
            else daily_new
        )
    if not daily_chart.empty:
        daily_chart = daily_chart.sort_values("date").fillna(0)
        daily_chart["active_ma_7"] = (
            daily_chart.get("active_wallets", pd.Series(dtype=float))
            .rolling(window=7, min_periods=1)
            .mean()
        )
        daily_chart["date_str"] = daily_chart["date"].dt.strftime("%Y-%m-%d")

    trend_html = ""
    if not daily_chart.empty:
        fig_trend = go.Figure()
        if "new_wallets" in daily_chart:
            fig_trend.add_bar(
                x=daily_chart["date_str"],
                y=daily_chart["new_wallets"],
                name="New Wallets",
                marker_color="#6c8cff",
                yaxis="y2",
                hovertemplate="<b>Date:</b> %{x}<br><b>New Wallets:</b> %{y}<br><i>Addresses making their first transaction on this date</i><extra></extra>",
            )
        if "active_wallets" in daily_chart:
            fig_trend.add_scatter(
                x=daily_chart["date_str"],
                y=daily_chart["active_wallets"],
                name="Active Wallets",
                mode="lines+markers",
                line=dict(color="#ff6b6b", width=2),
                hovertemplate="<b>Date:</b> %{x}<br><b>Active Wallets:</b> %{y}<br><i>Unique addresses with any transaction activity</i><extra></extra>",
            )
        if "active_ma_7" in daily_chart:
            fig_trend.add_scatter(
                x=daily_chart["date_str"],
                y=daily_chart["active_ma_7"],
                name="Active Wallets (7d MA)",
                mode="lines",
                line=dict(color="#1dd3b8", width=2, dash="dot"),
                hovertemplate="<b>Date:</b> %{x}<br><b>7-day MA:</b> %{y:.1f}<br><i>7-day moving average of active wallets for trend smoothing</i><extra></extra>",
            )
        fig_trend.update_layout(
            title="Daily New vs Active Wallets",
            xaxis_title="Date",
            yaxis=dict(title="Active Wallets"),
            yaxis2=dict(
                title="New Wallets",
                overlaying="y",
                side="right",
                showgrid=False,
            ),
            template="plotly_dark",
            legend=dict(orientation="h", y=-0.2),
            bargap=0.2,
            height=500,
        )
        trend_html = pio.to_html(fig_trend, include_plotlyjs="cdn", full_html=False)

    retention_html = ""
    if not retention.empty:
        retention_matrix = (
            retention.pivot(
                index="activation_date",
                columns="window_days",
                values="retention_rate",
            )
            .sort_index()
            * 100
        )
        if not retention_matrix.empty:
            fig_retention = go.Figure(
                data=go.Heatmap(
                    z=retention_matrix.values,
                    x=[f"{col}-day" for col in retention_matrix.columns],
                    y=[ts.strftime("%Y-%m-%d") for ts in retention_matrix.index],
                    colorscale="Blues",
                    colorbar=dict(title="Retention %"),
                    zmin=0,
                    zmax=100,
                    hovertemplate="<b>Cohort Date:</b> %{y}<br><b>Window:</b> %{x}<br><b>Retention:</b> %{z:.1f}%<br><i>% of wallets from this cohort still active after window period</i><extra></extra>",
                )
            )
            fig_retention.update_layout(
                title="Retention by Activation Cohort",
                xaxis_title="Retention Window",
                yaxis_title="Activation Date",
                template="plotly_dark",
                height=400 + 12 * len(retention_matrix),
            )
            retention_html = pio.to_html(fig_retention, include_plotlyjs="cdn", full_html=False)

    fee_html = ""
    if not fee_per_wallet.empty:
        fee_chart = fee_per_wallet.copy()
        fee_chart["activation_date"] = fee_chart["activation_date"].dt.strftime("%Y-%m-%d")
        fig_fee = px.bar(
            fee_chart,
            x="activation_date",
            y="avg_fee_stx",
            color="window_days",
            barmode="group",
            labels={
                "activation_date": "Activation Date",
                "avg_fee_stx": "Average Fees (STX)",
                "window_days": "Window (days)",
            },
            title="Average Fees per Wallet by Cohort",
            hover_data={"median_fee_stx": True, "wallets_observed": True},
            template="plotly_dark",
        )
        fig_fee.update_traces(
            hovertemplate="<b>Cohort:</b> %{x}<br><b>Window:</b> %{fullData.name} days<br>"
            + "<b>Avg Fee:</b> %{y:.4f} STX<br><b>Median Fee:</b> %{customdata[0]:.4f} STX<br>"
            + "<b>Wallets:</b> %{customdata[1]}<br><i>Average transaction fees paid per wallet in cohort</i><extra></extra>"
        )
        fig_fee.update_layout(height=520)
        fee_html = pio.to_html(fig_fee, include_plotlyjs="cdn", full_html=False)

    thr = wallet_value.ClassificationThresholds()
    sections = [
        "<div class='section'>",
        "<h1>Stacks Wallet Growth Dashboard</h1>",
        "<p class='note'>Derived from Hiro canonical transactions, cached locally. Updated "
        f"{generated_at.strftime('%Y-%m-%d %H:%M UTC')}.</p>",
        (
            "<div class='note'><strong>Definitions:</strong> "
            "Active wallets (this page): unique addresses with any transaction activity in the selected trailing window. "
            f"Classification (value module): Funded ≥ {thr.funded_stx_min:g} STX balance; "
            f"Active ≥ {thr.active_min_tx_30d} tx in first 30 days; "
            f"Value WALTV-30 ≥ {thr.value_min_fee_stx_30d:g} STX fees.</div>"
        ),
        "<h2>Window Summary</h2>",
        metric_definitions,
        summary_table_html,
        "</div>",
    ]
    if trend_html:
        sections.extend(
            ["<div class='section'>", "<h2>Daily Activity</h2>", trend_html, "</div>"]
        )
    if retention_html:
        sections.extend(
            ["<div class='section'>", "<h2>Cohort Retention</h2>", retention_html, "</div>"]
        )
    if fee_html:
        sections.extend(
            ["<div class='section'>", "<h2>Fee Contribution</h2>", fee_html, "</div>"]
        )
    if not trend_html and not retention_html and not fee_html:
        sections.append("<p>No wallet activity available for the requested windows.</p>")

    _write_html(
        output_path,
        "Stacks Wallet Growth Dashboard",
        sections,
        active_nav="wallet",
        last_updated=generated_at,
    )


def build_macro_dashboard(
    *,
    output_path: Path,
    history_days: int,
    force_refresh: bool,
) -> None:
    """Generate an HTML dashboard covering macro indicators."""
    generated_at = datetime.now(UTC)
    end_date = datetime.now(tz=UTC).date()
    start_date = end_date - timedelta(days=history_days)
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()

    sp500 = macro_data.fetch_sp500_data(start_str, end_str, force_refresh=force_refresh)
    unemployment = macro_data.fetch_unemployment_data(
        start_str, end_str, force_refresh=force_refresh
    )
    rates = macro_data.fetch_interest_rates(start_str, end_str, force_refresh=force_refresh)
    volatility = macro_data.fetch_volatility_data(
        start_str, end_str, force_refresh=force_refresh
    )

    price_panel = pd.DataFrame(columns=["date", "px"])
    price_fetch_errors: list[str] = []
    try:
        fresh = prices.fetch_price_series(
            "STX-USD",
            datetime.combine(start_date, datetime.min.time(), tzinfo=UTC),
            datetime.combine(end_date, datetime.min.time(), tzinfo=UTC),
            frequency="1d",
            force_refresh=force_refresh,
        )
        fresh["date"] = fresh["ts"].dt.date
        price_panel = fresh
    except Exception as exc:  # pragma: no cover - capture runtime issues
        price_fetch_errors.append(str(exc))

    correlation_panel = macro_analysis.build_macro_correlation_panel(
        start_str, end_str, force_refresh=force_refresh
    )
    correlation_summary = macro_analysis.summarize_indicator_correlations(
        correlation_panel, max_lag_days=14
    )

    last_rows = []
    if not sp500.empty:
        last_rows.append(
            {
                "Metric": "S&P 500 Close",
                "Latest": f"{sp500.iloc[-1]['sp500_close']:.0f}",
                "Latest Δ%": (
                    f"{sp500.iloc[-1]['sp500_pct_change']:.2f}%"
                    if pd.notna(sp500.iloc[-1]["sp500_pct_change"])
                    else "—"
                ),
            }
        )
    if not unemployment.empty:
        last_rows.append(
            {
                "Metric": "US Unemployment Rate",
                "Latest": f"{unemployment.iloc[-1]['unemployment_rate']:.2f}%",
                "Latest Δ%": "—",
            }
        )
    if not rates.empty:
        last_rows.append(
            {
                "Metric": "Fed Funds Rate / 10Y Treasury",
                "Latest": (
                    f"{rates.iloc[-1]['fed_funds_rate']:.2f}% / {rates.iloc[-1]['treasury_10y']:.2f}%"
                ),
                "Latest Δ%": "—",
            }
        )
    if not volatility.empty:
        last_rows.append(
            {
                "Metric": "VIX Close",
                "Latest": f"{volatility.iloc[-1]['vix_close']:.2f}",
                "Latest Δ%": "—",
            }
        )
    if not price_panel.empty:
        last_rows.append(
            {
                "Metric": "STX/USD",
                "Latest": f"${price_panel.iloc[-1]['px']:.4f}",
                "Latest Δ%": "—",
            }
        )
    summary_table = (
        pd.DataFrame(last_rows).to_html(index=False, classes="summary-table")
        if last_rows
        else "<p>No macro data available.</p>"
    )

    macro_sections = [
        "<div class='section'>",
        "<h1>Stacks Macro Dashboard</h1>",
        "<p class='note'>Daily macro indicators from FRED, Yahoo Finance, and CoinGecko. "
        f"History window: {start_str} → {end_str}. Generated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}.</p>",
    ]
    if price_fetch_errors:
        macro_sections.append(
            "<p class='note'>Price data note: "
            + " / ".join(price_fetch_errors)
            + "</p>"
        )
    macro_sections.extend(["<h2>Latest Snapshot</h2>", summary_table, "</div>"])

    if not correlation_summary.empty:
        display_cols = correlation_summary[
            [
                "label",
                "pearson",
                "spearman",
                "best_lag_days",
                "best_lag_correlation",
                "latest_value",
            ]
        ].rename(
            columns={
                "label": "Indicator",
                "pearson": "Pearson",
                "spearman": "Spearman",
                "best_lag_days": "Best Lag (days)",
                "best_lag_correlation": "Lag Corr",
                "latest_value": "Latest Value",
            }
        )
        for col in ["Pearson", "Spearman", "Lag Corr"]:
            display_cols[col] = display_cols[col].map(lambda x: f"{x:.3f}")
        display_cols["Latest Value"] = display_cols["Latest Value"].map(
            lambda x: f"{x:.3f}" if isinstance(x, (int, float)) else "—"
        )
        corr_table_html = display_cols.to_html(index=False, classes="summary-table")

        heatmap_fig = go.Figure(
            data=go.Heatmap(
                z=[
                    correlation_summary["pearson"].tolist(),
                    correlation_summary["spearman"].tolist(),
                ],
                x=correlation_summary["label"].tolist(),
                y=["Pearson", "Spearman"],
                colorscale="RdBu",
                zmin=-1,
                zmax=1,
                colorbar=dict(title="Correlation"),
                text=[
                    [f"{val:.2f}" for val in correlation_summary["pearson"]],
                    [f"{val:.2f}" for val in correlation_summary["spearman"]],
                ],
                texttemplate="%{text}",
            )
        )
        heatmap_fig.update_layout(
            title="STX/BTC vs Indicator Correlations",
            template="plotly_dark",
            height=360,
        )

        macro_sections.extend(
            [
                "<div class='section'>",
                "<h2>STX/BTC Correlation Summary</h2>",
                "<p class='note'>Correlations computed on overlapping dates; positive lag means the indicator leads STX/BTC by that many days.</p>",
                corr_table_html,
                pio.to_html(heatmap_fig, include_plotlyjs="cdn", full_html=False),
            ]
        )

        # Highlight lead/lag profile for strongest indicator
        top_indicator_row = correlation_summary.iloc[0]
        lag_df = macro_analysis.compute_lagged_correlations(
            correlation_panel,
            feature=top_indicator_row["indicator"],
            max_lag_days=14,
        )
        if not lag_df.empty:
            lag_chart = px.line(
                lag_df,
                x="lag_days",
                y="correlation",
                title=f"Lead / Lag Correlation: {top_indicator_row['label']}",
                labels={"lag_days": "Lag (days)", "correlation": "Correlation"},
                template="plotly_dark",
            )
            lag_chart.add_hline(y=0, line_dash="dot", line_color="#888")
            macro_sections.append(
                pio.to_html(lag_chart, include_plotlyjs="cdn", full_html=False)
            )
        macro_sections.append("</div>")

    if not sp500.empty:
        sp500_plot = px.line(
            sp500,
            x="date",
            y="sp500_close",
            title="S&P 500 Close",
            template="plotly_dark",
        )
        sp500_plot.update_traces(
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br><b>S&P 500:</b> %{y:.2f}<br><i>Market benchmark tracking 500 largest U.S. companies - indicator of overall stock market performance and investor sentiment</i><extra></extra>"
        )
        sp500_plot.update_layout(height=500)
        macro_sections.extend(
            ["<div class='section'>", pio.to_html(sp500_plot, include_plotlyjs="cdn", full_html=False), "</div>"]
        )

    if not rates.empty:
        rates_plot = px.line(
            rates,
            x="date",
            y=["fed_funds_rate", "treasury_10y"],
            labels={"value": "Rate (%)", "date": "Date"},
            title="Policy & Treasury Rates",
            template="plotly_dark",
        )
        # Add custom tooltips for each trace
        for i, trace in enumerate(rates_plot.data):
            if "fed_funds" in trace.name.lower():
                trace.hovertemplate = "<b>Date:</b> %{x|%Y-%m-%d}<br><b>Fed Funds Rate:</b> %{y:.2f}%<br><i>Federal Reserve's target interest rate - affects borrowing costs and investment returns across the economy</i><extra></extra>"
            elif "treasury" in trace.name.lower():
                trace.hovertemplate = "<b>Date:</b> %{x|%Y-%m-%d}<br><b>10Y Treasury:</b> %{y:.2f}%<br><i>Yield on 10-year U.S. Treasury bonds - benchmark for long-term interest rates and economic expectations</i><extra></extra>"
        rates_plot.update_layout(height=500)
        macro_sections.extend(
            ["<div class='section'>", pio.to_html(rates_plot, include_plotlyjs="cdn", full_html=False), "</div>"]
        )

    if not unemployment.empty:
        unemployment_plot = px.area(
            unemployment,
            x="date",
            y="unemployment_rate",
            title="US Unemployment Rate",
            labels={"unemployment_rate": "Rate (%)"},
            template="plotly_dark",
        )
        unemployment_plot.update_traces(
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br><b>Unemployment Rate:</b> %{y:.2f}%<br><i>Percentage of labor force actively seeking work - key indicator of economic health and consumer spending power</i><extra></extra>"
        )
        unemployment_plot.update_layout(height=450)
        macro_sections.extend(
            [
                "<div class='section'>",
                pio.to_html(unemployment_plot, include_plotlyjs="cdn", full_html=False),
                "</div>",
            ]
        )

    if not volatility.empty:
        vix_plot = px.line(
            volatility,
            x="date",
            y="vix_close",
            title="CBOE Volatility Index (VIX)",
            template="plotly_dark",
        )
        vix_plot.update_traces(
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br><b>VIX:</b> %{y:.2f}<br><i>Market volatility index - measures expected 30-day S&P 500 volatility, often called the 'fear gauge'</i><extra></extra>"
        )
        vix_plot.update_layout(height=450)
        macro_sections.extend(
            ["<div class='section'>", pio.to_html(vix_plot, include_plotlyjs="cdn", full_html=False), "</div>"]
        )

    if not price_panel.empty:
        stx_plot = px.line(
            price_panel,
            x="date",
            y="px",
            title="STX/USD Price (Daily)",
            labels={"px": "Price (USD)", "date": "Date"},
            template="plotly_dark",
        )
        stx_plot.update_traces(
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br><b>STX Price:</b> $%{y:.4f}<br><i>Stacks token price in U.S. dollars - reflects market demand and sentiment for the Stacks ecosystem</i><extra></extra>"
        )
        stx_plot.update_layout(height=450)
        macro_sections.extend(
            ["<div class='section'>", pio.to_html(stx_plot, include_plotlyjs="cdn", full_html=False), "</div>"]
        )

    _write_html(
        output_path,
        "Stacks Macro Dashboard",
        macro_sections,
        active_nav="macro",
        last_updated=generated_at,
    )


def copy_static_assets(public_dir: Path) -> None:
    """Copy and theme static HTML assets (coinbase calculator, scenarios) into public site."""
    public_dir.mkdir(parents=True, exist_ok=True)
    static_pages = [
        {
            "src": Path("out/coinbase_calculator.html"),
            "dest": public_dir / "coinbase" / "index.html",
            "title": "Coinbase Fee Calculator",
            "active_nav": "coinbase",
            "style": COINBASE_CALC_STYLE,
            "wrapper": "coinbase-wrapper",
        },
        {
            "src": Path("out/coinbase_replacement_roadmap.html"),
            "dest": public_dir / "coinbase_replacement" / "index.html",
            "title": "Coinbase Replacement Roadmap",
            "active_nav": "coinbase_replacement",
            "style": PLOTLY_EMBED_STYLE,
            "wrapper": "plotly-embed",
        },
        {
            "src": Path("out/scenario_dashboard.html"),
            "dest": public_dir / "scenarios" / "index.html",
            "title": "Scenario Sensitivity Dashboard",
            "active_nav": "scenarios",
            "style": PLOTLY_EMBED_STYLE,
            "wrapper": "plotly-embed",
        },
    ]
    for cfg in static_pages:
        src_path = cfg["src"]
        dest_path = cfg["dest"]
        if not src_path.exists():
            continue
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        raw_html = src_path.read_text(encoding="utf-8")
        _write_static_page(
            source_html=raw_html,
            output_path=dest_path,
            title=cfg["title"],
            active_nav=cfg["active_nav"],
            custom_style=cfg.get("style"),
            wrapper_class=cfg.get("wrapper"),
            strip_existing_styles=cfg.get("strip_styles", True),
        )
        print(f"Themed {src_path} -> {dest_path}")


def build_public_index(public_dir: Path) -> None:
    """Create a lightweight landing page linking to all dashboards."""
    public_dir.mkdir(parents=True, exist_ok=True)
    index_path = public_dir / "index.html"
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    nav_links = "\n".join(
        f'        <a data-key="{key}" data-href="{href}" href="{href}">{label}</a>'
        for key, label, href in NAV_LINKS
    )
    template = Template(
        """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Stacks Analytics</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; background: #101522; color: #f5f6fa; margin: 0; min-height: 100vh; display: flex; }
      .sidebar { width: 240px; background: #0f1420; border-right: 1px solid #2f354a; padding: 1.25rem; position: sticky; top: 0; height: 100vh; box-sizing: border-box; }
      .sidebar h2 { color: #70e1ff; margin-top: 0; font-size: 1.1rem; }
      .nav a { display: block; padding: 0.5rem 0.4rem; color: #b5bfd9; text-decoration: none; border-radius: 4px; }
      .nav a:hover, .nav a.active { color: #70e1ff; background: #1a2034; }
      .content { flex: 1; display: flex; flex-direction: column; }
      .topbar { padding: 1rem 1.5rem; border-bottom: 1px solid #2f354a; }
      .topbar p { margin: 0; color: #b5bfd9; }
      iframe { flex: 1; border: none; width: 100%; background: #0f1420; }
      footer { padding: 0.75rem 1.5rem; font-size: 0.85rem; color: #7681a1; border-top: 1px solid #2f354a; }
      .open-link { display: inline-flex; align-items: center; gap: 0.35rem; font-size: 0.85rem; color: #70e1ff; text-decoration: none; }
    </style>
  </head>
  <body>
    <aside class="sidebar">
      <h2>Stacks Analytics</h2>
      <nav class="nav">
$nav_links
      </nav>
    </aside>
    <div class="content">
      <div class="topbar">
        <p>Use the sidebar to switch dashboards or <a class="open-link" id="open-new" href="/wallet/index.html" target="_blank" rel="noreferrer">open current in new tab ↗</a></p>
      </div>
      <iframe id="dash-frame" src="/wallet/index.html" title="Stacks Analytics Dashboard"></iframe>
      <footer>Generated $stamp</footer>
    </div>
    <script>
      const links = Array.from(document.querySelectorAll('.nav a'));
      const frame = document.getElementById('dash-frame');
      const openLink = document.getElementById('open-new');
      function activate(key, href, push = true) {
        links.forEach((link) => link.classList.toggle('active', link.dataset.key === key));
        if (frame.getAttribute('src') !== href) {
          frame.setAttribute('src', href);
        }
        openLink.setAttribute('href', href);
        if (push) {
          history.replaceState(null, '', '#' + key);
        }
      }
      links.forEach((link) => {
        link.addEventListener('click', (event) => {
          event.preventDefault();
          activate(link.dataset.key, link.dataset.href);
        });
      });
      const initialKey = window.location.hash ? window.location.hash.slice(1) : 'wallet';
      const initialLink = links.find((link) => link.dataset.key === initialKey) || links[0];
      activate(initialLink.dataset.key, initialLink.dataset.href, false);
    </script>
  </body>
</html>
"""
    )
    index_path.write_text(template.substitute(stamp=stamp, nav_links=nav_links), encoding="utf-8")
    print(f"Wrote {index_path}")


def build_value_dashboard(
    *,
    output_path: Path,
    max_days: int,
    windows: Sequence[int],
    force_refresh: bool,
    wallet_db_path: Path | None = None,
    skip_history_sync: bool = False,
    cpa_target_stx: float = 5.0,
) -> None:
    """Generate CPI/CPA-style wallet value dashboard with PoX linkage."""
    generated_at = datetime.now(UTC)
    data = wallet_value.compute_value_pipeline(
        max_days=max_days,
        windows=windows,
        force_refresh=force_refresh,
        wallet_db_path=wallet_db_path,
        skip_history_sync=skip_history_sync,
    )
    windows_df = data["windows"]
    cls = data["classification"]
    activity_df = data["activity"]
    daily_activity = wallet_value.compute_network_daily(activity_df)
    kpis = wallet_value.summarize_value_kpis(
        daily_activity=daily_activity,
        windows_agg=windows_df,
        classification=cls,
        lookback_days=30,
    )
    cpa_panels: dict[int, pd.DataFrame] = {}
    for roi_window in SUPPORTED_ROI_WINDOWS:
        if roi_window in set(windows):
            cpa_panels[roi_window] = wallet_value.compute_cpa_panel(
                windows_df,
                window_days=roi_window,
                cpa_target_stx=cpa_target_stx,
                min_wallets=wallet_value.MIN_WALTV_COHORT,
            )
    window_stats: dict[int, dict[str, float | int]] = {}
    for win in SUPPORTED_ROI_WINDOWS:
        if win in set(windows):
            window_stats[win] = wallet_value.summarize_window_stats(
                windows_df, window_days=win
            )

    # Compute trailing (calendar-anchored) wallet value stats for comparison
    try:
        price_panel = wallet_value.load_price_panel_for_activity(
            activity_df, force_refresh=force_refresh
        )
    except Exception as exc:
        LOGGER.warning("Price panel unavailable for trailing stats: %s", exc)
        price_panel = pd.DataFrame(columns=["ts", "stx_btc"])

    trailing_df = wallet_value.compute_trailing_wallet_windows(
        activity_df, price_panel, windows=SUPPORTED_ROI_WINDOWS
    )
    trailing_stats: dict[int, dict[str, float | int]] = {}
    for win in SUPPORTED_ROI_WINDOWS:
        trailing_stats[win] = wallet_value.summarize_trailing_window_stats(
            trailing_df, window_days=win
        )

    try:
        pox_summary = pox_yields.get_cycle_yield_summary(
            last_n_cycles=8, force_refresh=force_refresh
        )
        cycles_df = pox_yields.fetch_pox_cycles_data(force_refresh=force_refresh)
        rewards_df = pox_yields.aggregate_rewards_by_cycle(force_refresh=force_refresh)
        cycle_apy_df = pox_yields.calculate_cycle_apy(cycles_df, rewards_df)
    except Exception as exc:
        LOGGER.warning("PoX data unavailable: %s", exc)
        pox_summary = {}
        cycle_apy_df = pd.DataFrame()

    recent_cycles = (
        cycle_apy_df.sort_values("cycle_number", ascending=False)
        .head(8)
        .sort_values("cycle_number")
        if not cycle_apy_df.empty
        else pd.DataFrame()
    )
    if not recent_cycles.empty:
        recent_cycles = recent_cycles.copy()
        recent_cycles["total_btc_btc"] = recent_cycles["total_btc_sats"] / 1e8

    sections: list[str] = []
    sections.append("<div class='section'>")
    sections.append("<h1>Stacks Wallet Value Dashboard</h1>")
    sections.append(
        "<p class='note'>Network Value (NV) computed as STX fees converted to BTC using "
        "historical STX/BTC prices nearest to each transaction timestamp. "
        "WALTV currently equals NV (no incentives/derived added yet). "
        f"Updated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}.</p>"
    )
    # Add classification definitions for clarity at the top of the page.
    thr = wallet_value.ClassificationThresholds()
    sections.append(
        "<div class='note'>"
        "<strong>Definitions:</strong> "
        f"Funded Wallet: current STX balance ≥ {thr.funded_stx_min:g} STX. "
        f"Active Wallet: ≥ {thr.active_min_tx_30d} tx in the first 30 days from activation. "
        f"Value Wallet: WALTV-30 ≥ {thr.value_min_fee_stx_30d:g} STX in fees."
        "</div>"
    )

    def _fmt(value: float | None, suffix: str = "") -> str:
        if value is None:
            return "—"
        if abs(value) >= 1:
            return f"{value:,.1f}{suffix}"
        return f"{value:.4f}{suffix}"

    sections.append("<div class='section'>")
    sections.append("<div class='kpi-grid'>")
    sections.append(
        f"<div class='kpi-card'><div class='kpi-label'>30d Network Value</div><div class='kpi-value'>{_fmt(kpis['total_nv_btc'], ' BTC')}</div><div class='kpi-subtext'>{_fmt(kpis['total_fee_stx'], ' STX fees')}</div></div>"
    )
    sections.append(
        f"<div class='kpi-card'><div class='kpi-label'>Avg WALTV-30</div><div class='kpi-value'>{_fmt(kpis['avg_waltv_stx'], ' STX')}</div><div class='kpi-subtext'>Median {_fmt(kpis['median_waltv_stx'], ' STX')}</div></div>"
    )
    # Trailing 30-day average across all wallets (calendar-anchored)
    ts30 = trailing_stats.get(30, {})
    if ts30 and ts30.get("wallets", 0) > 0:
        sections.append(
            f"<div class='kpi-card'><div class='kpi-label'>Avg Last-30</div><div class='kpi-value'>{_fmt(ts30.get('avg_last_stx', 0.0), ' STX')}</div><div class='kpi-subtext'>Median {_fmt(ts30.get('median_last_stx', 0.0), ' STX')}</div></div>"
        )
    sections.append(
        f"<div class='kpi-card'><div class='kpi-label'>Funded → Value</div><div class='kpi-value'>{_fmt(kpis['value_pct'], '%')}</div><div class='kpi-subtext'>Active {_fmt(kpis['active_pct'], '%')} | Funded {kpis['funded_wallets']}</div></div>"
    )
    sections.append(
        f"<div class='kpi-card'><div class='kpi-label'>Value Wallets (30d)</div><div class='kpi-value'>{kpis['value_wallets']}</div><div class='kpi-subtext'>Active {kpis['active_wallets']}</div></div>"
    )
    for extra_window in (60, 90):
        stats = window_stats.get(extra_window)
        if stats and stats["wallets"] > 0:
            sections.append(
                f"<div class='kpi-card'><div class='kpi-label'>Avg WALTV-{extra_window}</div>"
                f"<div class='kpi-value'>{_fmt(stats['avg_waltv_stx'], ' STX')}</div>"
                f"<div class='kpi-subtext'>Median {_fmt(stats['median_waltv_stx'], ' STX')}</div></div>"
            )
        # Add trailing counterpart
        tstats = trailing_stats.get(extra_window, {})
        if tstats and tstats.get("wallets", 0) > 0:
            sections.append(
                f"<div class='kpi-card'><div class='kpi-label'>Avg Last-{extra_window}</div>"
                f"<div class='kpi-value'>{_fmt(tstats.get('avg_last_stx', 0.0), ' STX')}</div>"
                f"<div class='kpi-subtext'>Median {_fmt(tstats.get('median_last_stx', 0.0), ' STX')}</div></div>"
            )
    if pox_summary.get("apy_btc_median") is not None:
        sections.append(
            f"<div class='kpi-card'><div class='kpi-label'>PoX APY (median)</div><div class='kpi-value'>{pox_summary['apy_btc_median']}%</div><div class='kpi-subtext'>Participation {pox_summary.get('participation_rate_mean', '—')}%</div></div>"
        )
    sections.append("</div>")
    sections.append("</div>")

    # Funnel summary
    summary_rows: list[dict[str, object]] = []
    if not cls.empty:
        cls_tmp = cls.copy()
        cls_tmp["activation_date"] = pd.to_datetime(cls_tmp["activation_date"], utc=True)
        today = pd.Timestamp.now(tz=UTC).floor("D")
        for w in windows:
            start_ts = today - pd.Timedelta(days=w - 1)
            cohort = cls_tmp[cls_tmp["activation_date"] >= start_ts]
            total = int(len(cohort))
            funded = int(cohort["funded"].sum()) if not cohort.empty else 0
            active = int(cohort["active_30d"].sum()) if not cohort.empty else 0
            value = int(cohort["value_30d"].sum()) if not cohort.empty else 0
            funded = min(funded, total)
            summary_rows.append(
                {
                    "Window": f"{w}d",
                    "Cohort Size": total,
                    "Funded": funded,
                    "Active (30d)": active,
                    "Value (30d)": value,
                    "Active/Funded %": (active / funded * 100) if funded else None,
                    "Value/Funded %": (value / funded * 100) if funded else None,
                }
            )
    summary_table = (
        pd.DataFrame(summary_rows).to_html(index=False) if summary_rows else "<p>No data.</p>"
    )
    sections.append("<div class='section'>")
    sections.append("<h2>Funnel Summary</h2>")
    sections.append(summary_table)
    sections.append("</div>")

    # Network trend
    if not daily_activity.empty:
        trend = daily_activity.sort_values("activity_date").copy()
        trend["nv_btc_roll30"] = trend["nv_btc_sum"].rolling(window=30, min_periods=7).sum()
        trend["fee_stx_roll30"] = trend["fee_stx_sum"].rolling(window=30, min_periods=7).sum()
        trend_fig = go.Figure()
        trend_fig.add_trace(
            go.Scatter(
                x=trend["activity_date"],
                y=trend["nv_btc_roll30"],
                mode="lines",
                name="30d NV (BTC)",
                line=dict(color="#70e1ff", width=3),
            )
        )
        trend_fig.add_trace(
            go.Scatter(
                x=trend["activity_date"],
                y=trend["fee_stx_roll30"],
                mode="lines",
                name="30d Fees (STX)",
                line=dict(color="#ffaf40", width=2, dash="dot"),
                yaxis="y2",
            )
        )
        trend_fig.update_layout(
            title="Network Value vs Fees (30d rolling)",
            xaxis_title="Date",
            yaxis_title="NV (BTC)",
            yaxis2=dict(
                title="Fees (STX)",
                overlaying="y",
                side="right",
                showgrid=False,
            ),
            template="plotly_dark",
            hovermode="x unified",
        )
        sections.extend(
            [
                "<div class='section'>",
                "<h2>Network Activity Trend</h2>",
                pio.to_html(trend_fig, include_plotlyjs="cdn", full_html=False),
                "</div>",
            ]
        )

    # CPA / ROI panels across windows
    for roi_window, panel in cpa_panels.items():
        if panel.empty:
            continue
        cpa_fig = px.line(
            panel,
            x="activation_date",
            y="payback_multiple",
            title=f"Payback Multiple vs Target ({roi_window}d)",
            labels={"activation_date": "Activation Date", "payback_multiple": "Avg WALTV / CPA Target"},
            template="plotly_dark",
        )
        cpa_fig.add_hline(
            y=1.0, line_dash="dash", line_color="#ffaf40", annotation_text="Target payback"
        )
        cpa_table = panel.copy()
        cpa_table["activation_date"] = cpa_table["activation_date"].dt.strftime("%Y-%m-%d")
        cpa_table = cpa_table.rename(
            columns={
                "avg_waltv_stx": f"Avg WALTV-{roi_window} (STX)",
                "median_waltv_stx": f"Median WALTV-{roi_window} (STX)",
                "wallets": "Wallets",
                "payback_multiple": "Payback Multiple",
                "above_target": "≥ Target",
            }
        )
        sections.extend(
            [
                "<div class='section'>",
                f"<h2>ROI & CPA Signal ({roi_window}d)</h2>",
                f"<p class='note'>Target CPA: {cpa_target_stx} STX. Payback multiple compares WALTV-{roi_window} to the target.</p>",
                pio.to_html(cpa_fig, include_plotlyjs="cdn", full_html=False),
                cpa_table.to_html(index=False),
                "</div>",
            ]
        )

    # Multi-window WALTV summary
    window_rows: list[dict[str, object]] = []
    for win, stats in window_stats.items():
        if not stats or stats["wallets"] == 0:
            continue
        window_rows.append(
            {
                "Window": f"{win}d",
                "Wallets": stats["wallets"],
                "Avg WALTV (STX)": stats["avg_waltv_stx"],
                "Median WALTV (STX)": stats["median_waltv_stx"],
                "Total Fees (STX)": stats["fee_stx_sum"],
            }
        )
    if window_rows:
        window_table = pd.DataFrame(window_rows)
        sections.extend(
            [
                "<div class='section'>",
                "<h2>WALTV Window Comparison</h2>",
                window_table.to_html(index=False),
                "</div>",
            ]
        )

    # Activation vs Trailing comparison table
    if window_stats:
        comp_rows: list[dict[str, object]] = []
        for win in sorted(window_stats.keys()):
            wstats = window_stats.get(win, {})
            tstats = trailing_stats.get(win, {})
            if not wstats:
                continue
            comp_rows.append(
                {
                    "Window": f"{win}d",
                    "WALTV Avg (STX)": wstats.get("avg_waltv_stx", 0.0),
                    "WALTV Median (STX)": wstats.get("median_waltv_stx", 0.0),
                    "WALTV Wallets": wstats.get("wallets", 0),
                    "Last Avg (STX)": tstats.get("avg_last_stx", 0.0),
                    "Last Median (STX)": tstats.get("median_last_stx", 0.0),
                    "Last Wallets": tstats.get("wallets", 0),
                    "Delta Avg (Last − WALTV)": (
                        (tstats.get("avg_last_stx", 0.0) - wstats.get("avg_waltv_stx", 0.0))
                    ),
                    "Ratio Avg (Last / WALTV)": (
                        (tstats.get("avg_last_stx", 0.0) / wstats.get("avg_waltv_stx", 1.0))
                    ),
                }
            )
        if comp_rows:
            comp_df = pd.DataFrame(comp_rows)
            sections.extend(
                [
                    "<div class='section'>",
                    "<h2>Activation vs Trailing</h2>",
                    "<p class='note'>WALTV-N measures the first N days after activation; Last-N measures the most recent N days regardless of activation date.</p>",
                    comp_df.to_html(index=False),
                    "</div>",
                ]
            )

    # PoX linkage
    pox_summary_text = (
        f"Median PoX APY across the last {pox_summary.get('cycles_analyzed', 0)} cycles is "
        f"{pox_summary.get('apy_btc_median', '—')}% with average participation "
        f"{pox_summary.get('participation_rate_mean', '—')}%."
        if pox_summary.get("cycles_analyzed", 0)
        else "PoX cycle data unavailable."
    )
    if not recent_cycles.empty:
        pox_fig = go.Figure()
        pox_fig.add_trace(
            go.Bar(
                x=recent_cycles["cycle_number"],
                y=recent_cycles["total_btc_btc"],
                name="Miner BTC Commit (BTC)",
                marker_color="#70e1ff",
            )
        )
        pox_fig.add_trace(
            go.Scatter(
                x=recent_cycles["cycle_number"],
                y=recent_cycles["apy_btc"],
                name="PoX APY (%)",
                mode="lines+markers",
                yaxis="y2",
                line=dict(color="#ffaf40", width=3),
            )
        )
        pox_fig.update_layout(
            title="Miner BTC Commit vs PoX APY (recent cycles)",
            xaxis_title="PoX Cycle",
            yaxis_title="BTC Committed",
            yaxis2=dict(
                title="APY (%)",
                overlaying="y",
                side="right",
            ),
            template="plotly_dark",
        )
        pox_table = recent_cycles[
            ["cycle_number", "total_btc_btc", "apy_btc", "participation_rate_pct"]
        ].rename(
            columns={
                "cycle_number": "Cycle",
                "total_btc_btc": "BTC Commit",
                "apy_btc": "APY (%)",
                "participation_rate_pct": "Participation (%)",
            }
        )
        sections.extend(
            [
                "<div class='section'>",
                "<h2>PoX Linkage</h2>",
                f"<p class='note'>{pox_summary_text}</p>",
                pio.to_html(pox_fig, include_plotlyjs="cdn", full_html=False),
                pox_table.to_html(index=False),
                "</div>",
            ]
        )
    else:
        sections.extend(
            [
                "<div class='section'>",
                "<h2>PoX Linkage</h2>",
                f"<p class='note'>{pox_summary_text}</p>",
                "</div>",
            ]
        )

    # Distribution of fee contribution per wallet (30d)
    if not windows_df.empty:
        w30 = windows_df[windows_df["window_days"] == 30].copy()
        if not w30.empty:
            w30["activation_date"] = w30["activation_date"].dt.strftime("%Y-%m-%d")
            hist = px.histogram(
                w30,
                x="fee_stx_sum",
                nbins=40,
                title="WALTV-30 (STX fees) Distribution",
                labels={"fee_stx_sum": "WALTV-30 (STX fees)"},
                template="plotly_dark",
            )
            hist.update_traces(
                hovertemplate="<b>WALTV-30:</b> %{x:.4f} STX<br><b>Wallets:</b> %{y}<extra></extra>"
            )
            sections.extend(
                [
                    "<div class='section'>",
                    "<h2>Wallet Value Distribution</h2>",
                    pio.to_html(hist, include_plotlyjs="cdn", full_html=False),
                    "</div>",
                ]
            )

    # Cohort average WALTV by activation date (30d window)
    if not windows_df.empty:
        w30 = windows_df[windows_df["window_days"] == 30].copy()
        if not w30.empty:
            cohort_fee = w30.groupby("activation_date")["fee_stx_sum"].agg(
                avg="mean", median="median", wallets="count"
            ).reset_index()
            cohort_fee["activation_date"] = cohort_fee["activation_date"].dt.strftime("%Y-%m-%d")
            bars = px.bar(
                cohort_fee,
                x="activation_date",
                y="avg",
                title="Average WALTV-30 (STX fees) by Activation Cohort",
                labels={"activation_date": "Activation Date", "avg": "Avg WALTV-30 (STX fees)"},
                template="plotly_dark",
            )
            bars.update_traces(
                hovertemplate="<b>Cohort:</b> %{x}<br><b>Avg WALTV-30:</b> %{y:.4f} STX<br>"
                + "<i>Median and wallets count in table below</i><extra></extra>"
            )
            table_html = cohort_fee.rename(
                columns={"avg": "Avg STX", "median": "Median STX", "wallets": "Wallets"}
            ).to_html(index=False)
            sections.extend(
                [
                    "<div class='section'>",
                    pio.to_html(bars, include_plotlyjs="cdn", full_html=False),
                    table_html,
                    "</div>",
                ]
            )

    _write_html(
        output_path,
        "Stacks Wallet Value Dashboard",
        sections,
        active_nav="value",
        last_updated=generated_at,
    )


def main() -> None:
    def positive_float(value: str) -> float:
        val = float(value)
        if val <= 0:
            raise argparse.ArgumentTypeError("Value must be > 0")
        return val
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wallet-max-days", type=int, default=180, help="History window for wallet metrics.")
    parser.add_argument(
        "--wallet-windows",
        type=int,
        nargs="+",
        default=[15, 30, 60, 90],
        help="Trailing windows (days) for wallet summary metrics.",
    )
    parser.add_argument(
        "--value-windows",
        type=int,
        nargs="+",
        default=[15, 30, 60, 90],
        help="Trailing windows (days) for wallet value dashboard.",
    )
    parser.add_argument("--macro-history-days", type=int, default=720, help="History window for macro data.")
    parser.add_argument("--force-refresh", action="store_true", help="Bypass caches when fetching data.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("out/dashboards"),
        help="Directory to write standalone dashboard HTML files.",
    )
    parser.add_argument(
        "--public-dir",
        type=Path,
        default=Path("public"),
        help="Directory for Vercel-ready static assets.",
    )
    parser.add_argument(
        "--value-only",
        action="store_true",
        help="Only build the wallet value dashboard (skip wallet & macro).",
    )
    parser.add_argument(
        "--wallet-db-path",
        type=Path,
        help="Override wallet metrics DuckDB path for read-only runs.",
    )
    parser.add_argument(
        "--wallet-db-snapshot",
        action="store_true",
        help="Copy the wallet metrics DuckDB to a temp snapshot before building dashboards.",
    )
    parser.add_argument(
        "--skip-wallet-history-sync",
        action="store_true",
        help="Skip ensure_transaction_history (useful when pointing at snapshots).",
    )
    parser.add_argument(
        "--cpa-target-stx",
        type=positive_float,
        default=5.0,
        help="Target STX WALTV for CPA payback comparisons (must be > 0).",
    )
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    wallet_html = args.out_dir / "wallet_dashboard.html"
    macro_html = args.out_dir / "macro_dashboard.html"
    value_html = args.out_dir / "wallet_value_dashboard.html"

    wallet_db_path = args.wallet_db_path
    skip_history_sync = args.skip_wallet_history_sync
    snapshot_path: Path | None = None

    if args.wallet_db_snapshot:
        snapshot_path = wallet_metrics.create_db_snapshot()
        wallet_db_path = snapshot_path
        skip_history_sync = True
        print(f"Using wallet DB snapshot at {snapshot_path}")
    elif wallet_db_path is not None and not skip_history_sync:
        print(
            "Custom wallet DB path detected; skipping history sync to avoid touching the primary DB."
        )
        skip_history_sync = True

    try:
        built_wallet = False
        built_macro = False

        if not args.value_only:
            build_wallet_dashboard(
                output_path=wallet_html,
                max_days=args.wallet_max_days,
                windows=args.wallet_windows,
                force_refresh=args.force_refresh,
                wallet_db_path=wallet_db_path,
                skip_history_sync=skip_history_sync,
            )
            built_wallet = True

        build_value_dashboard(
            output_path=value_html,
            max_days=args.wallet_max_days,
            windows=args.value_windows,
            force_refresh=args.force_refresh,
            wallet_db_path=wallet_db_path,
            skip_history_sync=skip_history_sync,
            cpa_target_stx=args.cpa_target_stx,
        )

        if not args.value_only:
            build_macro_dashboard(
                output_path=macro_html,
                history_days=args.macro_history_days,
                force_refresh=args.force_refresh,
            )
            built_macro = True
    finally:
        if snapshot_path is not None and snapshot_path.exists():
            snapshot_path.unlink()
            print(f"Removed wallet DB snapshot {snapshot_path}")

    # Copy dashboards into public structure for deployment.
    if args.public_dir:
        if not args.value_only and built_wallet:
            wallet_public = args.public_dir / "wallet" / "index.html"
            wallet_public.parent.mkdir(parents=True, exist_ok=True)
            wallet_public.write_text(wallet_html.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"Copied {wallet_html} -> {wallet_public}")

        if not args.value_only and built_macro:
            macro_public = args.public_dir / "macro" / "index.html"
            macro_public.parent.mkdir(parents=True, exist_ok=True)
            macro_public.write_text(macro_html.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"Copied {macro_html} -> {macro_public}")

        value_public = args.public_dir / "value" / "index.html"
        value_public.parent.mkdir(parents=True, exist_ok=True)
        value_public.write_text(value_html.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Copied {value_html} -> {value_public}")

        copy_static_assets(args.public_dir)
        build_public_index(args.public_dir)


if __name__ == "__main__":
    main()
