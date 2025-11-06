from __future__ import annotations

import pandas as pd
import pytest

from src import cycle_utils


def test_map_burn_heights_to_cycles_basic():
    """Test basic cycle mapping with simple case."""
    df = pd.DataFrame({
        "burn_block_height": [100, 150, 200],
        "value": [1, 2, 3],
    })

    cycles = pd.DataFrame({
        "cycle_number": [1, 2],
        "block_height": [100, 200],
    })

    result = cycle_utils.map_burn_heights_to_cycles(df, cycles)

    # Check that cycle_number column was added
    assert "cycle_number" in result.columns

    # Heights 100 and 150 should be in cycle 1
    assert result.loc[0, "cycle_number"] == 1
    assert result.loc[1, "cycle_number"] == 1

    # Height 200 should be in cycle 2
    assert result.loc[2, "cycle_number"] == 2


def test_map_burn_heights_to_cycles_empty_cycles():
    """Test handling when no cycles are available."""
    df = pd.DataFrame({
        "burn_block_height": [100, 200, 300],
        "value": [1, 2, 3],
    })

    # Empty cycles DataFrame
    cycles = pd.DataFrame()

    result = cycle_utils.map_burn_heights_to_cycles(df, cycles)

    # Should add cycle_number column with NA values
    assert "cycle_number" in result.columns
    assert result["cycle_number"].isna().all()


def test_map_burn_heights_to_cycles_preserves_data():
    """Test that original columns and data are preserved."""
    df = pd.DataFrame({
        "burn_block_height": [100, 200],
        "value": [1, 2],
        "name": ["a", "b"],
    })

    cycles = pd.DataFrame({
        "cycle_number": [1],
        "block_height": [100],
    })

    result = cycle_utils.map_burn_heights_to_cycles(df, cycles)

    # Original columns should be preserved
    assert "burn_block_height" in result.columns
    assert "value" in result.columns
    assert "name" in result.columns

    # Original data should be unchanged
    assert result["value"].tolist() == [1, 2]
    assert result["name"].tolist() == ["a", "b"]

    # Original DataFrame should not be modified (copy returned)
    assert "cycle_number" not in df.columns


def test_map_burn_heights_to_cycles_multiple_cycles():
    """Test mapping across multiple cycles."""
    df = pd.DataFrame({
        "burn_block_height": [100, 150, 200, 250, 300, 350, 400],
    })

    cycles = pd.DataFrame({
        "cycle_number": [1, 2, 3],
        "block_height": [100, 200, 300],
    })

    result = cycle_utils.map_burn_heights_to_cycles(df, cycles)

    # Cycle 1: heights 100-199
    assert result.loc[0, "cycle_number"] == 1  # 100
    assert result.loc[1, "cycle_number"] == 1  # 150

    # Cycle 2: heights 200-299
    assert result.loc[2, "cycle_number"] == 2  # 200
    assert result.loc[3, "cycle_number"] == 2  # 250

    # Cycle 3: heights 300+ (last cycle extends indefinitely)
    assert result.loc[4, "cycle_number"] == 3  # 300
    assert result.loc[5, "cycle_number"] == 3  # 350
    assert result.loc[6, "cycle_number"] == 3  # 400


def test_map_burn_heights_to_cycles_custom_height_column():
    """Test using a custom height column name."""
    df = pd.DataFrame({
        "custom_height": [100, 200, 300],
        "value": [1, 2, 3],
    })

    cycles = pd.DataFrame({
        "cycle_number": [1, 2],
        "block_height": [100, 250],
    })

    result = cycle_utils.map_burn_heights_to_cycles(
        df, cycles, height_column="custom_height"
    )

    # Should use custom_height column
    assert result.loc[0, "cycle_number"] == 1  # 100
    assert result.loc[1, "cycle_number"] == 1  # 200
    assert result.loc[2, "cycle_number"] == 2  # 300


def test_map_burn_heights_to_cycles_missing_height_column():
    """Test error handling when height column is missing."""
    df = pd.DataFrame({
        "value": [1, 2, 3],
    })

    cycles = pd.DataFrame({
        "cycle_number": [1],
        "block_height": [100],
    })

    with pytest.raises(ValueError, match="missing required column"):
        cycle_utils.map_burn_heights_to_cycles(df, cycles)


def test_map_burn_heights_to_cycles_empty_dataframe():
    """Test handling when input DataFrame is empty."""
    df = pd.DataFrame(columns=["burn_block_height"])

    cycles = pd.DataFrame({
        "cycle_number": [1, 2],
        "block_height": [100, 200],
    })

    result = cycle_utils.map_burn_heights_to_cycles(df, cycles)

    # Should return empty DataFrame with cycle_number column
    assert len(result) == 0
    assert "cycle_number" in result.columns


def test_map_burn_heights_to_cycles_boundary_heights():
    """Test that cycle boundaries are handled correctly."""
    df = pd.DataFrame({
        "burn_block_height": [99, 100, 199, 200, 201],
    })

    cycles = pd.DataFrame({
        "cycle_number": [1, 2],
        "block_height": [100, 200],
    })

    result = cycle_utils.map_burn_heights_to_cycles(df, cycles)

    # 99 is before cycle 1 starts - should be NA
    assert pd.isna(result.loc[0, "cycle_number"])

    # 100 is cycle 1 start - should be cycle 1
    assert result.loc[1, "cycle_number"] == 1

    # 199 is cycle 1 end - should be cycle 1
    assert result.loc[2, "cycle_number"] == 1

    # 200 is cycle 2 start - should be cycle 2
    assert result.loc[3, "cycle_number"] == 2

    # 201 is in cycle 2 - should be cycle 2
    assert result.loc[4, "cycle_number"] == 2


def test_map_burn_heights_to_cycles_unsorted_cycles():
    """Test that cycles DataFrame is sorted internally."""
    df = pd.DataFrame({
        "burn_block_height": [150, 250, 350],
    })

    # Cycles provided in reverse order
    cycles = pd.DataFrame({
        "cycle_number": [3, 2, 1],
        "block_height": [300, 200, 100],
    })

    result = cycle_utils.map_burn_heights_to_cycles(df, cycles)

    # Should still map correctly despite unsorted input
    assert result.loc[0, "cycle_number"] == 1  # 150 in cycle 1 (100-199)
    assert result.loc[1, "cycle_number"] == 2  # 250 in cycle 2 (200-299)
    assert result.loc[2, "cycle_number"] == 3  # 350 in cycle 3 (300+)
