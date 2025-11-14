from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from src import dashboard_cache
from src import wallet_metrics


@pytest.fixture(autouse=True)
def isolate_paths(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(dashboard_cache, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(dashboard_cache, "META_PATH", cache_dir / "meta.json")
    monkeypatch.setattr(
        dashboard_cache,
        "WALLET_ACTIVITY_PATH",
        cache_dir / "wallet_activity.parquet",
    )
    monkeypatch.setattr(
        dashboard_cache,
        "WALLET_FIRST_SEEN_PATH",
        cache_dir / "wallet_first_seen.parquet",
    )
    monkeypatch.setattr(
        dashboard_cache,
        "WALLET_NEW_PATH",
        cache_dir / "wallet_new.parquet",
    )
    monkeypatch.setattr(
        dashboard_cache,
        "WALLET_ACTIVE_PATH",
        cache_dir / "wallet_active.parquet",
    )
    monkeypatch.setattr(
        dashboard_cache,
        "WALLET_RETENTION_PATH",
        cache_dir / "wallet_retention.parquet",
    )
    monkeypatch.setattr(
        dashboard_cache,
        "WALLET_RETENTION_ACTIVE_PATH",
        cache_dir / "wallet_retention_active.parquet",
    )
    monkeypatch.setattr(
        dashboard_cache,
        "WALLET_FEE_PATH",
        cache_dir / "wallet_fee.parquet",
    )
    monkeypatch.setattr(
        dashboard_cache,
        "ROI_WINDOWS_PATH",
        cache_dir / "roi_windows.parquet",
    )
    monkeypatch.setattr(
        dashboard_cache,
        "ROI_CLASSIFICATION_PATH",
        cache_dir / "roi_classification.parquet",
    )
    monkeypatch.setattr(wallet_metrics, "FUNDED_D0_CACHE_PATH", cache_dir / "funded.parquet")
    monkeypatch.setattr(wallet_metrics, "SEGMENTED_RETENTION_PATH", cache_dir / "segmented.parquet")
    monkeypatch.setattr(
        wallet_metrics,
        "SEGMENTED_RETENTION_SURVIVAL_PATH",
        cache_dir / "segmented_survival.parquet",
    )
    yield


def _fake_activity() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "tx_id": ["t1"],
            "address": ["A"],
            "block_time": [pd.Timestamp("2025-01-01T00:00:00Z")],
            "activity_date": [pd.Timestamp("2025-01-01T00:00:00Z")],
            "fee_ustx": [1_000_000],
            "tx_type": ["token_transfer"],
        }
    )


def _fake_first_seen() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "address": ["A"],
            "first_seen": [pd.Timestamp("2025-01-01T00:00:00Z")],
        }
    )


def test_refresh_and_load_dashboard_cache(monkeypatch):
    activity = _fake_activity()
    first_seen = _fake_first_seen()
    new_wallets = pd.DataFrame({"activation_date": [pd.Timestamp("2025-01-01")], "new_wallets": [1]})
    active_wallets = pd.DataFrame({"activity_date": [pd.Timestamp("2025-01-01")], "active_wallets": [1]})
    retention_cumulative = pd.DataFrame(
        {
            "activation_date": [pd.Timestamp("2025-01-01")],
            "window_days": [15],
            "cohort_size": [1],
            "retained_wallets": [1],
            "retention_rate": [1.0],
        }
    )
    retention_active = retention_cumulative.copy()
    retention_active["retention_rate"] = [0.5]
    fee_per_wallet = pd.DataFrame(
        {
            "activation_date": [pd.Timestamp("2025-01-01")],
            "window_days": [15],
            "avg_fee_stx": [1.0],
            "wallets_observed": [1],
        }
    )
    windows_agg = pd.DataFrame(
        {
            "address": ["A"],
            "activation_date": [pd.Timestamp("2025-01-01")],
            "window_days": [15],
            "tx_count": [1],
            "fee_stx_sum": [1.0],
            "nv_btc_sum": [0.0],
            "band_tx_count": [1],
            "active_in_window": [True],
        }
    )
    classification = pd.DataFrame(
        {
            "address": ["A"],
            "activation_date": [pd.Timestamp("2025-01-01")],
            "funded": [True],
            "active_30d": [True],
            "value_30d": [True],
        }
    )
    funded_activation = pd.DataFrame(
        {
            "address": ["A"],
            "activation_date": [pd.Timestamp("2025-01-01")],
            "funded_d0": [True],
            "has_snapshot": [True],
        }
    )
    segmented = pd.DataFrame(
        {
            "window_days": [15],
            "segment": ["All"],
            "retained_users": [1],
            "eligible_users": [1],
            "retention_pct": [100.0],
            "anchor_window_days": [15],
            "updated_at": [pd.Timestamp("2025-01-02T00:00:00Z")],
        }
    )

    monkeypatch.setattr(
        dashboard_cache.wallet_metrics,
        "ensure_transaction_history",
        lambda **_: None,
    )
    monkeypatch.setattr(
        dashboard_cache.wallet_metrics,
        "load_recent_wallet_activity",
        lambda **_: activity,
    )
    monkeypatch.setattr(
        dashboard_cache.wallet_metrics,
        "update_first_seen_cache",
        lambda *_: first_seen,
    )
    monkeypatch.setattr(
        dashboard_cache.wallet_metrics,
        "compute_new_wallets",
        lambda *_, **__: new_wallets,
    )
    monkeypatch.setattr(
        dashboard_cache.wallet_metrics,
        "compute_active_wallets",
        lambda *_, **__: active_wallets,
    )

    def _fake_retention(*_, mode="cumulative", **__):
        return retention_cumulative if mode == "cumulative" else retention_active

    monkeypatch.setattr(
        dashboard_cache.wallet_metrics,
        "compute_retention",
        _fake_retention,
    )
    monkeypatch.setattr(
        dashboard_cache.wallet_metrics,
        "compute_fee_per_wallet",
        lambda *_, **__: fee_per_wallet,
    )
    monkeypatch.setattr(
        dashboard_cache.wallet_value,
        "load_price_panel_for_activity",
        lambda *_, **__: pd.DataFrame({"date": [pd.Timestamp("2025-01-01")], "price": [1.0]}),
    )
    monkeypatch.setattr(
        dashboard_cache.wallet_value,
        "compute_wallet_windows",
        lambda *_, **__: windows_agg,
    )
    monkeypatch.setattr(
        dashboard_cache.wallet_value,
        "classify_wallets",
        lambda *_, **__: classification,
    )
    monkeypatch.setattr(
        dashboard_cache.wallet_value,
        "compute_activation",
        lambda first_seen: pd.DataFrame(
            {"address": first_seen["address"], "activation_time": first_seen["first_seen"]}
        ),
    )
    monkeypatch.setattr(
        dashboard_cache.wallet_metrics,
        "ensure_wallet_balances",
        lambda *_, **__: 0,
    )
    monkeypatch.setattr(
        dashboard_cache.wallet_metrics,
        "ensure_activation_day_funded_snapshots",
        lambda *_, **__: 0,
    )
    monkeypatch.setattr(
        dashboard_cache.wallet_metrics,
        "collect_activation_day_funding",
        lambda *_, **__: funded_activation,
    )
    monkeypatch.setattr(
        dashboard_cache.wallet_metrics,
        "compute_value_flags",
        lambda *_, **__: pd.DataFrame(
            {"address": ["A"], "activation_date": [pd.Timestamp("2025-01-01")], "value_30d": [True]}
        ),
    )

    def _fake_segmented(*_, mode="cumulative", persist_path=None, **__):
        _ = mode
        target = persist_path or wallet_metrics.SEGMENTED_RETENTION_PATH
        wallet_metrics.write_parquet(target, segmented)
        return segmented

    monkeypatch.setattr(
        dashboard_cache.wallet_metrics,
        "compute_segmented_retention_panel",
        _fake_segmented,
    )

    meta = dashboard_cache.refresh_dashboard_cache(
        max_days=120,
        wallet_windows=[15],
        roi_windows=[15],
    )
    assert isinstance(meta.generated_at, datetime)
    assert meta.max_days == 120

    bundle, retention_active_loaded = dashboard_cache.load_wallet_bundle_from_cache()
    assert bundle is not None
    assert not retention_active_loaded.empty
    assert bundle.retention.equals(retention_cumulative)
    assert bundle.new_wallets.equals(new_wallets)

    roi_inputs = dashboard_cache.load_roi_inputs_from_cache()
    assert roi_inputs is not None
    assert not roi_inputs.retention_segmented.empty
    assert not roi_inputs.retention_segmented_cumulative.empty
    assert roi_inputs.windows_agg.equals(windows_agg)
