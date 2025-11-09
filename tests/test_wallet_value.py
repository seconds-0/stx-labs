from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

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
