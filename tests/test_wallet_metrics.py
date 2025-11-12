from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from src import config as cfg
from src import wallet_metrics


@pytest.fixture(autouse=True)
def patch_now(monkeypatch):
    fixed_now = datetime(2025, 4, 1, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(wallet_metrics, "_utc_now", lambda: fixed_now)
    return fixed_now


def test_load_recent_wallet_activity_filters_transactions(monkeypatch, tmp_path):
    base_time = datetime(2025, 4, 1, 12, 0, tzinfo=UTC)
    cutoff_time = int((base_time - timedelta(days=8)).timestamp())

    latest_page = {
        "results": [
            {
                "tx_id": "tx-new",
                "block_time": int(base_time.timestamp()),
                "canonical": True,
                "tx_status": "success",
                "sender_address": "SP111",
                "fee_rate": 1200,
                "tx_type": "contract_call",
            },
            {
                "tx_id": "tx-old",
                "block_time": cutoff_time - 100,
                "canonical": True,
                "tx_status": "success",
                "sender_address": "SP222",
                "fee_rate": 500,
                "tx_type": "token_transfer",
            },
            {
                "tx_id": "tx-failed",
                "block_time": int(base_time.timestamp()),
                "canonical": True,
                "tx_status": "abort_by_response",
                "sender_address": "SP333",
                "fee_rate": 900,
                "tx_type": "contract_call",
            },
        ],
        "limit": 3,
        "offset": 0,
        "total": 3,
    }

    def fake_fetch_transactions_page(**kwargs):
        if kwargs.get("end_time") is None:
            return latest_page
        return {"results": [], "limit": 0, "offset": 0, "total": 0}

    db_path = tmp_path / "wallet.duckdb"
    monkeypatch.setattr(wallet_metrics, "DUCKDB_PATH", db_path)
    monkeypatch.setattr(cfg, "DUCKDB_PATH", db_path)
    monkeypatch.setattr(
        wallet_metrics, "fetch_transactions_page", fake_fetch_transactions_page
    )
    monkeypatch.setattr(
        wallet_metrics, "FIRST_SEEN_CACHE_PATH", tmp_path / "first_seen.parquet"
    )

    wallet_metrics.ensure_transaction_history(
        max_days=7, force_refresh=True, max_pages=5
    )
    activity = wallet_metrics.load_recent_wallet_activity(max_days=7)

    assert list(activity["tx_id"]) == ["tx-new"]
    assert activity.iloc[0]["address"] == "SP111"
    assert activity.iloc[0]["fee_ustx"] == 1200
    assert str(activity.iloc[0]["activity_date"].tz) == "UTC"


def test_compute_new_and_active_wallets(tmp_path):
    with pytest.MonkeyPatch.context() as m:
        m.setattr(
            wallet_metrics, "FIRST_SEEN_CACHE_PATH", tmp_path / "first_seen.parquet"
        )

        activity = pd.DataFrame(
            {
                "tx_id": ["t1", "t2", "t3"],
                "address": ["A", "A", "B"],
                "block_time": [
                    pd.Timestamp("2025-03-01T10:00Z"),
                    pd.Timestamp("2025-03-05T10:00Z"),
                    pd.Timestamp("2025-03-05T15:00Z"),
                ],
                "activity_date": [
                    pd.Timestamp("2025-03-01T00:00Z"),
                    pd.Timestamp("2025-03-05T00:00Z"),
                    pd.Timestamp("2025-03-05T00:00Z"),
                ],
                "fee_ustx": [1000, 2000, 1500],
                "tx_type": ["contract_call", "contract_call", "token_transfer"],
            }
        )
        first_seen = wallet_metrics.update_first_seen_cache(activity)
        start_ts = pd.Timestamp("2025-02-20T00:00Z")

        new_wallets = wallet_metrics.compute_new_wallets(first_seen, start_ts)
        active_wallets = wallet_metrics.compute_active_wallets(activity, start_ts)

        assert new_wallets.set_index("activation_date")["new_wallets"].to_dict() == {
            pd.Timestamp("2025-03-01T00:00Z"): 1,
            pd.Timestamp("2025-03-05T00:00Z"): 1,
        }
        assert active_wallets.set_index("activity_date")[
            "active_wallets"
        ].to_dict() == {
            pd.Timestamp("2025-03-01T00:00Z"): 1,
            pd.Timestamp("2025-03-05T00:00Z"): 2,
        }


def test_retention_and_fee_metrics(tmp_path):
    with pytest.MonkeyPatch.context() as m:
        m.setattr(
            wallet_metrics, "FIRST_SEEN_CACHE_PATH", tmp_path / "first_seen.parquet"
        )

        activity = pd.DataFrame(
            {
                "tx_id": ["a0", "a1", "a2", "b0", "b1", "c0", "c1"],
                "address": ["A", "A", "A", "B", "B", "C", "C"],
                "block_time": [
                    pd.Timestamp("2025-01-01T10:00Z"),
                    pd.Timestamp("2025-01-10T12:00Z"),
                    pd.Timestamp("2025-02-05T12:00Z"),
                    pd.Timestamp("2025-02-15T12:00Z"),
                    pd.Timestamp("2025-03-10T12:00Z"),
                    pd.Timestamp("2025-03-15T09:00Z"),
                    pd.Timestamp("2025-03-28T09:00Z"),
                ],
                "activity_date": [
                    pd.Timestamp("2025-01-01T00:00Z"),
                    pd.Timestamp("2025-01-10T00:00Z"),
                    pd.Timestamp("2025-02-05T00:00Z"),
                    pd.Timestamp("2025-02-15T00:00Z"),
                    pd.Timestamp("2025-03-10T00:00Z"),
                    pd.Timestamp("2025-03-15T00:00Z"),
                    pd.Timestamp("2025-03-28T00:00Z"),
                ],
                "fee_ustx": [1000, 2000, 3000, 1500, 2500, 500, 700],
                "tx_type": ["contract_call"] * 7,
            }
        )

        first_seen = pd.DataFrame(
            {
                "address": ["A", "B", "C"],
                "first_seen": [
                    pd.Timestamp("2025-01-01T10:00Z"),
                    pd.Timestamp("2025-02-15T12:00Z"),
                    pd.Timestamp("2025-03-15T09:00Z"),
                ],
            }
        )

        windows = (15, 30, 60)
        today = pd.Timestamp("2025-04-01T00:00Z")

        retention = wallet_metrics.compute_retention(
            activity, first_seen, windows, today=today
        )
        fee_stats = wallet_metrics.compute_fee_per_wallet(
            activity, first_seen, windows, today=today
        )

        retention_keyed = {
            (row.activation_date, row.window_days): row.retention_rate
            for row in retention.itertuples()
        }

        assert retention_keyed[(pd.Timestamp("2025-01-01T00:00Z"), 15)] == 1.0
        assert retention_keyed[(pd.Timestamp("2025-02-15T00:00Z"), 15)] == 0.0
        assert retention_keyed[(pd.Timestamp("2025-03-15T00:00Z"), 15)] == 1.0
        assert retention_keyed[(pd.Timestamp("2025-01-01T00:00Z"), 30)] == 1.0
        assert retention_keyed[(pd.Timestamp("2025-02-15T00:00Z"), 30)] == 1.0
        assert retention_keyed[(pd.Timestamp("2025-01-01T00:00Z"), 60)] == 1.0

        fee_lookup = {
            (row.activation_date, row.window_days): row.avg_fee_stx
            for row in fee_stats.itertuples()
        }
        # Fees summed within window then normalised to STX (micro stx / 1e6)
        assert (
            pytest.approx(fee_lookup[(pd.Timestamp("2025-01-01T00:00Z"), 30)], rel=1e-6)
            == (1000 + 2000) / 1_000_000
        )
        assert (
            pytest.approx(fee_lookup[(pd.Timestamp("2025-02-15T00:00Z"), 30)], rel=1e-6)
            == (1500 + 2500) / 1_000_000
        )


def test_retention_active_band(tmp_path):
    with pytest.MonkeyPatch.context() as m:
        m.setattr(
            wallet_metrics, "FIRST_SEEN_CACHE_PATH", tmp_path / "first_seen.parquet"
        )

        activation_date = pd.Timestamp("2025-01-01T00:00Z")
        activity = pd.DataFrame(
                {
                    "tx_id": ["x0", "x1", "x2", "y0", "y1"],
                    "address": ["X", "X", "X", "Y", "Y"],
                    "block_time": [
                        activation_date,
                        activation_date + pd.Timedelta(days=5),
                        activation_date + pd.Timedelta(days=50),
                        activation_date,
                        activation_date + pd.Timedelta(days=10),
                    ],
                    "activity_date": [
                        activation_date,
                        activation_date + pd.Timedelta(days=5),
                        activation_date + pd.Timedelta(days=50),
                        activation_date,
                        activation_date + pd.Timedelta(days=10),
                    ],
                    "fee_ustx": [1000, 1000, 1000, 1000, 1000],
                    "tx_type": ["contract_call"] * 5,
                }
            )
        first_seen = pd.DataFrame(
            {
                "address": ["X", "Y"],
                "first_seen": [
                    activation_date,
                    activation_date,
                ],
            }
        )

        windows = (60,)
        today = pd.Timestamp("2025-04-01T00:00Z")
        retention_default = wallet_metrics.compute_retention(
            activity, first_seen, windows, today=today
        )
        retention_active = wallet_metrics.compute_retention(
            activity,
            first_seen,
            windows,
            today=today,
            mode="active_band",
        )
        default_rate = retention_default.iloc[0]["retention_rate"]
        active_rate = retention_active.iloc[0]["retention_rate"]
        assert pytest.approx(default_rate) == 1.0
        assert pytest.approx(active_rate) == 0.5
