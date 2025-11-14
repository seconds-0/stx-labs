from __future__ import annotations

from datetime import UTC, datetime, timedelta, date

import duckdb
import pandas as pd
import pytest

from src import config as cfg
from src import wallet_metrics, wallet_value


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


def test_ensure_activation_day_funded_snapshots_scopes_recent(monkeypatch):
    first_seen = pd.DataFrame(
        {
            "address": ["A", "B", "C"],
            "first_seen": [
                pd.Timestamp("2025-03-28T12:00Z"),
                pd.Timestamp("2025-03-31T09:00Z"),
                pd.Timestamp("2025-04-01T02:00Z"),
            ],
        }
    )
    calls: list[tuple[tuple[str, ...], date]] = []

    def fake_ensure(addresses, **kwargs):
        calls.append((tuple(sorted(addresses)), kwargs["as_of_date"]))
        return len(addresses)

    monkeypatch.setattr(wallet_metrics, "ensure_wallet_balances", fake_ensure)
    inserted = wallet_metrics.ensure_activation_day_funded_snapshots(
        first_seen, lookback_days=2, batch_size=50, concurrency=4
    )
    assert inserted == 2
    assert calls == [
        (("B",), date(2025, 3, 31)),
        (("C",), date(2025, 4, 1)),
    ]


def test_compute_value_flags_thresholds():
    activity = pd.DataFrame(
        {
            "tx_id": ["a0", "a1", "b0"],
            "address": ["A", "A", "B"],
            "block_time": [
                pd.Timestamp("2025-01-01T12:00Z"),
                pd.Timestamp("2025-01-10T15:00Z"),
                pd.Timestamp("2025-01-02T08:00Z"),
            ],
            "activity_date": [
                pd.Timestamp("2025-01-01T00:00Z"),
                pd.Timestamp("2025-01-10T00:00Z"),
                pd.Timestamp("2025-01-02T00:00Z"),
            ],
            "fee_ustx": [500_000, 700_000, 100_000],
            "tx_type": ["token_transfer"] * 3,
        }
    )
    first_seen = pd.DataFrame(
        {
            "address": ["A", "B", "C"],
            "first_seen": [
                pd.Timestamp("2025-01-01T12:00Z"),
                pd.Timestamp("2025-01-02T08:00Z"),
                pd.Timestamp("2025-02-01T00:00Z"),
            ],
        }
    )
    flags = wallet_metrics.compute_value_flags(activity, first_seen)
    flag_map = {
        (row.address, row.activation_date): row.value_30d
        for row in flags.itertuples()
    }
    assert flag_map[( "A", pd.Timestamp("2025-01-01T00:00Z"))] is True
    assert flag_map[( "B", pd.Timestamp("2025-01-02T00:00Z"))] is False
    assert flag_map[( "C", pd.Timestamp("2025-02-01T00:00Z"))] is False


def test_segmented_retention_panel_filters_by_funding(monkeypatch, tmp_path):
    db_path = tmp_path / "wallets.duckdb"
    monkeypatch.setattr(wallet_metrics, "FUNDED_D0_CACHE_PATH", tmp_path / "funded.parquet")
    monkeypatch.setattr(
        wallet_metrics, "SEGMENTED_RETENTION_PATH", tmp_path / "segments.parquet"
    )

    activity = pd.DataFrame(
        {
            "tx_id": ["a0", "a1", "b0"],
            "address": ["A", "A", "B"],
            "block_time": [
                pd.Timestamp("2025-01-01T12:00Z"),
                pd.Timestamp("2025-01-10T09:00Z"),
                pd.Timestamp("2025-01-02T08:00Z"),
            ],
            "activity_date": [
                pd.Timestamp("2025-01-01T00:00Z"),
                pd.Timestamp("2025-01-10T00:00Z"),
                pd.Timestamp("2025-01-02T00:00Z"),
            ],
            "fee_ustx": [500_000, 700_000, 100_000],
            "tx_type": ["token_transfer"] * 3,
        }
    )
    first_seen = pd.DataFrame(
        {
            "address": ["A", "B", "C"],
            "first_seen": [
                pd.Timestamp("2025-01-01T12:00Z"),
                pd.Timestamp("2025-01-02T08:00Z"),
                pd.Timestamp("2025-03-15T10:00Z"),
            ],
        }
    )

    def fetcher(address: str) -> dict[str, dict[str, str]]:
        balance = 15.0 if address in {"A", "B"} else 0.0
        return {
            "stx": {
                "balance": str(int(balance * wallet_value.MICROSTX_PER_STX)),
            }
        }

    wallet_metrics.ensure_wallet_balances(
        ["A"],
        as_of_date=date(2025, 1, 1),
        funded_threshold_stx=10.0,
        fetcher=fetcher,
        db_path=db_path,
    )
    wallet_metrics.ensure_wallet_balances(
        ["B"],
        as_of_date=date(2025, 1, 2),
        funded_threshold_stx=10.0,
        fetcher=fetcher,
        db_path=db_path,
    )

    funded_activation = wallet_metrics.collect_activation_day_funding(
        first_seen, db_path=db_path, persist=True
    )
    value_flags = wallet_metrics.compute_value_flags(activity, first_seen)
    today = pd.Timestamp("2025-04-01T00:00Z")

    panel = wallet_metrics.compute_segmented_retention_panel(
        activity,
        first_seen,
        windows=(15, 30),
        funded_activation=funded_activation,
        value_flags=value_flags,
        today=today,
        persist=False,
        db_path=db_path,
    )
    assert not panel.empty
    lookup = {
        (row.segment, row.window_days): (row.retained_users, row.eligible_users, row.retention_pct)
        for row in panel.itertuples()
    }
    assert lookup[("All", 15)] == (1, 2, 50.0)
    assert lookup[("All", 30)] == (1, 2, 50.0)
    assert lookup[("Value", 15)] == (1, 1, 100.0)
    assert lookup[("Non-value", 15)] == (0, 1, 0.0)


def test_collect_activation_day_funding_uses_fallback(monkeypatch, tmp_path):
    db_primary = tmp_path / "primary.duckdb"
    snapshot_db = tmp_path / "snapshot.duckdb"
    monkeypatch.setattr(wallet_metrics, "FUNDED_D0_CACHE_PATH", tmp_path / "funded.parquet")

    first_seen = pd.DataFrame(
        {
            "address": ["A"],
            "first_seen": [pd.Timestamp("2025-01-01T12:00:00Z")],
        }
    )

    def fetcher(address: str) -> dict[str, dict[str, str]]:
        balance = 12.0 if address == "A" else 0.0
        return {
            "stx": {
                "balance": str(int(balance * wallet_value.MICROSTX_PER_STX)),
            }
        }

    wallet_metrics.ensure_wallet_balances(
        ["A"],
        as_of_date=date(2025, 1, 1),
        funded_threshold_stx=10.0,
        fetcher=fetcher,
        db_path=db_primary,
    )
    duckdb.connect(str(snapshot_db)).close()

    funded = wallet_metrics.collect_activation_day_funding(
        first_seen,
        db_path=snapshot_db,
        fallback_db_path=db_primary,
        persist=False,
    )
    assert not funded.empty
    row = funded.iloc[0]
    assert bool(row["funded_d0"]) is True
    assert bool(row["has_snapshot"]) is True
    assert pd.Timestamp(row["snapshot_version"]) == pd.Timestamp("2025-01-01T00:00:00Z")


def test_activation_frame_clamps_to_metrics_data_start():
    start = wallet_metrics.METRICS_DATA_START
    earlier = start - pd.Timedelta(days=10)
    later = start + pd.Timedelta(days=2)
    first_seen = pd.DataFrame(
        {
            "address": ["EARLY", "LATE"],
            "first_seen": [earlier, later],
        }
    )
    frame = wallet_metrics._activation_frame(first_seen)
    assert frame["address"].tolist() == ["LATE"]
    assert frame.iloc[0]["activation_date"] == later.floor("D")


def test_retention_drops_pre_coverage_cohorts():
    start = wallet_metrics.METRICS_DATA_START
    earlier = start - pd.Timedelta(days=5)
    later = start + pd.Timedelta(days=1)
    activity = pd.DataFrame(
        {
            "tx_id": ["old0", "old1", "new0", "new1"],
            "address": ["EARLY", "EARLY", "LATE", "LATE"],
            "block_time": [
                earlier,
                earlier + pd.Timedelta(days=1),
                later,
                later + pd.Timedelta(days=1),
            ],
            "activity_date": [
                earlier.floor("D"),
                (earlier + pd.Timedelta(days=1)).floor("D"),
                later.floor("D"),
                (later + pd.Timedelta(days=1)).floor("D"),
            ],
            "fee_ustx": [500_000, 500_000, 1_000_000, 2_000_000],
            "tx_type": ["contract_call"] * 4,
        }
    )
    first_seen = pd.DataFrame(
        {
            "address": ["EARLY", "LATE"],
            "first_seen": [earlier, later],
        }
    )
    retention = wallet_metrics.compute_retention(activity, first_seen, windows=(15,))
    assert not retention.empty
    assert retention["activation_date"].min() >= start.floor("D")
    assert retention["activation_date"].nunique() == 1


def test_segmented_retention_panel_uses_fixed_denominator():
    today = pd.Timestamp("2025-06-01T00:00Z")
    windows = (15, 60)
    first_seen = pd.DataFrame(
        {
            "address": ["OLD1", "OLD2", "NEW1"],
            "first_seen": [
                pd.Timestamp("2025-01-01T12:00Z"),
                pd.Timestamp("2025-01-05T08:00Z"),
                pd.Timestamp("2025-05-15T10:00Z"),
            ],
        }
    )
    activity = pd.DataFrame(
        {
            "tx_id": ["o1", "o2", "n1"],
            "address": ["OLD1", "OLD2", "NEW1"],
            "block_time": [
                pd.Timestamp("2025-01-10T00:00Z"),
                pd.Timestamp("2025-01-20T00:00Z"),
                pd.Timestamp("2025-05-20T00:00Z"),
            ],
            "activity_date": [
                pd.Timestamp("2025-01-10T00:00Z"),
                pd.Timestamp("2025-01-20T00:00Z"),
                pd.Timestamp("2025-05-20T00:00Z"),
            ],
            "fee_ustx": [1_000_000, 1_000_000, 1_000_000],
            "tx_type": ["contract_call"] * 3,
        }
    )
    funded_activation = pd.DataFrame(
        {
            "address": ["OLD1", "OLD2", "NEW1"],
            "activation_date": [
                pd.Timestamp("2025-01-01T00:00Z"),
                pd.Timestamp("2025-01-05T00:00Z"),
                pd.Timestamp("2025-05-15T00:00Z"),
            ],
            "funded_d0": [True, True, True],
            "balance_ustx": [15_000_000, 15_000_000, 15_000_000],
            "snapshot_version": [
                pd.Timestamp("2025-01-01T00:00Z"),
                pd.Timestamp("2025-01-05T00:00Z"),
                pd.Timestamp("2025-05-15T00:00Z"),
            ],
            "has_snapshot": [True, True, True],
            "ingested_at": [
                pd.Timestamp("2025-01-02T00:00Z"),
                pd.Timestamp("2025-01-06T00:00Z"),
                pd.Timestamp("2025-05-16T00:00Z"),
            ],
            "updated_at": [
                pd.Timestamp("2025-01-02T00:00Z"),
                pd.Timestamp("2025-01-06T00:00Z"),
                pd.Timestamp("2025-05-16T00:00Z"),
            ],
        }
    )
    value_flags = wallet_metrics.compute_value_flags(activity, first_seen, window_days=30)
    panel = wallet_metrics.compute_segmented_retention_panel(
        activity,
        first_seen,
        windows=windows,
        funded_activation=funded_activation,
        value_flags=value_flags,
        today=today,
        persist=False,
    )
    assert not panel.empty
    all_rows = panel[panel["segment"] == "All"].sort_values("window_days")
    assert all_rows["eligible_users"].tolist() == [2, 2]
    assert all_rows.iloc[0]["retention_pct"] >= all_rows.iloc[1]["retention_pct"]
