from __future__ import annotations

from src import scenarios


def test_build_scenarios_outputs_expected_columns():
    cfg = scenarios.ScenarioConfig(
        fee_per_tx_stx=0.1,
        rho_candidates=(0.4, 0.5),
        coinbase_stx=1_000,
        reward_cycles_blocks=2,
        stacked_supply_stx=1_000_000,
    )
    df = scenarios.build_scenarios(
        uplift_rates=[0.1, 0.2],
        mean_fee_stx=50.0,
        mean_stx_btc=0.00002,
        config=cfg,
    )
    assert set(df.columns) == {
        "uplift",
        "reward_multiplier",
        "target_reward_stx",
        "delta_fee_stx",
        "delta_tx_count",
        "rho",
        "commit_sats",
        "cycle_commit_sats",
        "apy_shift_pct",
    }
    # Expect two uplifts * two rho candidates = 4 rows.
    assert len(df) == 4
    # Delta fee equals uplift * baseline reward (coinbase + fees).
    baseline = cfg.coinbase_stx + 50.0
    first_row = df.iloc[0]
    assert abs(first_row["delta_fee_stx"] - (baseline * 0.1)) < 1e-6
    # APY shift should scale with commit sats.
    assert (df.sort_values("commit_sats")["apy_shift_pct"].diff().dropna() >= 0).all()
