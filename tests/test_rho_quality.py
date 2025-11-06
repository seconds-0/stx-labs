from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src import pox_constants as const

PANEL_PATH = Path("out/tenure_panel.parquet")
REWARDS_PATH = Path("out/pox_rewards.parquet")


def _load_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        pytest.skip(f"{path} not generated; run `make notebook` first.")
    return pd.read_parquet(path)


def test_panel_has_sufficient_valid_rho():
    panel = _load_parquet(PANEL_PATH)

    rho = panel["rho"]
    missing_mask = panel.get("rho_flag_missing", pd.Series(False, index=panel.index))
    div0_mask = panel.get("rho_flag_div0", pd.Series(False, index=panel.index))
    valid_mask = rho.notna() & (rho > 0) & (~missing_mask) & (~div0_mask)

    valid_pct = valid_mask.mean()
    assert valid_pct >= 0.85, f"Valid rho coverage too low: {valid_pct:.1%}"
    assert rho.loc[valid_mask].between(const.MIN_RHO, const.MAX_RHO).all()


def test_default_rho_matches_observed_median():
    panel = _load_parquet(PANEL_PATH)
    valid_rho = panel["rho"].dropna()
    if valid_rho.empty:
        pytest.skip("No valid rho observations available")

    observed_median = valid_rho[valid_rho > 0].median()
    pct_diff = abs(observed_median - const.DEFAULT_COMMITMENT_RATIO) / observed_median * 100
    assert pct_diff <= 15, (
        f"DEFAULT_COMMITMENT_RATIO {const.DEFAULT_COMMITMENT_RATIO} "
        f"differs {pct_diff:.1f}% from observed median {observed_median:.3f}"
    )


def test_rewards_cover_panel_range():
    panel = _load_parquet(PANEL_PATH)
    rewards = _load_parquet(REWARDS_PATH)

    panel_heights = set(panel["burn_block_height"])
    reward_heights = set(rewards["burn_block_height"])

    coverage = len(panel_heights & reward_heights) / len(panel_heights)
    assert coverage >= 0.85, f"Hiro rewards cover only {coverage:.1%} of panel burn heights"
