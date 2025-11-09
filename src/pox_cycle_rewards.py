"""Utilities to assemble PoX reward cycle aggregates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd

from . import config as cfg
from . import hiro


CSV_OUTPUT_PATH = cfg.OUT_DIR / "pox_cycle_rewards.csv"


@dataclass(frozen=True)
class CycleBoundary:
    cycle_number: int
    prepare_start_burn_height: int
    reward_start_burn_height: int
    reward_end_burn_height: int
    reward_phase_length: int


def calculate_cycle_boundary(
    *,
    cycle_number: int,
    base_burn_height: int,
    reward_cycle_length: int,
    prepare_phase_length: int,
    reward_phase_length: int,
) -> CycleBoundary:
    """Return the burn chain heights bounding a reward cycle."""
    prepare_start = base_burn_height + cycle_number * reward_cycle_length
    reward_start = prepare_start + prepare_phase_length
    reward_end = reward_start + reward_phase_length - 1
    return CycleBoundary(
        cycle_number=cycle_number,
        prepare_start_burn_height=prepare_start,
        reward_start_burn_height=reward_start,
        reward_end_burn_height=reward_end,
        reward_phase_length=reward_phase_length,
    )


def _load_burn_block_metadata(
    burn_heights: Iterable[int],
    *,
    force_refresh: bool = False,
) -> Dict[int, Dict[str, int | str]]:
    """Fetch metadata (burn + stacks height/time/hash) for burn heights."""
    metadata_df = hiro.collect_anchor_metadata(
        burn_heights, force_refresh=force_refresh
    )
    if metadata_df.empty:
        return {}
    return {
        int(row.burn_block_height): {
            "stacks_block_height": int(row.stacks_block_height),
            "stacks_block_hash": str(row.stacks_block_hash),
            "burn_block_time": int(row.burn_block_time),
            "burn_block_time_iso": str(row.burn_block_time_iso),
            "miner_txid": row.miner_txid,
            "burn_block_hash": row.burn_block_hash,
            "parent_index_block_hash": row.parent_index_block_hash,
        }
        for row in metadata_df.itertuples()
    }


def _fetch_cycle_inputs(
    *,
    min_cycle: int,
    force_refresh: bool = False,
) -> tuple[pd.DataFrame, Dict[str, int]]:
    cycles_df = hiro.list_pox_cycles(force_refresh=force_refresh)
    if cycles_df.empty:
        raise RuntimeError("No PoX cycles returned from Hiro API.")
    config_payload = hiro.fetch_pox_config(force_refresh=force_refresh)
    cycle_constants = {
        "first_burnchain_block_height": int(
            config_payload["first_burnchain_block_height"]
        ),
        "reward_cycle_length": int(config_payload["reward_cycle_length"]),
        "prepare_phase_block_length": int(config_payload["prepare_phase_block_length"]),
        "reward_phase_block_length": int(config_payload["reward_phase_block_length"]),
    }
    filtered = cycles_df[cycles_df["cycle_number"] >= min_cycle].copy()
    if filtered.empty:
        raise RuntimeError(
            f"No cycles at or above {min_cycle} present in Hiro response."
        )
    return filtered, cycle_constants


def build_cycle_rewards_dataframe(
    *,
    min_cycle: int = 89,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Assemble PoX cycle reward statistics."""
    cycles_df, constants = _fetch_cycle_inputs(
        min_cycle=min_cycle, force_refresh=force_refresh
    )

    base_burn_height = constants["first_burnchain_block_height"]
    reward_cycle_length = constants["reward_cycle_length"]
    prepare_phase_length = constants["prepare_phase_block_length"]
    reward_phase_length = constants["reward_phase_block_length"]

    boundaries: List[CycleBoundary] = [
        calculate_cycle_boundary(
            cycle_number=int(row.cycle_number),
            base_burn_height=base_burn_height,
            reward_cycle_length=reward_cycle_length,
            prepare_phase_length=prepare_phase_length,
            reward_phase_length=reward_phase_length,
        )
        for row in cycles_df.itertuples()
    ]

    if not boundaries:
        raise RuntimeError("Unable to derive PoX cycle boundaries.")

    required_burn_heights: set[int] = set()
    for boundary in boundaries:
        required_burn_heights.add(boundary.reward_start_burn_height)
        required_burn_heights.add(boundary.reward_end_burn_height)
        prev_height = boundary.reward_start_burn_height - 1
        if prev_height > 0:
            required_burn_heights.add(prev_height)

    burn_metadata = _load_burn_block_metadata(
        required_burn_heights, force_refresh=force_refresh
    )

    records: List[Dict[str, object]] = []
    for row in cycles_df.itertuples():
        boundary = next(
            b for b in boundaries if b.cycle_number == int(row.cycle_number)
        )
        start_meta = burn_metadata.get(boundary.reward_start_burn_height, {})
        end_meta = burn_metadata.get(boundary.reward_end_burn_height, {})
        prev_meta = burn_metadata.get(boundary.reward_start_burn_height - 1, {})

        record = {
            "cycle_number": int(row.cycle_number),
            "reward_start_burn_height": boundary.reward_start_burn_height,
            "reward_end_burn_height": boundary.reward_end_burn_height,
            "reward_start_burn_time_iso": start_meta.get("burn_block_time_iso"),
            "reward_end_burn_time_iso": end_meta.get("burn_block_time_iso"),
            "reward_end_burn_block_hash": end_meta.get("burn_block_hash"),
            "reward_end_stacks_block_height": end_meta.get("stacks_block_height"),
            "reward_end_stacks_block_hash": end_meta.get("stacks_block_hash"),
            "btc_reward_satoshis": pd.NA,
            "btc_reward_btc": pd.NA,
            "reward_slot_count": pd.NA,
            "total_weight": int(row.total_weight),
            "total_stacked_amount_ustx": int(row.total_stacked_amount),
            "total_signers": int(row.total_signers),
            # Placeholders for STX mining yields (requires richer miner reward data).
            "stx_total_reward_ustx": pd.NA,
            "stx_coinbase_ustx": pd.NA,
            "stx_fees_ustx": pd.NA,
        }

        if prev_meta:
            record["baseline_stacks_block_height"] = prev_meta.get(
                "stacks_block_height"
            )
        else:
            record["baseline_stacks_block_height"] = None

        records.append(record)

    df = pd.DataFrame(records).sort_values("cycle_number").reset_index(drop=True)
    return df


def write_cycle_rewards_csv(
    *,
    output_path: Path = CSV_OUTPUT_PATH,
    min_cycle: int = 89,
    force_refresh: bool = False,
) -> Path:
    df = build_cycle_rewards_dataframe(min_cycle=min_cycle, force_refresh=force_refresh)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return output_path


def main() -> None:
    target_path = write_cycle_rewards_csv()
    print(f"Wrote PoX cycle rewards dataset to {target_path}")


if __name__ == "__main__":
    main()
