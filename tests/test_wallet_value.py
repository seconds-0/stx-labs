from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from src import wallet_value


def _activity_fixture():
    # Two wallets A and B with activity on two days; constant fees
    return pd.DataFrame(
        {
            "tx_id": ["a1", "a2", "a3", "b1"],
            "address": ["A", "A", "A", "B"],
            "block_time": [
                pd.Timestamp("2025-03-01T10:00Z"),
                pd.Timestamp("2025-03-05T11:00Z"),
                pd.Timestamp("2025-03-20T12:00Z"),
                pd.Timestamp("2025-03-03T12:00Z"),
            ],
            "activity_date": [
                pd.Timestamp("2025-03-01T00:00Z"),
                pd.Timestamp("2025-03-05T00:00Z"),
                pd.Timestamp("2025-03-20T00:00Z"),
                pd.Timestamp("2025-03-03T00:00Z"),
            ],
            "fee_ustx": [
                600_000,
                500_000,
                400_000,
                1_000,
            ],  # A: 1.5 STX total; B: 0.001 STX
            "tx_type": [
                "contract_call",
                "contract_call",
                "token_transfer",
                "contract_call",
            ],
        }
    )


def _first_seen_fixture():
    return pd.DataFrame(
        {
            "address": ["A", "B"],
            "first_seen": [
                pd.Timestamp("2025-03-01T09:00Z"),
                pd.Timestamp("2025-03-03T12:00Z"),
            ],
        }
    )


def _price_panel_fixture():
    # Hourly STX/BTC ≈ 0.000015 for simplicity
    times = pd.date_range("2025-03-01", "2025-03-21", freq="1H", tz=UTC)
    return pd.DataFrame({"ts": times, "stx_btc": 0.000015})


def _price_panel_without_ratio():
    times = pd.date_range("2025-03-01", "2025-03-02", freq="1H", tz=UTC)
    return pd.DataFrame({
        "ts": times,
        "stx_usd": 2.0,
        "btc_usd": 60000.0,
    })


def test_compute_wallet_windows_basic():
    activity = _activity_fixture()
    first_seen = _first_seen_fixture()
    prices = _price_panel_fixture()

    windows = wallet_value.compute_wallet_windows(
        activity, first_seen, prices, windows=(30,)
    )

    # A has 3 tx within 30 days, 1.5 STX fee sum, NV=1.5 * 0.000015 BTC
    a_row = windows[(windows["address"] == "A") & (windows["window_days"] == 30)].iloc[
        0
    ]
    assert a_row["tx_count"] == 3
    assert abs(a_row["fee_stx_sum"] - 1.5) < 1e-9
    assert abs(a_row["nv_btc_sum"] - (1.5 * 0.000015)) < 1e-12

    # B has 1 tx, tiny fees
    b_row = windows[(windows["address"] == "B") & (windows["window_days"] == 30)].iloc[
        0
    ]
    assert b_row["tx_count"] == 1
    assert abs(b_row["fee_stx_sum"] - 0.001) < 1e-12


def test_classification_with_balance_lookup():
    activity = _activity_fixture()
    first_seen = _first_seen_fixture()
    prices = _price_panel_fixture()
    windows = wallet_value.compute_wallet_windows(
        activity, first_seen, prices, windows=(30,)
    )
    thresholds = wallet_value.ClassificationThresholds(
        funded_stx_min=10.0, active_min_tx_30d=3, value_min_fee_stx_30d=1.0
    )

    # Inject balances: A is funded (20 STX), B not funded (0.5 STX)
    balance_map = {"A": 20.0, "B": 0.5}
    classified = wallet_value.classify_wallets(
        first_seen=first_seen,
        activity=activity,
        windows_agg=windows,
        thresholds=thresholds,
        balance_lookup=balance_map,
    )

    a = classified[classified["address"] == "A"].iloc[0]
    b = classified[classified["address"] == "B"].iloc[0]

    assert bool(a.funded) is True
    assert bool(a.active_30d) is True
    assert bool(a.value_30d) is True

    assert bool(b.funded) is False
    assert bool(b.active_30d) is False
    assert bool(b.value_30d) is False


def test_compute_network_daily_and_kpis():
    activity = _activity_fixture()
    activity["fee_stx"] = activity["fee_ustx"] / wallet_value.MICROSTX_PER_STX
    activity["nv_btc"] = activity["fee_stx"] * 0.000015
    daily = wallet_value.compute_network_daily(activity)
    assert len(daily) == 4  # four unique dates
    assert int(daily["tx_count"].sum()) == 4

    first_seen = _first_seen_fixture()
    prices = _price_panel_fixture()
    windows = wallet_value.compute_wallet_windows(
        activity, first_seen, prices, windows=(30,)
    )
    cls = wallet_value.classify_wallets(
        first_seen=first_seen,
        activity=activity,
        windows_agg=windows,
        thresholds=wallet_value.ClassificationThresholds(),
        balance_lookup={"A": 20.0, "B": 0.5},
    )
    kpis = wallet_value.summarize_value_kpis(
        daily_activity=daily,
        windows_agg=windows,
        classification=cls,
        lookback_days=365,
    )
    assert kpis["funded_wallets"] == 1
    assert kpis["value_wallets"] == 1
    assert round(kpis["total_fee_stx"], 3) == 1.501


def test_compute_cpa_panel():
    activity = _activity_fixture()
    first_seen = _first_seen_fixture()
    prices = _price_panel_fixture()
    windows = wallet_value.compute_wallet_windows(
        activity, first_seen, prices, windows=(30,)
    )
    panel = wallet_value.compute_cpa_panel(
        windows, window_days=30, cpa_target_stx=0.5, min_wallets=1
    )
    assert not panel.empty
    assert "payback_multiple" in panel.columns
    assert panel["payback_multiple"].iloc[0] > 0


def test_compute_cpa_panel_invalid_inputs():
    activity = _activity_fixture()
    first_seen = _first_seen_fixture()
    prices = _price_panel_fixture()
    windows = wallet_value.compute_wallet_windows(
        activity, first_seen, prices, windows=(30,)
    )
    with pytest.raises(ValueError):
        wallet_value.compute_cpa_panel(windows, cpa_target_stx=0)
    with pytest.raises(ValueError):
        wallet_value.compute_cpa_panel(windows, window_days=0)


def test_summarize_window_stats():
    activity = _activity_fixture()
    first_seen = _first_seen_fixture()
    prices = _price_panel_fixture()
    windows = wallet_value.compute_wallet_windows(
        activity, first_seen, prices, windows=(30, 60)
    )
    stats30 = wallet_value.summarize_window_stats(windows, window_days=30)
    assert stats30["wallets"] == 2
    assert stats30["avg_waltv_stx"] > 0
    stats90 = wallet_value.summarize_window_stats(windows, window_days=90)
    assert stats90["wallets"] == 0


def test_compute_wallet_windows_active_flag():
    activity = pd.DataFrame(
            {
                "tx_id": ["late", "early"],
                "address": ["A", "B"],
                "block_time": [
                    pd.Timestamp("2025-02-20T00:00Z"),
                    pd.Timestamp("2025-01-05T00:00Z"),
                ],
                "activity_date": [
                    pd.Timestamp("2025-02-20T00:00Z"),
                    pd.Timestamp("2025-01-05T00:00Z"),
                ],
                "fee_ustx": [1_000_000, 1_000_000],
                "tx_type": ["contract_call", "contract_call"],
            }
        )
    first_seen = pd.DataFrame(
        {
            "address": ["A", "B"],
            "first_seen": [
                pd.Timestamp("2025-01-01T00:00Z"),
                pd.Timestamp("2025-01-01T00:00Z"),
            ],
        }
    )
    prices = _price_panel_fixture()
    windows = wallet_value.compute_wallet_windows(
        activity, first_seen, prices, windows=(60,)
    )
    late_row = windows[windows["address"] == "A"].iloc[0]
    early_row = windows[windows["address"] == "B"].iloc[0]
    assert bool(late_row["active_in_window"]) is True
    assert late_row["band_tx_count"] == late_row["tx_count"] == 1
    assert bool(early_row["active_in_window"]) is False
    assert early_row["band_tx_count"] == 0


def test_compute_cpa_panel_by_channel():
    activation_date = pd.Timestamp("2025-01-01T00:00Z", tz=UTC)
    windows_agg = pd.DataFrame(
        {
            "address": ["A", "B"],
            "activation_date": [activation_date, activation_date],
            "window_days": [180, 180],
            "tx_count": [1, 1],
            "fee_stx_sum": [10.0, 5.0],
            "nv_btc_sum": [0.0, 0.0],
            "band_tx_count": [1, 1],
            "active_in_window": [True, True],
        }
    )
    channel_map = pd.DataFrame(
        {
            "address": ["A", "B"],
            "activation_date": [activation_date, activation_date],
            "channel": ["ads", "organic"],
        }
    )
    panel = wallet_value.compute_cpa_panel_by_channel(
        windows_agg,
        channel_map,
        window_days=180,
        cac_by_channel={"ads": 5.0, "organic": 2.0},
        min_wallets=1,
    )
    assert set(panel["channel"]) == {"ads", "organic"}
    ads_row = panel[panel["channel"] == "ads"].iloc[0]
    assert pytest.approx(ads_row["payback_multiple"]) == 2.0


def test_compute_trailing_wallet_windows_and_summary():
    activity = _activity_fixture()
    prices = _price_panel_fixture()
    # Anchor trailing windows at 2025-03-21 (covers all fixture events)
    as_of = pd.Timestamp("2025-03-21T00:00Z")

    trailing = wallet_value.compute_trailing_wallet_windows(
        activity, prices, windows=(30, 60), as_of=as_of
    )
    # Should have rows for both wallets for 30d
    t30 = trailing[trailing["window_days"] == 30]
    assert set(t30["address"]) == {"A", "B"}

    # Wallet A: 3 tx totaling 1.5 STX fees in last 30 days
    a_row = t30[t30["address"] == "A"].iloc[0]
    assert a_row["tx_count"] == 3
    assert abs(a_row["fee_stx_sum"] - 1.5) < 1e-9

    # Wallet B: 1 tx totaling 0.001 STX
    b_row = t30[t30["address"] == "B"].iloc[0]
    assert b_row["tx_count"] == 1
    assert abs(b_row["fee_stx_sum"] - 0.001) < 1e-12

    # Summary for trailing 30d reflects averages across wallets
    stats = wallet_value.summarize_trailing_window_stats(trailing, window_days=30)
    assert stats["wallets"] == 2
    assert stats["avg_last_stx"] > 0


def test_trailing_handles_price_panel_without_stx_btc():
    activity = _activity_fixture()
    price_panel = _price_panel_without_ratio()
    as_of = pd.Timestamp("2025-03-02T00:00Z")

    trailing = wallet_value.compute_trailing_wallet_windows(
        activity, price_panel, windows=(1,), as_of=as_of
    )
    # No error and result may be empty (since window small) but should be DataFrame
    assert isinstance(trailing, pd.DataFrame)
