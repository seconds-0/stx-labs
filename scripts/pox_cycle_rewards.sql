\echo Generating PoX cycle reward summary …

-- ---------------------------------------------------------------------------
-- Overview
-- ---------------------------------------------------------------------------
-- This script produces one row per PoX reward cycle (>= cycle 89). It assembles:
--   • Cycle boundary burn heights (prepare start, reward start/end)
--   • Reward window burn timestamps and terminal Stacks block metadata
--   • Total BTC rewards (satoshis + slot count) from burnchain_rewards
--   • STX miner rewards split (coinbase mint vs. fees) from miner_rewards
--
-- The script is intentionally verbose with CTEs + comments for auditability.
-- It assumes the Hiro mainnet database schema with canonical flags on all tables.
--
-- IMPORTANT: If Hiro adjusts PoX parameters, update the constants CTE.
--

\copy (
    WITH
    -- -----------------------------------------------------------------------
    -- Constant PoX parameters (PoX-4 mainnet).
    -- first_burnchain_height: burn height where PoX version became active.
    -- reward_cycle_len: total burn blocks per cycle (prepare + reward phases).
    -- prepare_len: burn blocks allocated to the prepare phase.
    -- reward_len: burn blocks allocated to the reward phase.
    -- -----------------------------------------------------------------------
    const AS (
        SELECT
            666050::bigint AS first_burnchain_height,
            2100::bigint AS reward_cycle_len,
            100::bigint AS prepare_len,
            2000::bigint AS reward_len
    ),

    -- -----------------------------------------------------------------------
    -- PoX cycle metadata and derived burn-chain boundaries.
    -- pox_cycles.block_height is the Stacks block height that anchors the cycle.
    -- We derive:
    --   prepare_start_burn_height = base + cycle_number * cycle_len
    --   reward_start_burn_height = prepare_start + prepare_len
    --   reward_end_burn_height   = reward_start + reward_len - 1
    -- -----------------------------------------------------------------------
    cycle_bounds AS (
        SELECT
            c.cycle_number,
            c.block_height      AS reward_end_stacks_block_height,
            c.index_block_hash  AS reward_end_index_block_hash,
            const.first_burnchain_height + c.cycle_number * const.reward_cycle_len AS prepare_start_burn_height,
            const.first_burnchain_height + c.cycle_number * const.reward_cycle_len + const.prepare_len AS reward_start_burn_height,
            const.first_burnchain_height + c.cycle_number * const.reward_cycle_len + const.prepare_len + const.reward_len - 1 AS reward_end_burn_height,
            c.total_weight,
            c.total_stacked_amount,
            c.total_signers
        FROM pox_cycles c
        CROSS JOIN const
    ),

    -- -----------------------------------------------------------------------
    -- Aggregate BTC rewards per cycle from burnchain_rewards.
    -- We restrict to canonical entries and the burn range for each cycle.
    -- -----------------------------------------------------------------------
    btc_rewards AS (
        SELECT
            cb.cycle_number,
            SUM(br.reward_amount) AS btc_reward_satoshis,
            COUNT(*)              AS reward_slot_count
        FROM cycle_bounds cb
        JOIN burnchain_rewards br
          ON br.canonical
         AND br.burn_block_height BETWEEN cb.reward_start_burn_height AND cb.reward_end_burn_height
        GROUP BY cb.cycle_number
    ),

    -- -----------------------------------------------------------------------
    -- Aggregate STX rewards per cycle from miner_rewards.
    -- All fields are uSTX (micro-STX). Fees include anchored and streamed fees.
    -- -----------------------------------------------------------------------
    stx_rewards AS (
        SELECT
            cb.cycle_number,
            SUM(mr.coinbase_amount) AS stx_coinbase_ustx,
            SUM(mr.tx_fees_anchored + mr.tx_fees_streamed_confirmed + mr.tx_fees_streamed_produced) AS stx_fees_ustx
        FROM cycle_bounds cb
        JOIN miner_rewards mr
          ON mr.canonical
         AND mr.mature_block_height BETWEEN cb.reward_start_burn_height AND cb.reward_end_burn_height
        GROUP BY cb.cycle_number
    ),

    -- -----------------------------------------------------------------------
    -- Pull reward window start/end burn timestamps from burn_blocks.
    -- If a burn height is missing (rare historical gaps), timestamps will be NULL.
    -- -----------------------------------------------------------------------
    burn_bounds AS (
        SELECT
            cb.cycle_number,
            b_start.burn_block_time AS reward_start_burn_time,
            b_end.burn_block_time   AS reward_end_burn_time
        FROM cycle_bounds cb
        LEFT JOIN burn_blocks b_start
               ON b_start.canonical
              AND b_start.burn_block_height = cb.reward_start_burn_height
        LEFT JOIN burn_blocks b_end
               ON b_end.canonical
              AND b_end.burn_block_height = cb.reward_end_burn_height
    )

    -- -----------------------------------------------------------------------
    -- Final projection with all metrics.
    -- -----------------------------------------------------------------------
    SELECT
        cb.cycle_number,
        cb.prepare_start_burn_height,
        cb.reward_start_burn_height,
        cb.reward_end_burn_height,
        burn_bounds.reward_start_burn_time,
        burn_bounds.reward_end_burn_time,
        cb.reward_end_stacks_block_height,
        cb.reward_end_index_block_hash,
        COALESCE(btc_rewards.btc_reward_satoshis, 0) AS btc_reward_satoshis,
        COALESCE(btc_rewards.btc_reward_satoshis, 0)::numeric / 1e8 AS btc_reward_btc,
        COALESCE(btc_rewards.reward_slot_count, 0) AS reward_slot_count,
        cb.total_weight,
        cb.total_stacked_amount,
        cb.total_signers,
        COALESCE(stx_rewards.stx_coinbase_ustx + stx_rewards.stx_fees_ustx, 0) AS stx_total_reward_ustx,
        COALESCE(stx_rewards.stx_coinbase_ustx, 0) AS stx_coinbase_ustx,
        COALESCE(stx_rewards.stx_fees_ustx, 0) AS stx_fees_ustx
    FROM cycle_bounds cb
    LEFT JOIN btc_rewards ON btc_rewards.cycle_number = cb.cycle_number
    LEFT JOIN stx_rewards ON stx_rewards.cycle_number = cb.cycle_number
    LEFT JOIN burn_bounds ON burn_bounds.cycle_number = cb.cycle_number
    WHERE cb.cycle_number >= 89
    ORDER BY cb.cycle_number
) TO STDOUT WITH CSV HEADER;
