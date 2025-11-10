from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from src import wallet_metrics


def _build_test_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "wallet_metrics_test.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE transactions (
                tx_id VARCHAR PRIMARY KEY,
                block_time TIMESTAMP,
                block_height BIGINT,
                sender_address VARCHAR,
                fee_ustx BIGINT,
                tx_type VARCHAR,
                canonical BOOLEAN,
                tx_status VARCHAR,
                burn_block_time TIMESTAMP,
                burn_block_height BIGINT,
                microblock_sequence BIGINT,
                ingested_at TIMESTAMP
            );
            """
        )
        conn.execute(
            """
            INSERT INTO transactions VALUES
            ('tx1', '2025-01-01 00:00:00', 1, 'STXABC', 1000, 'token_transfer', TRUE, 'success', NULL, NULL, NULL, '2025-01-01 00:00:00');
            """
        )
    finally:
        conn.close()
    return db_path


def test_load_recent_wallet_activity_with_custom_db(tmp_path: Path) -> None:
    db_path = _build_test_db(tmp_path)

    df = wallet_metrics.load_recent_wallet_activity(max_days=365, db_path=db_path)

    assert len(df) == 1
    assert df.loc[0, "address"] == "STXABC"
    assert pd.api.types.is_datetime64tz_dtype(df["block_time"])  # still tz-aware


def test_create_db_snapshot(monkeypatch, tmp_path: Path) -> None:
    source = _build_test_db(tmp_path)
    dest = tmp_path / "snapshot.duckdb"

    monkeypatch.setattr(wallet_metrics, "DUCKDB_PATH", source)

    snapshot_path = wallet_metrics.create_db_snapshot(destination=dest)

    assert snapshot_path == dest
    assert snapshot_path.exists()
    assert snapshot_path.stat().st_size == source.stat().st_size
