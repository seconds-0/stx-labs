"""Tests for macro_data utilities."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pandas as pd
import pytest

from src.macro_data import (
    fetch_additional_indicators,
    fetch_interest_rates,
    fetch_sp500_data,
    fetch_stablecoin_supply,
    fetch_unemployment_data,
    fetch_volatility_data,
    load_macro_panel,
)


@pytest.fixture
def temp_cache_dir(tmp_path, monkeypatch):
    macro_dir = tmp_path / "cache" / "macro"
    macro_dir.mkdir(parents=True)
    monkeypatch.setattr("src.macro_data.MACRO_CACHE_DIR", macro_dir)
    return macro_dir


def _build_history(values: list[float]) -> pd.DataFrame:
    history = pd.DataFrame({"Close": values}, index=pd.date_range("2024-01-01", periods=len(values)))
    history.index.name = "Date"
    return history


def test_fetch_sp500_uses_cache(temp_cache_dir, monkeypatch):
    mock_history = _build_history([4500.0, 4550.0, 4525.0])

    mock_ticker = Mock()
    mock_ticker.history.return_value = mock_history

    with patch("yfinance.Ticker", return_value=mock_ticker):
        df1 = fetch_sp500_data("2024-01-01", "2024-01-03")
        assert len(df1) == 3
        assert list(df1.columns) == ["date", "sp500_close", "sp500_pct_change"]

        df2 = fetch_sp500_data("2024-01-01", "2024-01-03")
        pd.testing.assert_frame_equal(df1, df2)
        assert mock_ticker.history.call_count == 1


def test_fetch_unemployment_data(temp_cache_dir):
    mock_df = pd.DataFrame(
        {"UNRATE": [3.7, 3.8, 3.9]}, index=pd.date_range("2024-01-01", periods=3, freq="MS")
    )
    mock_df.index.name = "date"

    with patch("pandas_datareader.data.DataReader", return_value=mock_df):
        df = fetch_unemployment_data("2024-01-01", "2024-03-01")

    assert len(df) == 3
    assert df["unemployment_rate"].iloc[0] == 3.7


def test_fetch_interest_rates(temp_cache_dir):
    mock_dff = pd.DataFrame({"DFF": [5.25, 5.25]}, index=pd.date_range("2024-01-01", periods=2))
    mock_dff.index.name = "date"
    mock_dgs10 = pd.DataFrame({"DGS10": [4.0, 4.05]}, index=pd.date_range("2024-01-01", periods=2))
    mock_dgs10.index.name = "date"

    with patch("pandas_datareader.data.DataReader", side_effect=[mock_dff, mock_dgs10]):
        df = fetch_interest_rates("2024-01-01", "2024-01-02")

    assert set(df.columns) == {"date", "fed_funds_rate", "treasury_10y"}
    assert df["fed_funds_rate"].iloc[0] == 5.25
    assert df["treasury_10y"].iloc[1] == 4.05


def test_fetch_volatility_data(temp_cache_dir):
    mock_history = _build_history([13.5, 14.2, 13.8])
    mock_ticker = Mock()
    mock_ticker.history.return_value = mock_history

    with patch("yfinance.Ticker", return_value=mock_ticker):
        df = fetch_volatility_data("2024-01-01", "2024-01-03")

    assert list(df.columns) == ["date", "vix_close"]
    assert df["vix_close"].tolist() == [13.5, 14.2, 13.8]


def test_fetch_stablecoin_supply_computes_changes(temp_cache_dir, monkeypatch):
    mock_usdt_response = {
        "market_caps": [
            [1704067200000, 95_000_000_000],
            [1704153600000, 96_000_000_000],
            [1704240000000, 96_500_000_000],
        ],
        "prices": [
            [1704067200000, 1.0],
            [1704153600000, 1.0],
            [1704240000000, 1.0],
        ],
    }
    mock_usdc_response = {
        "market_caps": [
            [1704067200000, 24_000_000_000],
            [1704153600000, 24_200_000_000],
            [1704240000000, 24_100_000_000],
        ],
        "prices": [
            [1704067200000, 1.0],
            [1704153600000, 1.0],
            [1704240000000, 1.0],
        ],
    }

    def mock_request(options):
        if "tether" in options.url:
            return mock_usdt_response
        return mock_usdc_response

    with patch("src.macro_data.cached_json_request", side_effect=mock_request):
        df = fetch_stablecoin_supply("2024-01-01", "2024-01-03")

    assert len(df) == 3
    assert "usdt_supply" in df.columns
    assert "usdc_supply" in df.columns
    assert df["usdt_daily_change"].iloc[1] == pytest.approx(1_000_000_000)
    assert df["usdc_daily_change"].iloc[2] == pytest.approx(-100_000_000)


def test_load_macro_panel_merges_all_sources(temp_cache_dir):
    dates = pd.date_range("2024-01-01", periods=3).date

    with patch("src.macro_data.fetch_sp500_data") as mock_sp500, patch(
        "src.macro_data.fetch_unemployment_data"
    ) as mock_unemp, patch("src.macro_data.fetch_interest_rates") as mock_rates, patch(
        "src.macro_data.fetch_volatility_data"
    ) as mock_vix, patch(
        "src.macro_data.fetch_stablecoin_supply"
    ) as mock_stable, patch(
        "src.macro_data.fetch_additional_indicators"
    ) as mock_additional:
        mock_sp500.return_value = pd.DataFrame({"date": dates, "sp500_close": [4500, 4550, 4525]})
        mock_unemp.return_value = pd.DataFrame(
            {"date": dates, "unemployment_rate": [3.7, 3.7, 3.8]}
        )
        mock_rates.return_value = pd.DataFrame(
            {"date": dates, "fed_funds_rate": [5.25, 5.25, 5.25], "treasury_10y": [4.0, 4.0, 4.1]}
        )
        mock_vix.return_value = pd.DataFrame({"date": dates, "vix_close": [13.5, 14.2, 13.8]})
        mock_stable.return_value = pd.DataFrame(
            {"date": dates, "usdt_supply": [95e9, 96e9, 96.5e9], "usdc_supply": [24e9, 24.2e9, 24.1e9]}
        )
        mock_additional.return_value = pd.DataFrame(
            {"date": dates, "dxy_close": [102.5, 102.8, 102.3]}
        )

        panel = load_macro_panel("2024-01-01", "2024-01-03")

    expected_cols = {
        "date",
        "sp500_close",
        "unemployment_rate",
        "fed_funds_rate",
        "treasury_10y",
        "vix_close",
        "usdt_supply",
        "usdc_supply",
        "dxy_close",
    }
    assert expected_cols.issubset(panel.columns)
    assert len(panel) == 3


def test_force_refresh_bypasses_cache(temp_cache_dir):
    mock_history = _build_history([4500.0, 4550.0])
    mock_ticker = Mock()
    mock_ticker.history.return_value = mock_history

    with patch("yfinance.Ticker", return_value=mock_ticker):
        fetch_sp500_data("2024-01-01", "2024-01-02")
        fetch_sp500_data("2024-01-01", "2024-01-02", force_refresh=True)

    assert mock_ticker.history.call_count == 2
