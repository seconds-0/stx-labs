"""Utilities for mapping burn block heights to PoX cycles."""

from __future__ import annotations

import pandas as pd


def map_burn_heights_to_cycles(
    df: pd.DataFrame,
    cycles_df: pd.DataFrame,
    height_column: str = "burn_block_height",
) -> pd.DataFrame:
    """Assign cycle_number to DataFrame based on burn block heights.

    Maps burn block heights to PoX cycles by determining cycle boundaries
    and assigning each row to the appropriate cycle.

    Args:
        df: DataFrame with burn block heights to map
        cycles_df: PoX cycles DataFrame (from hiro.list_pox_cycles)
                   Expected columns: cycle_number, block_height
        height_column: Name of the burn block height column in df

    Returns:
        Copy of df with cycle_number column added (pd.NA for unmapped rows)

    Example:
        >>> df = pd.DataFrame({'burn_block_height': [100, 150, 200]})
        >>> cycles = pd.DataFrame({
        ...     'cycle_number': [1, 2],
        ...     'block_height': [100, 200]
        ... })
        >>> result = map_burn_heights_to_cycles(df, cycles)
        >>> result['cycle_number'].tolist()
        [1, 1, 2]
    """
    if height_column not in df.columns:
        raise ValueError(f"DataFrame missing required column: {height_column}")

    # Handle empty cycles - return df with NA cycle_number
    if cycles_df.empty:
        result = df.copy()
        result["cycle_number"] = pd.NA
        return result

    # Sort cycles by block_height to determine boundaries
    cycles_sorted = cycles_df.sort_values("block_height").reset_index(drop=True)

    result = df.copy()
    result["cycle_number"] = pd.NA

    # Determine maximum height for last cycle boundary
    max_height = df[height_column].max() if len(df) > 0 else 0

    # Iterate through cycles and assign cycle_number based on height ranges
    for i, row in cycles_sorted.iterrows():
        start_height = int(row["block_height"])

        # Determine end height: next cycle's start (exclusive), or max + buffer if last cycle
        # Cycle ranges are [start, end) - inclusive of start, exclusive of end
        if i + 1 < len(cycles_sorted):
            end_height = int(cycles_sorted.iloc[i + 1]["block_height"])
        else:
            # For the most recent cycle, use a large buffer to catch all future blocks
            end_height = max_height + 1_000_000

        # Create mask for rows in this cycle's height range [start_height, end_height)
        mask = (result[height_column] >= start_height) & (
            result[height_column] < end_height
        )

        # Assign cycle_number to matching rows
        result.loc[mask, "cycle_number"] = int(row["cycle_number"])

    return result
