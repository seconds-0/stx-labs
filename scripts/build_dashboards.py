#!/usr/bin/env python3
"""Generate standalone HTML dashboards for wallet growth and macro analysis."""

from __future__ import annotations

import argparse
import html
import logging
import re
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from string import Template
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import dashboard_cache
from src import external_inputs
from src import macro_analysis
from src import macro_data
from src import pox_yields
from src import prices
from src import roi
from src import wallet_metrics
from src import wallet_value


LOGGER = logging.getLogger(__name__)
SUPPORTED_ROI_WINDOWS: tuple[int, ...] = (15, 30, 60, 90, 180)
RETENTION_CURVE_WINDOWS: tuple[int, ...] = roi.RETENTION_CURVE_WINDOWS
RETENTION_SEGMENT_COLORS: dict[str, str] = {
    "All": "#60a5fa",
    "Value": "#22c55e",
    "Non-value": "#f97316",
}
RETENTION_SEGMENT_LABELS: dict[str, str] = {
    "All": "All funded (D0)",
    "Value": "Value (≥1 STX fees by D30)",
    "Non-value": "Non-value (<1 STX by D30)",
}
RETROSPECTIVE_ACTIVITY_WINDOWS: tuple[int, ...] = (1, 15, 30, 60, 90, 180)
DATA_COVERAGE_START = wallet_metrics.METRICS_DATA_START
DATA_COVERAGE_LABEL = DATA_COVERAGE_START.strftime("%Y-%m-%d")
DATA_COVERAGE_NOTE = (
    f"Data coverage: wallets activated on/after {DATA_COVERAGE_LABEL} (post-Nakamoto fork)."
)


NAV_LINKS: list[tuple[str, str, str]] = [
    ("roi", "ROI", "roi/index.html"),
    ("wallet", "Wallet", "wallet/index.html"),
    ("value", "Value", "value/index.html"),
    ("macro", "Macro", "macro/index.html"),
]
DEFAULT_NAV_KEY = NAV_LINKS[0][0]

RETENTION_BUCKET_BREAKS = [-0.1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 75, 100, 125]
RETENTION_BUCKET_LABELS = [
    "<5%",
    "5-10%",
    "10-15%",
    "15-20%",
    "20-25%",
    "25-30%",
    "30-35%",
    "35-40%",
    "40-45%",
    "45-50%",
    "50-55%",
    "55-60%",
    "60-75%",
    "75-100%",
    "100%+",
]
RETENTION_BUCKET_COLORS = [
    "#5F0F99",
    "#3C1DB8",
    "#1F4FD1",
    "#0C7DB2",
    "#0EA37A",
    "#6EB22E",
    "#C7B929",
    "#E48A1F",
    "#D7541C",
    "#B71C1C",
    "#8E1B1B",
    "#702020",
    "#CD7F32",
    "#C0C0C0",
    "#FFD700",
]
RETENTION_BUCKET_NOTE = (
    "Colors progress from low-retention violet (<5%) through bronze/silver/gold for cohorts above 60%, "
    "so high-performing cohorts pop immediately—hover any cell for the exact percentage."
)
RETENTION_COLOR_SCALE: list[tuple[float, str]] = []
for idx, color in enumerate(RETENTION_BUCKET_COLORS):
    start = idx / len(RETENTION_BUCKET_COLORS)
    end = (idx + 1) / len(RETENTION_BUCKET_COLORS)
    RETENTION_COLOR_SCALE.append((start, color))
    RETENTION_COLOR_SCALE.append((end, color))

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
    nav_prefix: str = "",
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
            "    .kpi-label-row { display: flex; align-items: flex-start; gap: 0.5rem; }",
            "    .kpi-label-text { flex: 1; }",
            "    .kpi-badge { font-size: 0.65rem; text-transform: none; color: #9fb0d9; background: rgba(112,225,255,0.12); border: 1px solid #2f354a; border-radius: 999px; padding: 0.1rem 0.45rem; }",
            "    .kpi-value { font-size: 1.5rem; margin-top: 0.25rem; color: #f5f6fa; }",
            "    .kpi-subtext { font-size: 0.85rem; color: #7f8bb3; margin-top: 0.25rem; }",
            "    .kpi-footer { font-size: 0.75rem; color: #9fb0d9; margin-top: 0.35rem; font-style: italic; }",
            "    .tooltip-icon { position: relative; border: 1px solid #70e1ff; color: #70e1ff; background: rgba(112,225,255,0.12); border-radius: 999px; width: 22px; height: 22px; display: inline-flex; align-items: center; justify-content: center; font-size: 0.7rem; cursor: help; padding: 0; }",
            "    .tooltip-icon::after { content: attr(data-tooltip); position: absolute; top: 120%; right: 0; width: 240px; background: #0f1420; border: 1px solid #2f354a; border-radius: 6px; padding: 0.6rem; color: #dfe6ff; font-size: 0.75rem; line-height: 1.4; opacity: 0; pointer-events: none; transition: opacity 0.15s ease-in-out; z-index: 20; }",
            "    .tooltip-icon:hover::after, .tooltip-icon:focus-visible::after { opacity: 1; }",
            "    .tooltip-icon:focus-visible { outline: 2px solid #70e1ff; outline-offset: 2px; }",
            "    .tooltip-icon::-moz-focus-inner { border: 0; }",
            "    .retention-toggle { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; }",
            "    .retention-toggle label { cursor: pointer; font-size: 0.9rem; color: #dfe6ff; display: flex; align-items: center; gap: 0.35rem; }",
            "    .retention-toggle input { accent-color: #70e1ff; }",
            "    .retention-view { margin-top: 1rem; }",
            "    .retention-curve { background: #151b2c; border: 1px solid #2f354a; border-radius: 10px; padding: 1.25rem; }",
            "    .retention-curve-header { display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; margin-bottom: 0.75rem; }",
            "    .curve-body { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 260px); gap: 0.85rem; align-items: flex-start; width: 100%; }",
            "    .curve-chart { min-width: 0; }",
            "    .curve-table-wrapper { width: 100%; max-width: 260px; overflow: hidden; }",
            "    .retention-note { margin: 0.2rem 0 0.8rem; font-size: 0.85rem; color: #9fb0d9; line-height: 1.45; }",
            "    .retention-curve .note { margin-top: 0.9rem; position: relative; z-index: 2; line-height: 1.5; }",
            "    .curve-table { border-collapse: collapse; width: 100%; font-size: 0.85rem; background: #101628; }",
            "    .curve-table th, .curve-table td { border: 1px solid #2f354a; padding: 0.4rem 0.6rem; text-align: left; color: #dfe6ff; }",
            "    .curve-table th { background: #1b2338; font-weight: 600; }",
            "    @media (max-width: 960px) { .curve-body { grid-template-columns: 1fr; } }",
            "  </style>",
            "</head>",
            "<body>",
            "<div class='topnav'>",
            "  <strong style='margin-right: 1rem; color:#f5f6fa;'>Stacks Analytics</strong>",
        ]
        + [
            "  <a href='{href}'{active}>{label}</a>".format(
                href=f"{nav_prefix}{href.lstrip('/')}",
                active=" class='active'" if active_nav == key else "",
                label=label,
            )
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
        nav_prefix="../",
    )


def _format_number(value: float | int | None, *, decimals: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:,.{decimals}f}"


def _format_usd(value_stx: float | None, spot_price: float | None, as_of: datetime | None) -> str:
    if value_stx is None or spot_price is None:
        return ""
    usd_value = value_stx * spot_price
    if as_of:
        return f"(~${usd_value:,.2f} @ {as_of:%Y-%m-%d})"
    return f"(~${usd_value:,.2f})"


def _format_stx_with_usd(
    value_stx: float | None,
    *,
    spot_price: float | None,
    as_of: datetime | None,
    decimals: int = 2,
) -> str:
    base = _format_number(value_stx, decimals=decimals)
    if base == "—" or spot_price is None or value_stx is None:
        return f"{base} STX"
    usd_text = _format_usd(value_stx, spot_price, as_of)
    return f"{base} STX {usd_text}"


def _format_pct(value: float | None, *, decimals: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{decimals}f}%"


def _load_spot_price() -> tuple[datetime | None, float | None]:
    try:
        ts, price = prices.load_spot_price("STX-USD")
        return ts, price
    except Exception as exc:  # pragma: no cover - logging only
        LOGGER.warning("Failed to load spot STX price: %s", exc)
        return None, None


def _tooltip_icon(text: str | None, *, icon: str = "i") -> str:
    if not text:
        return ""
    safe = html.escape(text, quote=True)
    return (
        f"<button type='button' class='tooltip-icon' aria-label='{safe}' "
        f"data-tooltip='{safe}'>{icon}</button>"
    )


def render_kpi_cards(cards: Sequence[dict[str, str]]) -> str:
    if not cards:
        return "<p>No KPI data.</p>"
    rows = ["<div class='section'>", "<h2>Key KPIs</h2>", "<div class='kpi-grid'>"]
    for card in cards:
        label = html.escape(card.get("label", ""))
        badge = card.get("badge")
        badge_html = (
            f"<span class='kpi-badge'>{html.escape(str(badge))}</span>" if badge else ""
        )
        tooltip_html = _tooltip_icon(card.get("tooltip"))
        label_row = "".join(
            [
                "<div class='kpi-label-row'>",
                f"  <span class='kpi-label kpi-label-text'>{label}</span>",
                f"  {badge_html}" if badge_html else "",
                f"  {tooltip_html}" if tooltip_html else "",
                "</div>",
            ]
        )
        value = html.escape(card.get("value", "—"))
        subtext = html.escape(card.get("subtext", ""))
        footer = html.escape(card.get("footer", ""))
        rows.append(
            "\n".join(
                [
                    "<div class='kpi-card'>",
                    f"  {label_row}",
                    f"  <div class='kpi-value'>{value}</div>",
                    f"  <div class='kpi-subtext'>{subtext}</div>",
                    (f"  <div class='kpi-footer'><em>{footer}</em></div>" if footer else ""),
                    "</div>",
                ]
            )
        )
    rows.append("</div></div>")
    return "\n".join(rows)


def _pivot_retention(
    retention: pd.DataFrame, *, value_col: str = "retention_rate", freq: str = "D"
) -> pd.DataFrame:
    if retention.empty:
        return pd.DataFrame()
    pivot = retention.copy()
    pivot["activation_date"] = pd.to_datetime(pivot["activation_date"], utc=True)
    if freq == "W":
        pivot["activation_bucket"] = (
            pivot["activation_date"].dt.to_period("W-SUN").dt.to_timestamp()
        )
        grouped = (
            pivot.groupby(["activation_bucket", "window_days"])
            .apply(
                lambda df: np.average(
                    df[value_col], weights=df.get("cohort_size", 1.0)
                )
            )
            .reset_index(name=value_col)
        )
        matrix = grouped.pivot(
            index="activation_bucket", columns="window_days", values=value_col
        ).sort_index()
    else:
        matrix = (
            pivot.pivot(index="activation_date", columns="window_days", values=value_col)
            .sort_index()
        )
    return matrix


def _build_bucketed_heatmap(
    matrix: pd.DataFrame, *, title: str, height: int | None = None
) -> go.Figure | None:
    if matrix.empty:
        return None
    ordered = matrix.sort_index()
    values = ordered.to_numpy(dtype=float, copy=True)
    values = np.where(np.isnan(values), np.nan, values)
    series = pd.Series(values.ravel())
    codes = (
        pd.cut(
            series,
            bins=RETENTION_BUCKET_BREAKS,
            labels=False,
            include_lowest=True,
        )
        .to_numpy()
        .reshape(values.shape)
    )
    mask = ~np.isnan(codes)
    z_values = np.where(mask, codes, np.nan)

    label_grid = np.full(values.shape, "No data", dtype=object)
    if mask.any():
        label_grid[mask] = [
            RETENTION_BUCKET_LABELS[int(idx)] for idx in codes[mask].astype(int)
        ]
    text_matrix = np.full(values.shape, "", dtype=object)
    if mask.any():
        text_matrix[mask] = [
            f"{int(round(val))}%"
            for val in values[mask]
        ]

    customdata = np.empty(values.shape + (2,), dtype=object)
    customdata[..., 0] = values
    customdata[..., 1] = label_grid

    x_labels = [f"{int(col)}d" for col in ordered.columns]
    y_labels = [idx.strftime("%Y-%m-%d") for idx in ordered.index]

    fig = go.Figure(
        data=go.Heatmap(
            z=z_values,
            x=x_labels,
            y=y_labels,
            colorscale=RETENTION_COLOR_SCALE,
            zmin=-0.5,
            zmax=len(RETENTION_BUCKET_COLORS) - 0.5,
            text=text_matrix,
            texttemplate="%{text}",
            colorbar=dict(
                title="Retention band",
                tickmode="array",
                tickvals=list(range(len(RETENTION_BUCKET_LABELS))),
                ticktext=RETENTION_BUCKET_LABELS,
            ),
            customdata=customdata,
            hovertemplate="<b>Cohort:</b> %{y}<br>"
            "<b>Window:</b> %{x}<br>"
            "<b>Retention:</b> %{customdata[0]:.1f}%<br>"
            "<b>Band:</b> %{customdata[1]}<extra></extra>",
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title="Retention Window",
        yaxis_title="Activation Date",
        template="plotly_dark",
        height=height or max(320, 26 * len(y_labels) + 160),
    )
    return fig


def render_retention_heatmap(
    retention: pd.DataFrame,
    *,
    section_id: str | None = None,
    wrap_section: bool = True,
    heading: str = "Retention",
    note: str | None = None,
) -> str:
    if retention.empty:
        return "<p>No retention data available.</p>"
    section_slug = section_id or secrets.token_hex(4)
    toggle_name = f"retention-view-{section_slug}"
    daily_div_id = f"{section_slug}-daily"
    weekly_div_id = f"{section_slug}-weekly"
    daily_matrix = _pivot_retention(retention) * 100
    weekly_matrix = _pivot_retention(retention, freq="W") * 100
    daily_fig = _build_bucketed_heatmap(
        daily_matrix, title="Retention by Activation Date (Daily)"
    )
    weekly_fig = _build_bucketed_heatmap(
        weekly_matrix, title="Retention by Activation Week (Sunday buckets)"
    )
    if daily_fig is None and weekly_fig is None:
        return "<p>No retention data available.</p>"
    toggle_controls = f"""
    <div class='retention-toggle'>
      <label><input type="radio" name="{toggle_name}" value="daily" checked /> Daily cohorts</label>
      <label><input type="radio" name="{toggle_name}" value="weekly" /> Weekly cohorts</label>
    </div>
    """
    toggle_script = f"""
    <script>
      (function() {{
        const radios = document.querySelectorAll('input[name="{toggle_name}"]');
        const daily = document.getElementById('{daily_div_id}');
        const weekly = document.getElementById('{weekly_div_id}');
        function sync(view) {{
          if (daily) daily.style.display = view === 'daily' ? 'block' : 'none';
          if (weekly) weekly.style.display = view === 'weekly' ? 'block' : 'none';
        }}
        radios.forEach((radio) => {{
          radio.addEventListener('change', (event) => sync(event.target.value));
        }});
        sync('daily');
      }})();
    </script>
    """
    default_note = (
        "Each cell shows the share of a cohort that was active inside the final tracking band "
        "(15 days for the 15d horizon, 30 days for all others). "
        f"{RETENTION_BUCKET_NOTE}"
    )
    sections: list[str] = []
    if wrap_section:
        sections.append("<div class='section'>")
        if heading:
            sections.append(f"<h2>{heading}</h2>")
    else:
        if heading:
            sections.append(f"<h3>{heading}</h3>")
    note_text = default_note if note is None else note
    if note_text:
        sections.append(f"<p class='note'>{note_text}</p>")
    sections.append(toggle_controls)
    if daily_fig is not None:
        sections.append(
            f"<div id='{daily_div_id}'>{pio.to_html(daily_fig, include_plotlyjs='cdn', full_html=False)}</div>"
        )
    if weekly_fig is not None:
        sections.append(
            f"<div id='{weekly_div_id}' style='display:none;'>{pio.to_html(weekly_fig, include_plotlyjs=False, full_html=False)}</div>"
        )
    sections.append(toggle_script)
    if wrap_section:
        sections.append("</div>")
    return "\n".join(sections)


def _available_retention_windows(panel: pd.DataFrame) -> list[int]:
    if panel.empty or "window_days" not in panel:
        return []
    windows = sorted(
        {
            int(w)
            for w in panel["window_days"].dropna().unique().tolist()
            if pd.notna(w)
        }
    )
    return windows


def _retention_anchor_window(panel: pd.DataFrame) -> int | None:
    if panel.empty:
        return None
    if "anchor_window_days" in panel.columns:
        anchors = panel["anchor_window_days"].dropna()
        if not anchors.empty:
            return int(anchors.iloc[0])
    windows = _available_retention_windows(panel)
    return windows[-1] if windows else None


def _prepare_retention_series(
    panel: pd.DataFrame,
    segments: Sequence[str],
    windows: Sequence[int],
) -> dict[str, list[roi.RetentionPoint]]:
    series_map = roi.retention_curve_points(
        panel,
        windows=windows,
        segments=segments,
    )
    prepared: dict[str, list[roi.RetentionPoint]] = {}
    for segment, points in series_map.items():
        ordered = sorted(points, key=lambda p: p.window_days)
        if not ordered:
            continue
        if ordered[0].window_days != 0:
            origin = roi.RetentionPoint(
                window_days=0,
                retention_pct=100.0,
                eligible_users=ordered[0].eligible_users,
            )
            ordered = [origin, *ordered]
        prepared[segment] = ordered
    return prepared


def _lookup_point(points: list[roi.RetentionPoint] | None, window: int) -> roi.RetentionPoint | None:
    if not points:
        return None
    return next((pt for pt in points if pt.window_days == window), None)


def _retention_table_html(
    series_map: dict[str, list[roi.RetentionPoint]],
    windows: Sequence[int],
    segments: Sequence[str],
    *,
    include_eligible: bool,
) -> str:
    headers = ["Window"]
    for segment in segments:
        label = RETENTION_SEGMENT_LABELS.get(segment, segment)
        headers.append(label)
    if include_eligible:
        headers.append("Eligible wallets (All)")
    rows = ["<table class='curve-table'>", "<thead><tr>"]
    rows.extend([f"<th>{html.escape(header)}</th>" for header in headers])
    rows.append("</tr></thead><tbody>")
    for window in sorted({int(w) for w in windows if int(w) > 0}):
        cells = [f"<td>{window}d</td>"]
        for segment in segments:
            point = _lookup_point(series_map.get(segment), window)
            cells.append(f"<td>{_format_pct(point.retention_pct) if point else '—'}</td>")
        if include_eligible:
            eligible = _lookup_point(series_map.get("All"), window)
            if eligible:
                cells.append(f"<td>{eligible.eligible_users:,}</td>")
            else:
                cells.append("<td>—</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    rows.append("</tbody></table>")
    return "\n".join(rows)


def render_retention_blended_curve(
    panel: pd.DataFrame,
    *,
    windows: Sequence[int],
    title: str = "Blended funded retention (default view)",
    tooltip: str | None = None,
    footnote: str | None = None,
) -> str:
    available_windows = [w for w in _available_retention_windows(panel) if w in {int(x) for x in windows}]
    if not available_windows:
        return "<p class='note'>No funded cohorts have matured enough to render the blended retention curve yet.</p>"
    series_map = _prepare_retention_series(panel, ("All",), available_windows)
    points = series_map.get("All")
    if not points:
        return "<p class='note'>Not enough funded cohorts to render the blended retention curve.</p>"

    anchor_window = _retention_anchor_window(panel)
    coverage_cutoff: pd.Timestamp | None = None
    if anchor_window and "updated_at" in panel.columns:
        updated_values = panel["updated_at"].dropna()
        if not updated_values.empty:
            latest_update = pd.to_datetime(updated_values.max()).tz_convert(UTC)
            coverage_cutoff = latest_update.floor("D") - pd.Timedelta(days=anchor_window)

    detail_parts: list[str] = []
    eligible_total = points[0].eligible_users if points else None
    if eligible_total:
        detail_parts.append(
            f"Eligible funded wallets feeding every point: {eligible_total:,}."
        )
    if anchor_window and coverage_cutoff is not None:
        detail_parts.append(
            "Cohorts shown: funded-on-D0 wallets activated on/after "
            f"{DATA_COVERAGE_LABEL} and on/before {coverage_cutoff.date()} "
            f"(must be ≥{anchor_window}d old to reach D{anchor_window})."
        )
    elif anchor_window:
        detail_parts.append(
            "Cohorts shown: funded-on-D0 wallets with enough history to reach "
            f"Day {anchor_window}; shorter windows reuse the same cohort pool."
        )
    window_tags = ", ".join(f"D{w}" for w in sorted({int(w) for w in available_windows}))
    if window_tags:
        detail_parts.append(
            f"Windows plotted: {window_tags}. 15d uses a trailing 15d survival band; "
            "≥30d windows use a trailing 30d band, so wallets drop out when idle and re-enter once they transact again."
        )
    detail_html = (
        f"<p class='note retention-note'>{' '.join(detail_parts)}</p>" if detail_parts else ""
    )

    fig = go.Figure()
    fig.add_scatter(
        x=[pt.window_days for pt in points],
        y=[pt.retention_pct for pt in points],
        mode="lines+markers",
        name="All funded D0",
        line=dict(color=RETENTION_SEGMENT_COLORS["All"], width=3),
        marker=dict(color=RETENTION_SEGMENT_COLORS["All"], size=8),
        hovertemplate="<b>Day %{x}</b><br>Retention %{y:.1f}%<extra></extra>",
    )
    fig.update_layout(
        template="plotly_dark",
        height=420,
        xaxis_title="Days since activation (D0)",
        yaxis_title="Cumulative retention (%)",
        yaxis=dict(range=[0, 100], ticksuffix="%"),
        xaxis=dict(tickmode="array", tickvals=[0, *sorted({int(w) for w in windows if int(w) > 0})]),
        margin=dict(t=30, r=10, l=60, b=60),
    )
    table_html = _retention_table_html(
        series_map,
        available_windows,
        ("All",),
        include_eligible=True,
    )
    tooltip = tooltip or (
        "Blends every funded-on-D0 cohort that has matured for the selected window. "
        "Each point counts wallets with ≥1 transaction inside the trailing survival band ending on day N "
        "(15d band for D15, 30d for ≥30d), so wallets can exit and re-enter as their activity changes."
    )
    footnote = footnote or (
        "Percentages share a single eligible cohort so windows stay comparable. Wallets are only retained "
        "while they keep transacting in the trailing survival band; they immediately rejoin once fresh activity appears."
    )
    anchor_note = (
        f"Longest available window currently plotted: {anchor_window}d "
        + (
            f"(activation dates ≤ {coverage_cutoff.date()})."
            if coverage_cutoff is not None
            else "(limited by matured funded cohorts)."
        )
        if anchor_window
        else ""
    )
    return "\n".join(
        [
            "<div class='retention-curve'>",
            "<div class='retention-curve-header'>",
            f"  <h3>{title}</h3>",
            f"  {_tooltip_icon(tooltip)}",
            "</div>",
            detail_html,
            "<div class='curve-body'>",
            f"  <div class='curve-chart'>{pio.to_html(fig, include_plotlyjs='cdn', full_html=False)}</div>",
            f"  <div class='curve-table-wrapper'>{table_html}</div>",
            "</div>",
            f"<p class='note'>{footnote or ''} {DATA_COVERAGE_NOTE} {anchor_note}</p>",
            "</div>",
        ]
    )


def render_retention_segmented_lines(
    panel: pd.DataFrame,
    *,
    windows: Sequence[int],
    title: str = "Segmented retention (All / Value / Non-value)",
    tooltip: str | None = None,
    note: str | None = None,
    include_eligible: bool = True,
    include_plotly_js: bool = False,
) -> str:
    segments = ("All", "Value", "Non-value")
    available_windows = [w for w in _available_retention_windows(panel) if w in {int(x) for x in windows}]
    if not available_windows:
        return "<p class='note'>Segmented retention will appear once funded cohorts mature past the requested windows.</p>"
    series_map = _prepare_retention_series(panel, segments, available_windows)
    if not series_map:
        return "<p class='note'>Segmented retention will appear once funded cohorts mature past the requested windows.</p>"

    fig = go.Figure()
    for segment in segments:
        points = series_map.get(segment)
        if not points:
            continue
        fig.add_scatter(
            x=[pt.window_days for pt in points],
            y=[pt.retention_pct for pt in points],
            mode="lines+markers",
            name=RETENTION_SEGMENT_LABELS.get(segment, segment),
            line=dict(color=RETENTION_SEGMENT_COLORS.get(segment, "#dfe6ff"), width=3),
            marker=dict(color=RETENTION_SEGMENT_COLORS.get(segment, "#dfe6ff"), size=7),
            hovertemplate="<b>%{text}</b><br>Day %{x}: %{y:.1f}%<extra></extra>",
            text=[RETENTION_SEGMENT_LABELS.get(segment, segment)] * len(points),
        )
    fig.update_layout(
        template="plotly_dark",
        height=420,
        xaxis_title="Days since activation (D0)",
        yaxis_title="Cumulative retention (%)",
        yaxis=dict(range=[0, 100], ticksuffix="%"),
        margin=dict(t=30, r=10, l=60, b=60),
    )
    table_html = _retention_table_html(
        series_map,
        available_windows,
        tuple(seg for seg in segments if seg in series_map),
        include_eligible=include_eligible,
    )
    tooltip = tooltip or (
        "All lines require a D0-funded wallet. Value wallets generated ≥1 STX of fees within 30 days; "
        "Non-value wallets are funded but below that threshold. Points only draw when enough cohorts have matured."
    )
    anchor_window = _retention_anchor_window(panel)
    anchor_note = (
        f"Longest available window currently plotted: {anchor_window}d "
        "(limited by matured funded cohorts)."
        if anchor_window
        else ""
    )
    return "\n".join(
        [
            "<div class='retention-curve'>",
            "<div class='retention-curve-header'>",
            f"  <h3>{title}</h3>",
            f"  {_tooltip_icon(tooltip)}",
            "</div>",
            "<div class='curve-body'>",
            f"  <div class='curve-chart'>{pio.to_html(fig, include_plotlyjs=('cdn' if include_plotly_js else False), full_html=False)}</div>",
            f"  <div class='curve-table-wrapper'>{table_html}</div>",
            "</div>",
            f"<p class='note'>{note or 'Value / Non-value split determined by ≥1 STX of fees within the first 30 days.'} "
            f"{DATA_COVERAGE_NOTE} {anchor_note}</p>",
            "</div>",
        ]
    )


def render_retention_section(
    retention: pd.DataFrame,
    survival_panel: pd.DataFrame,
    *,
    cumulative_panel: pd.DataFrame | None = None,
    section_id: str = "roi-retention",
    heading: str = "Retention",
) -> str:
    if (
        retention.empty
        and survival_panel.empty
        and (cumulative_panel is None or cumulative_panel.empty)
    ):
        return "<p>No retention data available.</p>"

    blended_id = f"{section_id}-blended"
    segmented_id = f"{section_id}-segmented"
    cumulative_id = f"{section_id}-cumulative"
    heatmap_id = f"{section_id}-heatmap"
    toggle_name = f"{section_id}-view"

    blended_html = render_retention_blended_curve(
        survival_panel,
        windows=RETENTION_CURVE_WINDOWS,
        title="Blended funded retention (survival)",
        tooltip=(
            "Wallets funded on D0. A point at day N counts wallets with activity inside the trailing retention band "
            "(15d window uses 15d, ≥30d windows use 30d). Once wallets stop transacting, later windows decline."
        ),
        footnote="Measures the share of funded wallets still active in the trailing retention band.",
    )
    segmented_html = render_retention_segmented_lines(
        survival_panel,
        windows=RETENTION_CURVE_WINDOWS,
        title="Segmented retention (survival)",
        tooltip=(
            "Survival-style retention. All wallets were funded on D0; Value wallets generated ≥1 STX in the first 30 days. "
            "A point at day N requires activity in the trailing retention band."
        ),
        note="Share of funded wallets still active inside the trailing band.",
    )
    def _prepend_zero_row(panel: pd.DataFrame) -> pd.DataFrame:
        if panel.empty:
            return panel
        segments = panel["segment"].unique()
        additions: list[dict[str, object]] = []
        updated_at = datetime.now(UTC)
        for segment in segments:
            subset = panel[panel["segment"] == segment]
            if subset.empty:
                continue
            eligible = int(subset.iloc[0]["eligible_users"])
            anchor = subset.iloc[0].get("anchor_window_days")
            additions.append(
                {
                    "window_days": 0,
                    "segment": segment,
                    "retained_users": 0,
                    "eligible_users": eligible,
                    "retention_pct": 0.0,
                    "anchor_window_days": anchor,
                    "updated_at": pd.Timestamp(updated_at),
                }
            )
        if not additions:
            return panel
        augmented = pd.concat([pd.DataFrame(additions), panel], ignore_index=True)
        return augmented.sort_values(["segment", "window_days"])

    cumulative_html = ""
    if cumulative_panel is not None and not cumulative_panel.empty:
        cumulative_display = _prepend_zero_row(cumulative_panel.copy())
        cumulative_windows = (0,) + RETENTION_CURVE_WINDOWS
        cumulative_html = render_retention_segmented_lines(
            cumulative_display,
            windows=cumulative_windows,
            title="Cumulative retention (legacy)",
            tooltip=(
                "Legacy cumulative view: once a funded wallet is active between D0 and day N it remains counted for all "
                "later windows (matches the previous dashboard definition)."
            ),
            note="Legacy cumulative curve (ever active between D0 and day N).",
            include_plotly_js=False,
        )
    heatmap_html = render_retention_heatmap(
        retention,
        section_id=f"{section_id}-heat",
        wrap_section=False,
        heading="",
        note="Existing active-band heatmap (trailing 15d/30d activity).",
    )
    anchor_window = _retention_anchor_window(survival_panel)
    anchor_blurb = (
        f"Longest funded-window currently available: {anchor_window}d. "
        "180d will appear automatically once enough cohorts mature."
        if anchor_window and anchor_window < max(RETENTION_CURVE_WINDOWS)
        else ""
    )

    view_entries = [
        ("blended", "Blended survival", blended_html, blended_id),
        ("segments", "Segmented survival", segmented_html, segmented_id),
    ]
    if cumulative_html:
        view_entries.append(("cumulative", "Cumulative (legacy)", cumulative_html, cumulative_id))
    view_entries.append(("heatmap", "Active-band heatmap", heatmap_html, heatmap_id))

    toggle_controls = [
        "<div class='retention-toggle'>",
        *[
            f'<label><input type="radio" name="{toggle_name}" value="{value}" {"checked" if idx == 0 else ""} /> {label}</label>'
            for idx, (value, label, _, _) in enumerate(view_entries)
        ],
        "</div>",
    ]
    toggle_controls = "\n".join(toggle_controls)

    toggle_script = f"""
    <script>
      (function() {{
        const radios = document.querySelectorAll('input[name="{toggle_name}"]');
        const views = {{
          blended: document.getElementById('{blended_id}'),
          segments: document.getElementById('{segmented_id}'),
          cumulative: document.getElementById('{cumulative_id}') || null,
          heatmap: document.getElementById('{heatmap_id}')
        }};
        function show(view) {{
          Object.entries(views).forEach(([key, el]) => {{
            if (!el) return;
            el.style.display = key === view ? 'block' : 'none';
          }});
        }}
        radios.forEach((radio) => radio.addEventListener('change', (event) => show(event.target.value)));
        show('blended');
      }})();
    </script>
    """

    section_parts = [
        "<div class='section'>",
        f"<h2>{heading}</h2>",
        (
            "<p class='note'>Toggle between the survival-style line charts (default), the legacy cumulative curve, and the "
            "active-band heatmap. Survival curves count wallets that remain active inside the trailing retention band, "
            "whereas the cumulative view mirrors the previous “ever active” definition. "
            f"{DATA_COVERAGE_NOTE} {anchor_blurb}</p>"
        ),
        toggle_controls,
    ]
    for idx, (_, _, html, dom_id) in enumerate(view_entries):
        display = "block" if idx == 0 else "none"
        section_parts.append(f"<div id='{dom_id}' class='retention-view' style='display:{display};'>{html}</div>")
    section_parts.append(toggle_script)
    section_parts.append("</div>")
    return "\n".join(section_parts)


def render_waltv_bars(summary: pd.DataFrame, *, spot_price: float | None, as_of: datetime | None) -> str:
    # Until derived value and incentives are wired in, these “WALTV” plots are truly
    # NV (fees paid). Keep the NV label in the UI so stakeholders aren’t confused
    # and remove this note once WALTV diverges from NV.
    if summary.empty:
        return "<p>No NV data available.</p>"
    summary = summary.sort_values("window_days")
    labels = [f"{int(w)}d" for w in summary["window_days"]]
    fig = go.Figure()
    fig.add_bar(
        x=labels,
        y=summary["avg_all"],
        name="All Wallets",
        marker_color="#70e1ff",
        hovertemplate="<b>Window:</b> %{x}<br><b>All Avg:</b> %{y:.3f} STX<extra></extra>",
    )
    has_funded = "avg_funded" in summary.columns and summary["avg_funded"].notna().any()
    if has_funded:
        fig.add_bar(
            x=labels,
            y=summary["avg_funded"].fillna(0.0),
            name="Funded Wallets (D0)",
            marker_color="#22c55e",
            hovertemplate="<b>Window:</b> %{x}<br><b>Funded Avg:</b> %{y:.3f} STX<extra></extra>",
        )
    fig.add_bar(
        x=labels,
        y=summary["avg_survivor"],
        name="Survivors Only",
        marker_color="#ffaf40",
        hovertemplate="<b>Window:</b> %{x}<br><b>Survivor Avg:</b> %{y:.3f} STX<extra></extra>",
    )
    fig.update_layout(
        barmode="group",
        title="Average NV (All vs Funded vs Survivors)",
        xaxis_title="Window",
        yaxis_title="Avg NV (STX)",
        template="plotly_dark",
        height=450,
    )
    table_df = summary.copy()
    if spot_price is not None:
        table_df["Avg NV (All wallets, USD)"] = table_df["avg_all"] * spot_price
        if has_funded:
            table_df["Avg NV (Funded wallets, USD)"] = (
                table_df["avg_funded"].fillna(0.0) * spot_price
            )
        table_df["Avg NV (Survivors, USD)"] = table_df["avg_survivor"] * spot_price
    table_df = table_df.rename(
        columns={
            "window_days": "Window (d)",
            "avg_all": "Avg NV (All wallets)",
            "cohort_size": "Cohort Wallets Considered",
            "avg_funded": "Avg NV (Funded wallets)",
            "funded_wallets": "Funded Wallets Considered",
            "avg_survivor": "Avg NV (Survivors)",
        }
    )
    table = table_df.to_html(index=False, classes="summary-table", float_format=lambda x: f"{x:.4f}")
    return "\n".join(
        [
            "<div class='section'>",
            "<h2>Average NV (All vs Survivors vs Funded)</h2>",
            "<p class='note'>All-wallet averages keep zeros for dormant wallets so funnel drag is visible; "
            "survivor averages isolate wallets active inside each window’s trailing band; funded averages filter the same "
            "windows down to wallets that met the ≥10 STX D0 balance gate. NV currently equals WALTV because incentives/"
            "derived value are not applied yet. "
            f"{DATA_COVERAGE_NOTE}</p>",
            pio.to_html(fig, include_plotlyjs="cdn", full_html=False),
            table,
            "</div>",
        ]
    )


def render_payback_table(
    panel: pd.DataFrame,
    *,
    title: str,
    spot_price: float | None,
    as_of: datetime | None,
) -> str:
    # Payback math still uses WALTV columns internally but the UI shows NV labels
    # because WALTV == NV (fees) right now. Switch the copy back when derived
    # value/incentive adjustments land.
    if panel.empty:
        return "<p>No CAC/payback data available.</p>"
    table = panel.copy()
    table["activation_date"] = pd.to_datetime(
        table["activation_date"], utc=True
    ).dt.strftime("%Y-%m-%d")
    if "payback_multiple" in table:
        table["payback_multiple"] = table["payback_multiple"].apply(
            lambda v: f"{v:.2f}" if pd.notna(v) else "—"
        )
    table = table.rename(
        columns={
            "avg_waltv_stx": "Avg NV (STX)",
            "median_waltv_stx": "Median NV (STX)",
            "wallets": "Wallets",
            "cac_stx": "CAC (STX)",
            "payback_multiple": "Payback Multiple",
        }
    )
    if spot_price is not None:
        table["Avg NV (USD)"] = table["Avg NV (STX)"].astype(float) * spot_price
        table["CAC (USD)"] = table["CAC (STX)"].astype(float) * spot_price
    html_table = table.to_html(index=False, classes="summary-table", float_format=lambda x: f"{x:.4f}")
    return "\n".join(
        [
            "<div class='section'>",
            f"<h2>{title}</h2>",
            "<p class='note'>Payback Multiple = Avg NV (window) ÷ CAC; values above 1.0 mean the cohort has already covered acquisition cost at that horizon. "
            f"{DATA_COVERAGE_NOTE}</p>"
            + (
                f"<p class='note'>Spot STX/USD ≈ ${spot_price:,.4f} as of {as_of:%Y-%m-%d %H:%M %Z}</p>"
                if spot_price is not None and as_of is not None
                else ""
            ),
            html_table,
            "</div>",
        ]
    )


def render_metric_glossary() -> str:
    items = [
        ("Activation-Aligned Retention", "Share of wallets with at least one qualifying tx during the trailing band (last 30d, or 15d for the 15-day window) at each horizon."),
        ("Avg NV (All wallets)", "Cohort-size-weighted mean of cumulative STX fees for all wallets, including inactive ones. Rename back to WALTV once derived value and incentives land."),
        ("Avg NV (Survivors)", "Mean NV among wallets that transacted in the trailing band of the horizon (\"still active\" cohort)."),
        ("Expected NV-180", "Weighted average of NV-180 across cohorts that activated in the last 180d and have fully matured to 180d."),
        ("Breakeven CPA", "Maximum STX you can spend per activation while still achieving ≥1.0x payback at 180 days (equal to Expected NV-180 today)."),
        ("Payback Multiple", "Avg NV ÷ CAC for a channel/horizon. >1.0 means fees exceed acquisition cost."),
        ("Active Wallets ≤/>180d", "Split of wallets with activity in the last 30 days, grouped by whether they activated within or more than 180 days ago."),
    ]
    rows = [
        "<div class='section'>",
        "<h2>Metric Definitions</h2>",
        "<div style='background:#1f2840;padding:1rem;border-radius:8px;border:1px solid #2f354a;'>",
        "<ul style='margin:0;padding-left:1.25rem;line-height:1.5;'>",
    ]
    for title, desc in items:
        rows.append(f"<li><strong>{title}:</strong> {desc}</li>")
    rows.extend(["</ul>", "</div>", "</div>"])
    return "\n".join(rows)


def compute_retrospective_activity_summary(
    activity: pd.DataFrame,
    funded_activation: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    windows: Sequence[int] = RETROSPECTIVE_ACTIVITY_WINDOWS,
) -> tuple[pd.DataFrame, int]:
    columns = ["window_days", "window_label", "active_wallets", "active_pct"]
    if funded_activation.empty:
        return pd.DataFrame(columns=columns), 0

    eligible_pool = funded_activation[
        (funded_activation["funded_d0"].fillna(False))
        & (funded_activation["has_snapshot"].fillna(False))
    ]
    if eligible_pool.empty:
        return pd.DataFrame(columns=columns), 0

    eligible_addresses = (
        eligible_pool["address"].astype(str).dropna().drop_duplicates().tolist()
    )
    eligible_total = len(eligible_addresses)
    if eligible_total == 0:
        return pd.DataFrame(columns=columns), 0

    windows = sorted({int(w) for w in windows if int(w) > 0})
    if not windows:
        return pd.DataFrame(columns=columns), eligible_total

    eligible_set = set(eligible_addresses)
    scoped_activity = activity[activity["address"].isin(eligible_set)].copy()
    if scoped_activity.empty:
        last_activity = pd.DataFrame({"address": eligible_addresses, "last_activity_date": pd.NaT})
    else:
        last_activity = (
            scoped_activity.groupby("address")["activity_date"]
            .max()
            .rename("last_activity_date")
            .reset_index()
        )
        last_activity = (
            pd.DataFrame({"address": eligible_addresses})
            .merge(last_activity, on="address", how="left")
        )

    results: list[dict[str, object]] = []
    for window in windows:
        label = "Last 1d (today)" if window == 1 else f"Last {window}d"
        cutoff = as_of - pd.Timedelta(days=window - 1)
        if last_activity.empty:
            active = 0
        else:
            mask = last_activity["last_activity_date"].notna() & (
                last_activity["last_activity_date"] >= cutoff
            )
            active = int(mask.sum())
        pct = active / eligible_total * 100 if eligible_total else 0.0
        results.append(
            {
                "window_days": int(window),
                "window_label": label,
                "active_wallets": active,
                "active_pct": pct,
            }
        )

    summary = pd.DataFrame(results, columns=columns).sort_values("window_days")
    return summary, eligible_total


def render_retrospective_activity_section(
    summary: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    eligible_total: int,
) -> str:
    if summary.empty or eligible_total <= 0:
        return ""

    summary = summary.sort_values("window_days")
    labels = summary["window_label"].tolist()
    fig = go.Figure()
    fig.add_bar(
        x=labels,
        y=summary["active_wallets"],
        name="Active wallets",
        marker_color="#60a5fa",
        hovertemplate="<b>%{x}</b><br>Active wallets: %{y:,}<extra></extra>",
    )
    fig.add_scatter(
        x=labels,
        y=summary["active_pct"],
        yaxis="y2",
        name="% of funded",
        mode="lines+markers",
        line=dict(color="#f97316", width=3),
        marker=dict(size=8),
        hovertemplate="<b>%{x}</b><br>% of funded: %{y:.2f}%<extra></extra>",
    )
    fig.update_layout(
        template="plotly_dark",
        title="Retrospective activity pulse",
        xaxis_title="Trailing window ending today",
        yaxis=dict(title="Active wallets"),
        yaxis2=dict(
            title="% of funded wallets",
            overlaying="y",
            side="right",
            ticksuffix="%",
        ),
        legend=dict(orientation="h", yanchor="bottom", y=-0.2),
        height=420,
    )

    display = summary.copy()
    display["share_pct"] = summary["active_pct"].map(lambda v: f"{v:.2f}%")
    display = display.rename(
        columns={
            "window_label": "Window",
            "active_wallets": "Active wallets",
        }
    )[
        ["window_days", "Window", "Active wallets", "share_pct"]
    ]
    display = display.rename(columns={"window_days": "Window (d)", "share_pct": "% of funded"})
    table_html = display.to_html(index=False, classes="summary-table")

    note = (
        f"<p class='note'>Counts wallets funded on D0 (eligible pool: {eligible_total:,}) "
        f"that recorded ≥1 canonical transaction during the trailing window ending {as_of:%Y-%m-%d}. "
        "Unlike survival retention, wallets can drop out and immediately return based solely on recent activity.</p>"
    )

    return "\n".join(
        [
            "<div class='section'>",
            "<h2>Retrospective Activity</h2>",
            note,
            pio.to_html(fig, include_plotlyjs="cdn", full_html=False),
            table_html,
            "</div>",
        ]
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
    spot_price: float | None = None,
    spot_price_ts: datetime | None = None,
    metrics_bundle: wallet_metrics.WalletMetricsBundle | None = None,
    retention_active_band: pd.DataFrame | None = None,
    retention_segmented: pd.DataFrame | None = None,
    retention_segmented_cumulative: pd.DataFrame | None = None,
) -> None:
    """Generate the wallet growth dashboard HTML using cached Hiro transactions."""
    generated_at = last_updated or datetime.now(UTC)
    thr = wallet_value.ClassificationThresholds()
    if spot_price is None or spot_price_ts is None:
        spot_price_ts, spot_price = _load_spot_price()
    wallet_today = pd.Timestamp.now(tz="UTC").floor("D")
    if metrics_bundle is None and not skip_history_sync:
        wallet_metrics.ensure_transaction_history(
            max_days=max_days,
            force_refresh=force_refresh,
        )

    if metrics_bundle is not None:
        activity = metrics_bundle.activity.copy()
        first_seen = metrics_bundle.first_seen.copy()
        new_wallets = metrics_bundle.new_wallets.copy()
        active_wallets = metrics_bundle.active_wallets.copy()
        retention = metrics_bundle.retention.copy()
        fee_per_wallet = metrics_bundle.fee_per_wallet.copy()
    else:
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
        window_origin = wallet_today - pd.Timedelta(days=max_days)
        new_wallets = wallet_metrics.compute_new_wallets(
            first_seen,
            window_origin,
        )
        active_wallets = wallet_metrics.compute_active_wallets(
            activity,
            window_origin,
        )

    if retention_active_band is None:
        retention_active_band = wallet_metrics.compute_retention(
            activity,
            first_seen,
            windows,
            mode="active_band",
        )

    funded_activation = pd.DataFrame(columns=wallet_metrics.FUNDED_D0_COLUMNS)
    value_flags = pd.DataFrame(columns=["address", "activation_date", "value_30d"])
    need_segmented = retention_segmented is None or retention_segmented_cumulative is None
    if need_segmented and not first_seen.empty:
        wallet_metrics.ensure_activation_day_funded_snapshots(
            first_seen,
            lookback_days=min(3, max_days),
            funded_threshold_stx=thr.funded_stx_min,
            db_path=wallet_db_path,
        )
        funded_activation = wallet_metrics.collect_activation_day_funding(
            first_seen,
            db_path=wallet_db_path,
            persist=True,
        )
        value_flags = wallet_metrics.compute_value_flags(activity, first_seen)
    if retention_segmented_cumulative is None:
        retention_segmented_cumulative = wallet_metrics.compute_segmented_retention_panel(
            activity,
            first_seen,
            RETENTION_CURVE_WINDOWS,
            funded_activation=funded_activation,
            value_flags=value_flags,
            db_path=wallet_db_path,
            persist_path=wallet_metrics.SEGMENTED_RETENTION_PATH,
        )
    if retention_segmented is None:
        retention_segmented = wallet_metrics.compute_segmented_retention_panel(
            activity,
            first_seen,
            RETENTION_CURVE_WINDOWS,
            funded_activation=funded_activation,
            value_flags=value_flags,
            db_path=wallet_db_path,
            mode="survival",
            persist_path=wallet_metrics.SEGMENTED_RETENTION_SURVIVAL_PATH,
            persist_db=False,
        )

    if funded_activation.empty and not first_seen.empty:
        funded_activation = wallet_metrics.collect_activation_day_funding(
            first_seen,
            db_path=wallet_db_path,
            persist=True,
        )

    retro_summary, retro_eligible = compute_retrospective_activity_summary(
        activity,
        funded_activation,
        as_of=wallet_today,
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
    if spot_price is not None and not summary_df.empty:
        summary_df["avg_fee_usd"] = summary_df["avg_fee_stx"].astype(float) * spot_price
    summary_display = summary_df.rename(
        columns={
            "window_days": "Window (d)",
            "new_wallets_trailing": "New Wallets (trailing)",
            "active_wallets_trailing": "Active Wallets (trailing)",
            "retention_cohort_date": "Retention Cohort Date",
            "retention_rate_pct": "Retention Rate (%)",
            "avg_fee_stx": "Avg Fee (STX)",
            "wallets_observed": "Wallets Observed",
        }
    )
    if "avg_fee_usd" in summary_df.columns:
        summary_display["Avg Fee (USD)"] = summary_df["avg_fee_usd"]
    summary_table_html = summary_display.fillna("—").to_html(
        index=False, classes="summary-table", float_format=lambda x: f"{x:.2f}"
    )

    # Add explanatory text for table metrics
    metric_definitions = """
<div style="background: #1f2840; padding: 1rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.9rem; line-height: 1.5;">
  <strong>Metric Definitions:</strong><br/>
  • <strong>new_wallets_trailing:</strong> Count of unique addresses that made their first transaction within the trailing window<br/>
  • <strong>active_wallets_trailing:</strong> Count of unique addresses with any transaction activity in the trailing window<br/>
  • <strong>retention_cohort_date:</strong> Most recent cohort date used for retention analysis<br/>
  • <strong>retention_rate_pct:</strong> Percentage of wallets from the cohort still active after the window period<br/>
  • <strong>avg_fee_stx:</strong> Average transaction fees paid per wallet (in STX) for the cohort{}<br/>
  • <strong>wallets_observed:</strong> Number of wallets with fee data available in the window
</div>""".format(
        " (USD column estimated using latest STX/USD spot)" if spot_price is not None else ""
    )

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

    retention_section_html = ""
    if (
        (retention_active_band is not None and not retention_active_band.empty)
        or (retention_segmented is not None and not retention_segmented.empty)
        or (
            retention_segmented_cumulative is not None
            and not retention_segmented_cumulative.empty
        )
    ):
        retention_section_html = render_retention_section(
            retention=retention_active_band if retention_active_band is not None else retention,
            survival_panel=retention_segmented if retention_segmented is not None else pd.DataFrame(),
            cumulative_panel=(
                retention_segmented_cumulative
                if retention_segmented_cumulative is not None
                else pd.DataFrame()
            ),
            section_id="wallet-retention",
            heading="Cohort Retention",
        )

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

    retrospective_html = ""
    if retro_eligible > 0 and not retro_summary.empty:
        retrospective_html = render_retrospective_activity_section(
            retro_summary,
            as_of=wallet_today,
            eligible_total=retro_eligible,
        )

    sections = [
        "<div class='section'>",
        "<h1>Stacks Wallet Growth Dashboard</h1>",
        "<p class='note'>Snapshot built from Hiro canonical transactions cached locally at build time so dashboard reads are instant. "
        f"Data last refreshed {generated_at.strftime('%Y-%m-%d %H:%M UTC')}.</p>",
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
    if retrospective_html:
        sections.append(retrospective_html)
    if trend_html:
        sections.extend(
            ["<div class='section'>", "<h2>Daily Activity</h2>", trend_html, "</div>"]
        )
    if retention_section_html:
        sections.append(retention_section_html)
    if fee_html:
        sections.extend(
            ["<div class='section'>", "<h2>Fee Contribution</h2>", fee_html, "</div>"]
        )
    if not trend_html and not retention_section_html and not fee_html:
        sections.append("<p>No wallet activity available for the requested windows.</p>")

    _write_html(
        output_path,
        "Stacks Wallet Growth Dashboard",
        sections,
        active_nav="wallet",
        last_updated=generated_at,
        nav_prefix="../",
    )


# NOTE: Retention visualization mock-up. Not linked in production nav; keep for future experiments.
def build_retention_demo_dashboard(
    *,
    output_path: Path,
    max_days: int,
    windows: Sequence[int],
    force_refresh: bool,
    wallet_db_path: Path | None = None,
    skip_history_sync: bool = False,
    cohorts_in_heatmap: int = 12,
    recent_days_for_curve: int = 90,
    timeline_days: int = 180,
    active_mix_lookback_days: int = 60,
) -> None:
    """Generate a playground page with alternate retention visualizations.

    This is intentionally a mock-up for experimentation. It is not linked in the
    public navigation, but the CLI flag remains available so we can revive the
    concept quickly when needed.
    """

    def _resolve_band(window: int) -> int:
        return 15 if window <= 15 else 30

    def _weighted_rate(data: pd.DataFrame) -> float | None:
        total = float(data["cohort_size"].sum())
        if total <= 0:
            return None
        return float((data["retention_rate"] * data["cohort_size"]).sum() / total)

    def _render_compact_heatmap(retention_df: pd.DataFrame) -> str:
        ordered = retention_df.sort_values("activation_date")
        cohort_dates = (
            ordered["activation_date"].drop_duplicates().sort_values().tail(cohorts_in_heatmap)
        )
        subset = ordered[ordered["activation_date"].isin(cohort_dates)]
        matrix = _pivot_retention(subset, value_col="retention_pct")
        if matrix.empty:
            return ""
        fig = _build_bucketed_heatmap(
            matrix,
            title="Compact Heatmap (last cohorts only)",
        )
        if fig is None:
            return ""
        return pio.to_html(fig, include_plotlyjs="cdn", full_html=False)

    def _render_retention_curve(retention_df: pd.DataFrame) -> str:
        if retention_df.empty:
            return ""
        cutoff = retention_df["activation_date"].max() - pd.Timedelta(days=recent_days_for_curve)
        rows: list[dict[str, object]] = []
        for window in windows:
            window_df = retention_df[retention_df["window_days"] == window]
            if window_df.empty:
                continue
            weighted_all = _weighted_rate(window_df)
            recent_df = window_df[window_df["activation_date"] >= cutoff]
            weighted_recent = _weighted_rate(recent_df) if not recent_df.empty else None
            latest = window_df.sort_values("activation_date").iloc[-1]
            rows.append(
                {
                    "window": window,
                    "weighted_all": weighted_all * 100 if weighted_all is not None else None,
                    "weighted_recent": weighted_recent * 100 if weighted_recent is not None else None,
                    "latest_pct": float(latest["retention_rate"]) * 100,
                    "latest_date": latest["activation_date"].strftime("%Y-%m-%d"),
                }
            )
        curve_df = pd.DataFrame(rows)
        if curve_df.empty:
            return ""
        fig = go.Figure()
        if curve_df["weighted_all"].notna().any():
            fig.add_scatter(
                x=curve_df["window"],
                y=curve_df["weighted_all"],
                name="Weighted avg (all cohorts)",
                mode="lines+markers",
            )
        if curve_df["weighted_recent"].notna().any():
            fig.add_scatter(
                x=curve_df["window"],
                y=curve_df["weighted_recent"],
                name=f"Weighted avg (last {recent_days_for_curve}d cohorts)",
                mode="lines+markers",
            )
        fig.add_scatter(
            x=curve_df["window"],
            y=curve_df["latest_pct"],
            mode="markers+text",
            name="Latest cohort",
            text=[
                f"{row.latest_date}"
                for row in curve_df.itertuples()
            ],
            textposition="top center",
        )
        fig.update_layout(
            title="Aggregate Retention Curve",
            xaxis_title="Window (days)",
            yaxis_title="Retention %",
            template="plotly_dark",
            yaxis=dict(range=[0, 100]),
        )
        return pio.to_html(fig, include_plotlyjs="cdn", full_html=False)

    def _render_band_timeline(retention_df: pd.DataFrame) -> str:
        if retention_df.empty:
            return ""
        cutoff = retention_df["activation_date"].max() - pd.Timedelta(days=timeline_days)
        scoped = retention_df[retention_df["activation_date"] >= cutoff]
        if scoped.empty:
            return ""
        fig = go.Figure()
        for window in windows:
            window_df = scoped[scoped["window_days"] == window].sort_values("activation_date")
            if window_df.empty:
                continue
            band = _resolve_band(window)
            fig.add_trace(
                go.Scatter(
                    x=window_df["activation_date"],
                    y=window_df["retention_pct"],
                    mode="lines+markers",
                    name=f"{window}-day window (band {band}d)",
                    line=dict(width=2 if band == 15 else 4),
                    hovertemplate=(
                        f"<b>Cohort:</b> {{x|%Y-%m-%d}}<br><b>Window:</b> {window}d<br>"
                        f"<b>Retention:</b> {{y:.1f}}%<br>"
                        f"<i>Active if ≥1 tx in last {band} days</i><extra></extra>"
                    ),
                )
            )
        fig.update_layout(
            title=f"Retention Timeline vs Active Band (last {timeline_days}d)",
            xaxis_title="Activation Cohort",
            yaxis_title="Retention %",
            template="plotly_dark",
            yaxis=dict(range=[0, 100]),
        )
        return pio.to_html(fig, include_plotlyjs="cdn", full_html=False)

    def _render_cohort_strips(retention_df: pd.DataFrame) -> str:
        def _with_mock_points(cohort_df: pd.DataFrame, cohort_date: pd.Timestamp) -> pd.DataFrame:
            ordered = cohort_df.sort_values("window_days").copy()
            ordered["is_mock"] = False
            present_windows = ordered["window_days"].tolist()
            if len(present_windows) >= 2:
                return ordered
            if ordered.empty:
                return ordered
            target_windows = [w for w in sorted(set(windows)) if w > present_windows[-1]]
            if not target_windows:
                return ordered
            last_value = float(ordered.iloc[-1]["retention_pct"])
            mock_rows: list[dict[str, object]] = []
            decay = 0.85
            for win in target_windows:
                last_value = max(last_value * decay, 2.0)
                mock_rows.append(
                    {
                        "activation_date": cohort_date,
                        "window_days": win,
                        "retention_pct": last_value,
                        "is_mock": True,
                    }
                )
            if mock_rows:
                ordered = (
                    pd.concat([ordered, pd.DataFrame(mock_rows)], ignore_index=True)
                    .sort_values("window_days")
                    .reset_index(drop=True)
                )
            return ordered

        cohort_dates = (
            retention_df["activation_date"]
            .drop_duplicates()
            .sort_values()
            .tail(min(6, retention_df["activation_date"].nunique()))
        )
        if cohort_dates.empty:
            return ""
        fig = make_subplots(
            rows=len(cohort_dates),
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.04,
            subplot_titles=[dt.strftime("%Y-%m-%d") for dt in cohort_dates],
        )
        for idx, cohort_date in enumerate(cohort_dates, start=1):
            cohort_df = (
                retention_df[retention_df["activation_date"] == cohort_date]
                .sort_values("window_days")
            )
            if cohort_df.empty:
                continue
            augmented = _with_mock_points(cohort_df, cohort_date)
            if augmented.empty:
                continue
            marker_symbols = [
                "circle" if not is_mock else "diamond-open"
                for is_mock in augmented["is_mock"]
            ]
            marker_colors = [
                "#70e1ff" if not is_mock else "#ffaf40"
                for is_mock in augmented["is_mock"]
            ]
            fig.add_trace(
                go.Scatter(
                    x=augmented["window_days"],
                    y=augmented["retention_pct"],
                    mode="lines+markers",
                    marker=dict(size=8, symbol=marker_symbols, color=marker_colors),
                    name=cohort_date.strftime("%Y-%m-%d"),
                    showlegend=False,
                    hovertemplate="<b>Window:</b> %{x}d<br><b>Retention:</b> %{y:.1f}%<extra></extra>",
                ),
                row=idx,
                col=1,
            )
        fig.update_layout(
            height=160 * len(cohort_dates) + 120,
            template="plotly_dark",
            title="Cohort Strips (sparkline view)",
        )
        fig.update_xaxes(title_text="Window (days)", row=len(cohort_dates), col=1)
        fig.update_yaxes(range=[0, 100])
        return pio.to_html(fig, include_plotlyjs="cdn", full_html=False)

    def _render_survival_lines(retention_df: pd.DataFrame) -> str:
        if retention_df.empty:
            return ""
        monthly = (
            retention_df.assign(
                activation_month=retention_df["activation_date"].dt.to_period("M").dt.to_timestamp()
            )
            .groupby(["activation_month", "window_days"])
            .apply(_weighted_rate)
            .reset_index(name="retention_rate")
        )
        if monthly.empty:
            return ""
        recent_months = (
            monthly["activation_month"].drop_duplicates().sort_values().tail(4)
        )
        scoped = monthly[monthly["activation_month"].isin(recent_months)]
        if scoped.empty:
            return ""
        fig = go.Figure()
        for month in recent_months:
            month_df = scoped[scoped["activation_month"] == month].sort_values("window_days")
            if month_df.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    x=month_df["window_days"],
                    y=month_df["retention_rate"] * 100,
                    mode="lines+markers",
                    name=month.strftime("%Y-%m"),
                    hovertemplate=(
                        f"<b>Month:</b> {month.strftime('%Y-%m')}<br><b>Window:</b> {{x}}d<br>"
                        "<b>Retention:</b> {{y:.1f}}%<extra></extra>"
                    ),
                )
            )
        fig.update_layout(
            title="Survival-style Lines (monthly weighted cohorts)",
            xaxis_title="Window (days)",
            yaxis_title="Retention %",
            yaxis=dict(range=[0, 100]),
            template="plotly_dark",
        )
        return pio.to_html(fig, include_plotlyjs="cdn", full_html=False)

    def _render_active_mix(activity_df: pd.DataFrame, first_seen_df: pd.DataFrame) -> str:
        if activity_df.empty or first_seen_df.empty:
            return ""
        max_activity_date = activity_df["activity_date"].max()
        if pd.isna(max_activity_date):
            return ""
        lookback_start = max_activity_date - pd.Timedelta(days=active_mix_lookback_days)
        scoped = activity_df[activity_df["activity_date"] >= lookback_start].copy()
        if scoped.empty:
            return ""
        merged = scoped.merge(first_seen_df[["address", "first_seen"]], on="address", how="left")
        merged = merged.dropna(subset=["first_seen"])
        if merged.empty:
            return ""
        merged["age_days"] = (merged["activity_date"] - merged["first_seen"].dt.floor("D")).dt.days
        bins = [-1, 15, 30, 90, 180, 10_000]
        labels = ["≤15d", "16-30d", "31-90d", "91-180d", ">180d"]
        merged["age_bucket"] = pd.cut(merged["age_days"], bins=bins, labels=labels)
        counts = (
            merged.groupby(["activity_date", "age_bucket"])["address"]
            .nunique()
            .reset_index(name="active_wallets")
        )
        if counts.empty:
            return ""
        pivot = counts.pivot(index="activity_date", columns="age_bucket", values="active_wallets").fillna(0)
        totals = pivot.sum(axis=1)
        pivot = pivot[totals > 0]
        if pivot.empty:
            return ""
        share = pivot.div(pivot.sum(axis=1), axis=0) * 100
        fig = go.Figure()
        for label in labels:
            if label not in share.columns:
                continue
            fig.add_trace(
                go.Scatter(
                    x=share.index,
                    y=share[label],
                    mode="lines",
                    stackgroup="one",
                    name=label,
                    hovertemplate=(
                        f"<b>Date:</b> {{x|%Y-%m-%d}}<br><b>Age bucket:</b> {label}<br>"
                        "<b>Share:</b> {{y:.1f}}%<extra></extra>"
                    ),
                )
            )
        fig.update_layout(
            title=f"Active Base Age Mix (last {active_mix_lookback_days}d of activity)",
            yaxis_title="Share of active wallets",
            xaxis_title="Activity Date",
            yaxis=dict(range=[0, 100]),
            template="plotly_dark",
        )
        return pio.to_html(fig, include_plotlyjs="cdn", full_html=False)

    generated_at = datetime.now(UTC)
    windows = sorted(set(int(w) for w in windows if w > 0))
    if not windows:
        raise ValueError("At least one positive window is required to build the retention demo.")
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
        mode="active_band",
    )

    sections: list[str] = [
        "<div class='section'>",
        "<h1>Retention Visualization Playground</h1>",
        "<p class='note'>Prototype layouts for evaluating active-band retention visuals without touching the primary dashboard.</p>",
        "</div>",
    ]

    if retention.empty:
        sections.append(
            "<p>Retention data is not available for the requested history window. Try increasing --wallet-max-days or rerun the ingestion backfill.</p>"
        )
        _write_html(
            output_path,
            "Retention Visualization Playground",
            sections,
            active_nav="retention_demo",
            last_updated=generated_at,
            nav_prefix="../",
        )
        return

    retention["retention_pct"] = retention["retention_rate"] * 100

    heatmap_html = _render_compact_heatmap(retention)
    curve_html = _render_retention_curve(retention)
    timeline_html = _render_band_timeline(retention)
    strips_html = _render_cohort_strips(retention)
    survival_html = _render_survival_lines(retention)
    active_mix_html = _render_active_mix(activity, first_seen)

    if heatmap_html:
        sections.extend(
            [
                "<div class='section'>",
                "<h2>1. Tiered layout: compact heatmap</h2>",
                "<p class='note'>Shows the same data density as the wallet page but limits to recent cohorts. "
                f"{RETENTION_BUCKET_NOTE}</p>",
                heatmap_html,
                "</div>",
            ]
        )
    if curve_html:
        sections.extend(
            [
                "<div class='section'>",
                "<h2>2. Aggregate retention curve</h2>",
                "<p class='note'>Weighted averages turn the heatmap into a single curve so trend spotting is easier.</p>",
                curve_html,
                "</div>",
            ]
        )
    if timeline_html:
        sections.extend(
            [
                "<div class='section'>",
                "<h2>3. Retention band timeline</h2>",
                "<p class='note'>Each line encodes the trailing band (15d vs 30d) via line weight to reinforce what “still active” means.</p>",
                timeline_html,
                "</div>",
            ]
        )
    if strips_html:
        sections.extend(
            [
                "<div class='section'>",
                "<h2>4. Cohort strips</h2>",
                "<p class='note'>Sparkline rows make it easy to compare the latest cohorts side-by-side without scrolling a full heatmap. Diamond markers extend cohorts with mocked future points so you can preview the curve even before the real data matures.</p>",
                strips_html,
                "</div>",
            ]
        )
    if survival_html:
        sections.extend(
            [
                "<div class='section'>",
                "<h2>5. Survival-style lines</h2>",
                "<p class='note'>Monthly weighted curves mimic survival plots and highlight slope changes at each horizon.</p>",
                survival_html,
                "</div>",
            ]
        )
    if active_mix_html:
        sections.extend(
            [
                "<div class='section'>",
                "<h2>6. Active base composition</h2>",
                "<p class='note'>Shows whether today’s activity is dominated by fresh or long-tenured wallets.</p>",
                active_mix_html,
                "</div>",
            ]
        )

    sections.append(
        "<div class='section'><p class='note'>All charts reuse the existing wallet metrics dataset. Tweak parameters in build_retention_demo_dashboard to try different cohort windows or lookbacks.</p></div>"
    )

    _write_html(
        output_path,
        "Retention Visualization Playground",
        sections,
        active_nav="retention_demo",
        last_updated=generated_at,
        nav_prefix="../",
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
        "<p class='note'>Context panel covering FRED labor data, Yahoo Finance benchmarks, and CoinGecko crypto series "
        f"for {start_str} → {end_str}. Updated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}.</p>",
    ]
    if price_fetch_errors:
        macro_sections.append(
            "<p class='note'>Some price feeds failed to refresh: " + " / ".join(price_fetch_errors) + "</p>"
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
                "<p class='note'>Correlations use overlapping dates only; a positive lag means the indicator historically led STX/BTC by that many days.</p>",
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
        nav_prefix="../",
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
    default_href = NAV_LINKS[0][2]
    default_key = DEFAULT_NAV_KEY
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
        <p>Use the sidebar to switch dashboards or <a class="open-link" id="open-new" href="$default_href" target="_blank" rel="noreferrer">open current in new tab ↗</a></p>
      </div>
      <iframe id="dash-frame" src="$default_href" title="Stacks Analytics Dashboard"></iframe>
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
      const initialKey = window.location.hash ? window.location.hash.slice(1) : '$default_key';
      const initialLink = links.find((link) => link.dataset.key === initialKey) || links[0];
      activate(initialLink.dataset.key, initialLink.dataset.href, false);
    </script>
  </body>
</html>
"""
    )
    index_path.write_text(
        template.substitute(
            stamp=stamp,
            nav_links=nav_links,
            default_href=default_href,
            default_key=default_key,
        ),
        encoding="utf-8",
    )
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
    spot_price: float | None = None,
    spot_price_ts: datetime | None = None,
) -> None:
    """Generate CPI/CPA-style wallet value dashboard with PoX linkage."""
    generated_at = datetime.now(UTC)
    if spot_price is None or spot_price_ts is None:
        spot_price_ts, spot_price = _load_spot_price()
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
        price_window_cycles = max(cycles_df["cycle_number"].max() - 32, cycles_df["cycle_number"].min())
        prices_df = pox_yields.compute_cycle_price_averages(
            cycles_df,
            start_cycle=price_window_cycles,
            force_refresh=force_refresh,
        )
        cycle_apy_df = pox_yields.calculate_cycle_apy(
            cycles_df,
            rewards_df,
            prices_df=prices_df,
        )
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
    usd_hint = ""
    if spot_price is not None and spot_price_ts is not None:
        usd_hint = f" Spot STX/USD ≈ ${spot_price:,.4f} (as of {spot_price_ts:%Y-%m-%d %H:%M %Z})."
    sections.append(
        "<p class='note'>Network Value (NV) converts each wallet's STX fees into BTC using the closest historical STX/BTC print. "
        "Because incentives and derived value adjustments have not landed yet, NV and WALTV are identical. "
        f"Snapshot generated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}.{usd_hint}</p>"
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

    def _fmt_stx_value(value: float | None) -> str:
        return _format_stx_with_usd(
            value, spot_price=spot_price, as_of=spot_price_ts, decimals=2
        )

    sections.append("<div class='section'>")
    sections.append("<div class='kpi-grid'>")
    sections.append(
        f"<div class='kpi-card'><div class='kpi-label'>30d Network Value</div><div class='kpi-value'>{_fmt(kpis['total_nv_btc'], ' BTC')}</div><div class='kpi-subtext'>{_fmt_stx_value(kpis['total_fee_stx'])}</div></div>"
    )
    sections.append(
        f"<div class='kpi-card'><div class='kpi-label'>Avg WALTV-30</div><div class='kpi-value'>{_fmt_stx_value(kpis['avg_waltv_stx'])}</div><div class='kpi-subtext'>Median {_fmt_stx_value(kpis['median_waltv_stx'])}</div></div>"
    )
    # Trailing 30-day average across all wallets (calendar-anchored)
    ts30 = trailing_stats.get(30, {})
    if ts30 and ts30.get("wallets", 0) > 0:
        sections.append(
            f"<div class='kpi-card'><div class='kpi-label'>Avg Last-30</div><div class='kpi-value'>{_fmt_stx_value(ts30.get('avg_last_stx', 0.0))}</div><div class='kpi-subtext'>Median {_fmt_stx_value(ts30.get('median_last_stx', 0.0))}</div></div>"
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
                f"<div class='kpi-value'>{_fmt_stx_value(stats['avg_waltv_stx'])}</div>"
                f"<div class='kpi-subtext'>Median {_fmt_stx_value(stats['median_waltv_stx'])}</div></div>"
            )
        # Add trailing counterpart
        tstats = trailing_stats.get(extra_window, {})
        if tstats and tstats.get("wallets", 0) > 0:
            sections.append(
                f"<div class='kpi-card'><div class='kpi-label'>Avg Last-{extra_window}</div>"
                f"<div class='kpi-value'>{_fmt_stx_value(tstats.get('avg_last_stx', 0.0))}</div>"
                f"<div class='kpi-subtext'>Median {_fmt_stx_value(tstats.get('median_last_stx', 0.0))}</div></div>"
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
        if spot_price is not None:
            cpa_table[f"Avg WALTV-{roi_window} (USD)"] = (
                cpa_table[f"Avg WALTV-{roi_window} (STX)"].astype(float) * spot_price
            )
            cpa_table[f"Median WALTV-{roi_window} (USD)"] = (
                cpa_table[f"Median WALTV-{roi_window} (STX)"].astype(float) * spot_price
            )
        target_caption = f"{cpa_target_stx} STX CPA target"
        if spot_price is not None:
            target_caption += f" (~${cpa_target_stx * spot_price:,.2f})"
        sections.extend(
            [
                "<div class='section'>",
                f"<h2>ROI & CPA Signal ({roi_window}d)</h2>",
                f"<p class='note'>Payback Multiple = WALTV-{roi_window} ÷ target CPA ({target_caption}). "
                f"Series sitting above 1.0 have already earned back their acquisition cost within {roi_window} days.</p>",
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
        if spot_price is not None:
            window_table["Avg WALTV (USD)"] = window_table["Avg WALTV (STX)"].astype(float) * spot_price
            window_table["Median WALTV (USD)"] = window_table["Median WALTV (STX)"].astype(float) * spot_price
            window_table["Total Fees (USD)"] = window_table["Total Fees (STX)"].astype(float) * spot_price
        sections.extend(
            [
                "<div class='section'>",
                "<h2>WALTV Window Comparison</h2>",
                window_table.to_html(index=False, float_format=lambda x: f"{x:.4f}"),
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
            if spot_price is not None:
                comp_df["WALTV Avg (USD)"] = comp_df["WALTV Avg (STX)"].astype(float) * spot_price
                comp_df["Last Avg (USD)"] = comp_df["Last Avg (STX)"].astype(float) * spot_price
            sections.extend(
                [
                    "<div class='section'>",
                    "<h2>Activation vs Trailing</h2>",
                    "<p class='note'>WALTV-N tracks the first N days post-activation, while Last-N measures the most recent calendar window for the entire base. "
                    "Comparing the two highlights whether fresh cohorts or the mature install base are driving value. "
                    f"{DATA_COVERAGE_NOTE}</p>",
                    comp_df.to_html(index=False, float_format=lambda x: f"{x:.4f}"),
                    "</div>",
                ]
            )

    # PoX linkage
    pox_summary_text = (
        f"Across the last {pox_summary.get('cycles_analyzed', 0)} PoX cycles, median APY was "
        f"{pox_summary.get('apy_btc_median', '—')}% with average participation "
        f"{pox_summary.get('participation_rate_mean', '—')}%—a useful benchmark for wallet-derived NV."
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
                "<p class='note'>Under construction: APY calibration is being redone in a separate task, so treat these values as provisional.</p>",
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
                "<p class='note'>Under construction: APY calibration is being redone in a separate task, so treat these values as provisional.</p>",
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
            if spot_price is not None:
                cohort_fee["Avg USD"] = cohort_fee["avg"] * spot_price
                cohort_fee["Median USD"] = cohort_fee["median"] * spot_price
            table_html = cohort_fee.rename(
                columns={"avg": "Avg STX", "median": "Median STX", "wallets": "Wallets"}
            ).to_html(index=False, float_format=lambda x: f"{x:.4f}")
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
        nav_prefix="../",
    )


def build_roi_dashboard(
    *,
    output_path: Path,
    max_days: int,
    windows: Sequence[int],
    force_refresh: bool,
    wallet_db_path: Path | None = None,
    skip_history_sync: bool = False,
    cac_file: Path | None = None,
    channel_map_file: Path | None = None,
    incentives_file: Path | None = None,
    ensure_wallet_balances: bool = False,
    spot_price: float | None = None,
    spot_price_ts: datetime | None = None,
    precomputed_inputs: roi.RoiInputs | None = None,
) -> None:
    """Generate the ROI one-pager dashboard."""
    generated_at = datetime.now(UTC)
    if spot_price is None or spot_price_ts is None:
        spot_price_ts, spot_price = _load_spot_price()

    if precomputed_inputs is not None:
        inputs = precomputed_inputs
    else:
        inputs = roi.build_inputs(
            max_days=max_days,
            windows=windows,
            force_refresh=force_refresh,
            wallet_db_path=wallet_db_path,
            skip_history_sync=skip_history_sync,
            ensure_balances=ensure_wallet_balances,
        )

    retention = inputs.retention
    waltv_all = roi.summarize_waltv_by_window(inputs.windows_agg, inputs.first_seen)
    survivors = roi.waltv_survivors_only(inputs.windows_agg)
    expected_180 = roi.expected_waltv_180(
        inputs.windows_agg, inputs.first_seen, horizon_days=180, recent_activation_days=180
    )
    active_breakdown = roi.active_base_breakdown(inputs.activity, inputs.first_seen)

    window_rollups: list[dict[str, float]] = []
    funded_windows = pd.DataFrame(columns=inputs.windows_agg.columns)
    if (
        hasattr(inputs, "funded_activation")
        and inputs.funded_activation is not None
        and not inputs.funded_activation.empty
    ):
        funded_addresses = inputs.funded_activation[
            inputs.funded_activation["funded_d0"]
            & inputs.funded_activation["has_snapshot"]
        ]["address"].astype(str)
        if not funded_addresses.empty:
            funded_windows = inputs.windows_agg[
                inputs.windows_agg["address"].astype(str).isin(set(funded_addresses))
            ].copy()
    else:
        funded_windows = pd.DataFrame(columns=inputs.windows_agg.columns)
    if not waltv_all.empty:
        for window in sorted(waltv_all["window_days"].unique()):
            subset = waltv_all[waltv_all["window_days"] == window]
            if subset.empty:
                continue
            total_fee = subset["total_fee_stx"].sum()
            total_cohort = subset["cohort_size"].sum()
            if not total_cohort:
                continue
            avg_all = total_fee / total_cohort
            survivor_subset = survivors[survivors["window_days"] == window]
            survivor_wallets = survivor_subset["survivor_wallets"].sum()
            if survivor_wallets:
                avg_survivor = (
                    (
                        survivor_subset["avg_waltv_survivors_stx"]
                        * survivor_subset["survivor_wallets"]
                    ).sum()
                    / survivor_wallets
                )
            else:
                avg_survivor = 0.0
            funded_subset = pd.DataFrame(columns=inputs.windows_agg.columns)
            funded_wallets = 0
            avg_funded = 0.0
            if not funded_windows.empty:
                funded_subset = funded_windows[funded_windows["window_days"] == window]
                if not funded_subset.empty:
                    funded_wallets = len(funded_subset)
                    total_funded_fee = funded_subset["fee_stx_sum"].sum()
                    if funded_wallets:
                        avg_funded = total_funded_fee / funded_wallets
            window_rollups.append(
                {
                    "window_days": window,
                    "avg_all": avg_all,
                    "avg_survivor": avg_survivor,
                    "cohort_size": total_cohort,
                    "avg_funded": avg_funded if funded_wallets else None,
                    "funded_wallets": funded_wallets,
                }
            )
    window_summary = pd.DataFrame(window_rollups)

    retention_snapshot = roi.retention_snapshot_summary(
        inputs.retention_segmented,
        windows=RETENTION_CURVE_WINDOWS,
        value_window=30,
    )

    cards: list[dict[str, str]] = []
    cards.append(
        {
            "label": "Expected NV-180",
            "value": _format_stx_with_usd(
                expected_180, spot_price=spot_price, as_of=spot_price_ts
            ),
            "subtext": "Weighted Avg (last 180d activations, fully matured)",
            "tooltip": (
                "Pipeline: wallet_metrics → wallet_value.compute_wallet_windows. We take every cohort activated in the last "
                "180 calendar days that has already reached day 180, sum their fee_stx_totals from DuckDB, and divide by the "
                "cohort size. This is pure on-chain fee spend (NV) until derived value lands. "
                f"{DATA_COVERAGE_NOTE}"
            ),
        }
    )
    cards.append(
        {
            "label": "Breakeven CPA @180d (NV)",
            "value": _format_stx_with_usd(
                expected_180, spot_price=spot_price, as_of=spot_price_ts
            ),
            "subtext": "Spend ≤ this STX to hit payback 1.0",
            "tooltip": (
                "Same data source as Expected NV-180 (wallet_metrics + wallet_value aggregates). This number is the guardrail "
                "CPA that still yields a 1.0× payback at 180d, so we simply reuse the weighted NV-180 output as the max "
                "allowable spend per funded activation. "
                f"{DATA_COVERAGE_NOTE}"
            ),
        }
    )
    young_wallets = active_breakdown.get("young_wallets", 0)
    legacy_wallets = active_breakdown.get("legacy_wallets", 0)
    total_active_wallets = young_wallets + legacy_wallets
    young_pct = (
        young_wallets / total_active_wallets * 100 if total_active_wallets else 0.0
    )
    legacy_pct = (
        legacy_wallets / total_active_wallets * 100 if total_active_wallets else 0.0
    )
    cards.append(
        {
            "label": "Active Wallets ≤180d",
            "value": f"{young_wallets} ({young_pct:.1f}%)",
            "subtext": "Share of active base in last 30d",
            "tooltip": (
                "Source: roi.active_base_breakdown. We pull the last 30 calendar days of wallet_metrics activity, bucket each "
                "address by activation age from first_seen, and count + sum fees for wallets whose activation date is within "
                "180 days. Percentage = this bucket ÷ total active wallets in the last 30 days. "
                f"{DATA_COVERAGE_NOTE}"
            ),
        }
    )
    cards.append(
        {
            "label": "Active Wallets >180d",
            "value": f"{legacy_wallets} ({legacy_pct:.1f}%)",
            "subtext": "Legacy share of last-30d active base",
            "tooltip": (
                "Same dataset as the ≤180d card, but we keep addresses whose activation date is older than 180 days. "
                "Shows how much of the current 30-day active base relies on legacy cohorts sourced from wallet_metrics. "
                f"{DATA_COVERAGE_NOTE}"
            ),
        }
    )

    if retention_snapshot:
        ordered_windows = [w for w in (15, 30, 60, 90, 180) if w in retention_snapshot["metrics"]]
        headline_window = ordered_windows[0] if ordered_windows else None
        headline_value = (
            f"{headline_window}d {_format_pct(retention_snapshot['metrics'][headline_window])}"
            if headline_window
            else _format_pct(None)
        )
        sub_parts: list[str] = []
        for window in ordered_windows[1:]:
            sub_parts.append(f"{window}d {_format_pct(retention_snapshot['metrics'][window])}")
        value_pair = retention_snapshot.get("value_pair") or {}
        pair_items: list[str] = []
        if value_pair.get("value_pct") is not None:
            pair_items.append(f"Value {_format_pct(value_pair['value_pct'])}")
        if value_pair.get("non_value_pct") is not None:
            pair_items.append(f"Non-value {_format_pct(value_pair['non_value_pct'])}")
        if pair_items:
            sub_parts.append(f"{value_pair.get('window_days', 30)}d: {' vs '.join(pair_items)}")
        cards.append(
            {
                "label": "Funded Retention Snapshot",
                "value": headline_value,
                "subtext": " | ".join(sub_parts),
                "footer": f"Eligible {retention_snapshot['eligible_users']:,} funded wallets",
                "tooltip": (
                    "Source: wallet_metrics.collect_activation_day_funding + compute_segmented_retention_panel (survival mode). "
                    "We only include wallets whose D0 balance snapshot met the funded threshold (≥10 STX) and count them as "
                    "retained when they stay active inside the trailing retention band (15d for 15d window, 30d otherwise). "
                    "Percentages are cohort-size weighted and stored in retention_segmented_survival.parquet for reuse. "
                    f"{DATA_COVERAGE_NOTE}"
                ),
            }
        )

    sections: list[str] = []
    sections.append(render_kpi_cards(cards))
    sections.append(f"<p class='note'>{DATA_COVERAGE_NOTE}</p>")
    sections.append(
        render_retention_section(
            retention=retention,
            survival_panel=inputs.retention_segmented,
            cumulative_panel=inputs.retention_segmented_cumulative,
            section_id="roi-retention",
            heading="Retention",
        )
    )
    sections.append(
        render_waltv_bars(window_summary, spot_price=spot_price, as_of=spot_price_ts)
    )

    payback_panel = pd.DataFrame()
    channel_map_df = None
    cac_map = None
    if channel_map_file and channel_map_file.exists():
        channel_map_df = external_inputs.load_address_channel_map(channel_map_file)
    if cac_file and cac_file.exists():
        cac_map = external_inputs.load_cac_by_channel(cac_file)
    if channel_map_df is not None:
        payback_panel = wallet_value.compute_cpa_panel_by_channel(
            inputs.windows_agg,
            channel_map_df,
            window_days=180,
            cac_by_channel=cac_map,
        )
    if not payback_panel.empty:
        sections.append(
            render_payback_table(
                payback_panel,
                title="Payback vs CAC (180d cohorts)",
                spot_price=spot_price,
                as_of=spot_price_ts,
            )
        )
    else:
        guardrail = (
            "<div class='section'>"
            "<h2>Payback vs CAC</h2>"
            "<p class='note'>Channel payback requires --cac-file (channel,cac_stx) plus --channel-map-file "
            "(address,activation_date,channel). Until those inputs are wired, lean on the breakeven CPA guardrail below. "
            f"{DATA_COVERAGE_NOTE}</p>"
            f"<div class='kpi-card' style='max-width:260px;'>"
            "<div class='kpi-label'>Breakeven CPA @180d (NV)</div>"
            f"<div class='kpi-value'>{_format_number(expected_180)} STX</div>"
            f"<div class='kpi-subtext'>Spend per activation that keeps payback ≥ 1.0 {_format_usd(expected_180, spot_price, spot_price_ts)}</div>"
            "</div>"
            "</div>"
        )
        sections.append(guardrail)

    if incentives_file and incentives_file.exists():
        # Validate schema even if unused; will be consumed in future iterations.
        external_inputs.load_incentives(incentives_file)

    sections.append(render_metric_glossary())

    _write_html(
        output_path,
        "Stacks ROI One-Pager",
        sections,
        active_nav="roi",
        last_updated=generated_at,
        nav_prefix="../",
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
    parser.add_argument(
        "--one-pager-only",
        action="store_true",
        help="Build only the ROI one-pager dashboard.",
    )
    parser.add_argument(
        "--roi-windows",
        type=int,
        nargs="+",
        default=list(SUPPORTED_ROI_WINDOWS),
        help="Activation windows for ROI dashboard (days).",
    )
    parser.add_argument(
        "--cac-file",
        type=Path,
        help="CSV with channel,cac_stx columns to compute payback multiples.",
    )
    parser.add_argument(
        "--channel-map-file",
        type=Path,
        help="CSV with address,activation_date,channel columns for attribution.",
    )
    parser.add_argument(
        "--incentives-file",
        type=Path,
        help="CSV with address,paid_date,amount_stx columns for incentives (optional).",
    )
    parser.add_argument(
        "--ensure-wallet-balances",
        action="store_true",
        help="Refresh funded balances for recent activations before building ROI dashboards (defaults to off to avoid Hiro rate-limits).",
    )
    parser.add_argument(
        "--retention-demo",
        action="store_true",
        help="Also build the retention visualization playground.",
    )
    parser.add_argument(
        "--retention-demo-only",
        action="store_true",
        help="Skip other dashboards and only build the retention visualization playground.",
    )
    parser.add_argument(
        "--no-dashboard-cache",
        action="store_true",
        help="Bypass the precomputed dashboard cache and recompute everything from scratch.",
    )
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    wallet_html = args.out_dir / "wallet_dashboard.html"
    macro_html = args.out_dir / "macro_dashboard.html"
    value_html = args.out_dir / "wallet_value_dashboard.html"
    roi_html = args.out_dir / "roi_dashboard.html"
    retention_demo_html = args.out_dir / "retention_demo.html"

    use_dashboard_cache = not args.no_dashboard_cache
    if args.wallet_db_path is not None or args.force_refresh:
        use_dashboard_cache = False

    cached_wallet_bundle: wallet_metrics.WalletMetricsBundle | None = None
    cached_retention_active: pd.DataFrame | None = None
    cached_roi_inputs: roi.RoiInputs | None = None
    cached_segmented_survival: pd.DataFrame | None = None
    cached_segmented_cumulative: pd.DataFrame | None = None
    if use_dashboard_cache:
        cached_wallet_bundle, cached_retention_active = dashboard_cache.load_wallet_bundle_from_cache()
        cached_roi_inputs = dashboard_cache.load_roi_inputs_from_cache()
        if cached_wallet_bundle is not None:
            print("Using cached wallet metrics bundle.")
        if cached_roi_inputs is not None:
            print("Using cached ROI inputs bundle.")
    if cached_roi_inputs is not None:
        if not cached_roi_inputs.retention_segmented.empty:
            cached_segmented_survival = cached_roi_inputs.retention_segmented
        if not cached_roi_inputs.retention_segmented_cumulative.empty:
            cached_segmented_cumulative = cached_roi_inputs.retention_segmented_cumulative

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

    spot_price_ts, spot_price = _load_spot_price()

    try:
        built_wallet = False
        built_macro = False
        built_value = False
        built_roi = False
        built_retention_demo = False

        build_wallet = (
            not args.value_only and not args.one_pager_only and not args.retention_demo_only
        )
        build_macro = (
            not args.value_only and not args.one_pager_only and not args.retention_demo_only
        )
        build_value = not args.one_pager_only and not args.retention_demo_only
        build_roi = not args.retention_demo_only
        build_retention_demo = args.retention_demo or args.retention_demo_only

        wallet_bundle_arg = cached_wallet_bundle if cached_wallet_bundle is not None else None
        wallet_retention_active_arg = (
            cached_retention_active
            if cached_retention_active is not None and not cached_retention_active.empty
            else None
        )
        wallet_segmented_arg = (
            cached_segmented_survival
            if cached_segmented_survival is not None and not cached_segmented_survival.empty
            else None
        )
        wallet_segmented_cumulative_arg = (
            cached_segmented_cumulative
            if cached_segmented_cumulative is not None and not cached_segmented_cumulative.empty
            else None
        )
        roi_inputs_arg = cached_roi_inputs if cached_roi_inputs is not None else None

        if build_wallet:
            build_wallet_dashboard(
                output_path=wallet_html,
                max_days=args.wallet_max_days,
                windows=args.wallet_windows,
                force_refresh=args.force_refresh,
                wallet_db_path=wallet_db_path,
                skip_history_sync=skip_history_sync,
                spot_price=spot_price,
                spot_price_ts=spot_price_ts,
                metrics_bundle=wallet_bundle_arg,
                retention_active_band=wallet_retention_active_arg,
                retention_segmented=wallet_segmented_arg,
                retention_segmented_cumulative=wallet_segmented_cumulative_arg,
            )
            built_wallet = True

        if build_value:
            build_value_dashboard(
                output_path=value_html,
                max_days=args.wallet_max_days,
                windows=args.value_windows,
                force_refresh=args.force_refresh,
                wallet_db_path=wallet_db_path,
                skip_history_sync=skip_history_sync,
                cpa_target_stx=args.cpa_target_stx,
                spot_price=spot_price,
                spot_price_ts=spot_price_ts,
            )
            built_value = True

        if build_macro:
            build_macro_dashboard(
                output_path=macro_html,
                history_days=args.macro_history_days,
                force_refresh=args.force_refresh,
            )
            built_macro = True

        if build_roi:
            build_roi_dashboard(
                output_path=roi_html,
                max_days=args.wallet_max_days,
                windows=args.roi_windows,
                force_refresh=args.force_refresh,
                wallet_db_path=wallet_db_path,
                skip_history_sync=skip_history_sync,
                cac_file=args.cac_file,
                channel_map_file=args.channel_map_file,
                incentives_file=args.incentives_file,
                ensure_wallet_balances=args.ensure_wallet_balances,
                spot_price=spot_price,
                spot_price_ts=spot_price_ts,
                precomputed_inputs=roi_inputs_arg,
            )
            built_roi = True

        if build_retention_demo:
            build_retention_demo_dashboard(
                output_path=retention_demo_html,
                max_days=args.wallet_max_days,
                windows=args.roi_windows,
                force_refresh=args.force_refresh,
                wallet_db_path=wallet_db_path,
                skip_history_sync=skip_history_sync,
            )
            built_retention_demo = True
    finally:
        if snapshot_path is not None and snapshot_path.exists():
            snapshot_path.unlink()
            print(f"Removed wallet DB snapshot {snapshot_path}")

    # Copy dashboards into public structure for deployment.
    if args.public_dir:
        if built_wallet:
            wallet_public = args.public_dir / "wallet" / "index.html"
            wallet_public.parent.mkdir(parents=True, exist_ok=True)
            wallet_public.write_text(wallet_html.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"Copied {wallet_html} -> {wallet_public}")

        if built_macro:
            macro_public = args.public_dir / "macro" / "index.html"
            macro_public.parent.mkdir(parents=True, exist_ok=True)
            macro_public.write_text(macro_html.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"Copied {macro_html} -> {macro_public}")

        if built_value:
            value_public = args.public_dir / "value" / "index.html"
            value_public.parent.mkdir(parents=True, exist_ok=True)
            value_public.write_text(value_html.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"Copied {value_html} -> {value_public}")

        if built_roi:
            roi_public = args.public_dir / "roi" / "index.html"
            roi_public.parent.mkdir(parents=True, exist_ok=True)
            roi_public.write_text(roi_html.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"Copied {roi_html} -> {roi_public}")

        if built_retention_demo:
            retention_public = args.public_dir / "retention_demo" / "index.html"
            retention_public.parent.mkdir(parents=True, exist_ok=True)
            retention_public.write_text(retention_demo_html.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"Copied {retention_demo_html} -> {retention_public}")

        copy_static_assets(args.public_dir)
        build_public_index(args.public_dir)


if __name__ == "__main__":
    main()
