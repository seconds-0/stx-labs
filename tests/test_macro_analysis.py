from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from src import macro_analysis


def test_build_macro_correlation_panel_merges_prices(monkeypatch):
    def fake_macro(start, end, force_refresh=False):
        return pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")],
                "sp500_close": [4800.0, 4820.0],
            }
        )

    def fake_price(start, end, frequency="1d", force_refresh=False):
        return pd.DataFrame(
            {
                "ts": pd.to_datetime(
                    ["2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z"], utc=True
                ),
                "stx_usd": [1.1, 1.2],
                "btc_usd": [50000, 51000],
                "stx_btc": [1.1 / 50000, 1.2 / 51000],
            }
        )

    monkeypatch.setattr(macro_analysis.macro_data, "load_macro_panel", fake_macro)
    monkeypatch.setattr(macro_analysis.prices, "load_price_panel", fake_price)

    panel = macro_analysis.build_macro_correlation_panel("2024-01-01", "2024-01-05")
    assert "stx_btc" in panel.columns
    assert "sp500_close" in panel.columns
    assert len(panel) == 2


def test_compute_indicator_correlations_simple():
    panel = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=5, tz=UTC),
            "stx_btc": [0.1, 0.11, 0.12, 0.13, 0.14],
            "sp500_close": [4800, 4810, 4820, 4830, 4840],
        }
    )
    result = macro_analysis.compute_indicator_correlations(panel)
    assert not result.empty
    assert result.iloc[0]["indicator"] == "sp500_close"
    assert pytest.approx(result.iloc[0]["correlation"], rel=1e-5) == 1.0


def test_compute_lagged_correlations_positive_and_negative():
    panel = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=6, tz=UTC),
            "stx_btc": [0.1, 0.11, 0.12, 0.13, 0.14, 0.15],
            "usdt_supply": [1, 2, 3, 4, 5, 6],
        }
    )
    lag_df = macro_analysis.compute_lagged_correlations(
        panel, feature="usdt_supply", max_lag_days=2
    )
    corr_at_zero = lag_df.loc[lag_df["lag_days"] == 0, "correlation"].iloc[0]
    assert pytest.approx(corr_at_zero, rel=1e-5) == 1.0


def test_summarize_indicator_correlations_returns_labels():
    panel = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=10, tz=UTC),
            "stx_btc": pd.Series(range(10)).astype(float) / 100,
            "sp500_close": pd.Series(range(10)).astype(float) * 10,
            "vix_close": pd.Series(range(10)).astype(float)[::-1],
        }
    )
    summary = macro_analysis.summarize_indicator_correlations(panel)
    assert {"sp500_close", "vix_close"} <= set(summary["indicator"])
    assert "label" in summary.columns
    assert summary.loc[summary["indicator"] == "sp500_close", "label"].iloc[0] == "S&P 500 Close"
