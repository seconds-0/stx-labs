from src.pox_cycle_rewards import calculate_cycle_boundary


def test_calculate_cycle_boundary_basic() -> None:
    boundary = calculate_cycle_boundary(
        cycle_number=89,
        base_burn_height=666050,
        reward_cycle_length=2100,
        prepare_phase_length=100,
        reward_phase_length=2000,
    )
    assert boundary.prepare_start_burn_height == 666050 + 89 * 2100
    assert boundary.reward_start_burn_height == boundary.prepare_start_burn_height + 100
    assert boundary.reward_end_burn_height == boundary.reward_start_burn_height + 2000 - 1

