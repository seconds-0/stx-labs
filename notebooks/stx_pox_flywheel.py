#!/usr/bin/env python
# coding: utf-8

# # Stacks PoX Flywheel: Fees → Miner Rewards → BTC Bids → PoX Yields
# 
# This notebook reconstructs the Stacks Proof-of-Transfer (PoX) flywheel by joining fees, miner rewards, BTC bids, and stacker yields at the burn-block (tenure) level. It relies on the Signal21 public API for market and fee data and the Hiro Stacks API for burn chain metadata.
# 
# **Objectives**
# - Pull full-history STX/BTC prices, transaction fees, PoX rewards, and anchor metadata.
# - Construct a tenure-level panel with derived reward value and \(ho = rac{	ext{BTC commit}}{	ext{reward value}}\).
# - Quantify fee uplift scenarios (+10/25/50/100/200%) to estimate incremental BTC commits and PoX APY shifts.
# 
# **References**
# - [Signal21 API docs](https://app.signal21.io/docs/api.html)
# - [Signal21 API access](https://signal21.github.io/docs/extras/api-access.html)
# - [Hiro Stacks API reference](https://www.hiro.so/stacks-api)
# - [Stacks fee mechanics](https://docs.stacks.co/concepts/network-fundamentals/network)
# - [Stacks mempool fee endpoint](https://www.quicknode.com/docs/stacks/v2/extended-v2-mempool-fees)

# In[1]:


import os
from pathlib import Path
import subprocess
import sys

if "google.colab" in sys.modules:
    repo_path = Path('/content/stx-labs')
    if repo_path.exists():
        subprocess.run(['git', '-C', str(repo_path), 'reset', '--hard', 'origin/main'], check=True)
        subprocess.run(['git', '-C', str(repo_path), 'fetch', '--all'], check=True)
        subprocess.run(['git', '-C', str(repo_path), 'checkout', 'main'], check=True)
        subprocess.run(['git', '-C', str(repo_path), 'pull', '--ff-only'], check=True)
    else:
        subprocess.run(['git', 'clone', 'https://github.com/seconds-0/stx-labs.git', str(repo_path)], check=True)
    os.chdir(repo_path)
    subprocess.run(['pip', 'install', '--quiet', '-r', 'requirements.txt'], check=True)
    print('Colab environment ready: repo synced and dependencies installed.')
else:
    print('Running outside Colab; ensure you execute from the repo root.')


# ## 1. Configuration & Environment Checks
# 
# Edit the cell below to configure date windows, retry policy, and manual overrides. Set `HIRO_API_KEY` in your environment (or in the notebook UI) before running the data acquisition cells.

# In[ ]:


# Parameters
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd


def _find_project_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / 'src').is_dir():
            return candidate
    raise RuntimeError('Unable to locate project root containing a src/ directory.')


PROJECT_ROOT = _find_project_root(Path.cwd())
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from src import config as cfg  # noqa: E402

# -------- User Parameters -------- #
WINDOW_DAYS = (30, 90, 180)
HISTORY_DAYS = cfg.default_date_horizon_days()
CUSTOM_START_DATE = None  # set to datetime(YYYY, M, D, tzinfo=UTC) to override history days
END_DATE = datetime.now(UTC)
ANALYSIS_START = CUSTOM_START_DATE or (END_DATE - timedelta(days=HISTORY_DAYS))
FORCE_REFRESH = False  # force-refresh all caches when True
PRICE_SYMBOLS = ("STX-USD", "BTC-USD")

# Scenario assumptions
COINBASE_STX = 1_000.0
FEE_PER_TX_STX = 0.08
RHO_RANGE = (0.92, 1.04, 1.10)
UPLIFT_POINTS = (0.10, 0.25, 0.50, 1.00, 2.00)
REWARD_BLOCKS_PER_CYCLE = 2100

# Roadmap baseline window (use recent data for realistic current market conditions)
ROADMAP_WINDOW_DAYS = 90

RAW_PATH = cfg.RAW_DATA_DIR
CACHE_PATH = cfg.CACHE_DIR
OUT_PATH = cfg.OUT_DIR
for path in (RAW_PATH, CACHE_PATH, OUT_PATH):
    path.mkdir(parents=True, exist_ok=True)

HIRO_API_KEY = os.getenv(cfg.HIRO_API_KEY_ENV)
if not HIRO_API_KEY:
    print('⚠️ Set HIRO_API_KEY before running Hiro API calls.')


# ## 2. Imports & Helper Setup
# 
# The helper modules live in `src/` and encapsulate Signal21/Hiro API access, caching, and scenario math.

# In[3]:


import json
from collections import defaultdict

import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from src import hiro, panel_builder, prices, scenarios
from src import pox_constants as const
from src.fees import fetch_fee_per_tx_summary, fetch_fees_by_tenure
from src.signal21 import probe_schema

try:
    import ipywidgets as widgets
except ModuleNotFoundError:
    widgets = None
    print("⚠️ ipywidgets not installed; PoX rewards calculator disabled.")
from IPython.display import display, Markdown
from src.scenarios import summarize_miner_rewards
pd.options.display.float_format = "{:.6f}".format


# ## 3. Parameter Summary & Cache Status
# 

# In[4]:


print(f"Analysis window: {ANALYSIS_START:%Y-%m-%d %H:%M} → {END_DATE:%Y-%m-%d %H:%M} UTC")
print(f"History days: {HISTORY_DAYS} (custom start: {CUSTOM_START_DATE})")
print(f"Force refresh: {FORCE_REFRESH}")

from src.prices import cached_price_series
from src.cache_utils import read_parquet

for symbol in PRICE_SYMBOLS:
    cache_df = cached_price_series(symbol)
    if cache_df.empty:
        print(f"{symbol} cache: empty")
    else:
        print(
            f"{symbol} cache: {len(cache_df):,} rows "
            f"({cache_df['ts'].min():%Y-%m-%d} → {cache_df['ts'].max():%Y-%m-%d})"
        )

fees_cache = cfg.CACHE_DIR / 'signal21' / 'fees_by_tenure_all.parquet'
rewards_cache = cfg.CACHE_DIR / 'hiro' / 'rewards_all.parquet'
for label, path in [('Fees cache', fees_cache), ('Rewards cache', rewards_cache)]:
    exists = path.exists()
    msg = "exists" if exists else "missing"
    print(f"{label}: {msg} ({path})")



# ## 4. Schema Discovery (Signal21)
# 

# In[5]:


# Uncomment to inspect schema when needed
# tx_sample = probe_schema("core.txs")
# block_sample = probe_schema("core.blocks")
# display(tx_sample.head())
# display(block_sample.head())


# ## 4. Data Acquisition
# 
# This section ingests prices, fees, PoX rewards, and anchor metadata. Each request uses robust retry logic and caches raw payloads under `data/raw/`.

# In[ ]:


cache_before = {symbol: len(prices.cached_price_series(symbol)) for symbol in PRICE_SYMBOLS}
prices_df = prices.load_price_panel(ANALYSIS_START, END_DATE, force_refresh=FORCE_REFRESH)
cache_after = {symbol: len(prices.cached_price_series(symbol)) for symbol in PRICE_SYMBOLS}

for symbol in PRICE_SYMBOLS:
    before = cache_before[symbol]
    after = cache_after[symbol]
    delta = after - before
    print(f"{symbol}: {after:,} cached rows (Δ {delta:+,})")
print(
    f"Price panel rows: {len(prices_df):,} spanning "
    f"{prices_df['ts'].min()} → {prices_df['ts'].max()}"
)
prices_df.head()



# In[ ]:


fees_df = fetch_fees_by_tenure(force_refresh=FORCE_REFRESH)
if fees_df.empty:
    print("⚠️ No fee data returned.")
else:
    print(
        f"Fees rows: {len(fees_df):,} burn blocks "
        f"({fees_df['burn_block_height'].min()} → {fees_df['burn_block_height'].max()})"
    )
fees_df.head()



# In[ ]:


if fees_df.empty:
    rewards_df = pd.DataFrame()
else:
    min_height = int(fees_df['burn_block_height'].min())
    max_height = int(fees_df['burn_block_height'].max())
    rewards_df = hiro.aggregate_rewards_by_burn_block(
        start_height=min_height,
        end_height=max_height,
        force_refresh=FORCE_REFRESH,
    )
    print(
        f"Rewards rows: {len(rewards_df):,} burn blocks "
        f"({rewards_df['burn_block_height'].min()} → {rewards_df['burn_block_height'].max()})"
    )
rewards_df.head()



# In[ ]:


if fees_df.empty:
    anchor_df = pd.DataFrame()
else:
    anchor_df = hiro.collect_anchor_metadata(fees_df['burn_block_height'].astype(int), force_refresh=FORCE_REFRESH)
    print(f"Collected anchor metadata for {anchor_df.shape[0]} burn blocks")
anchor_df.head()


# In[ ]:


cycles_df = hiro.list_pox_cycles(force_refresh=FORCE_REFRESH)
print(f"Retrieved {cycles_df.shape[0]} PoX cycles")
cycles_df.head()


# ## 5. Tenure Panel Construction
# 
# Join all datasets on `burn_block_height`, align prices to anchor timestamps, and derive reward value and \(ho\).

# In[ ]:


if fees_df.empty or anchor_df.empty:
    panel_df = pd.DataFrame()
else:
    panel_cfg = panel_builder.PanelConfig(coinbase_stx=COINBASE_STX)
    panel_df = panel_builder.build_tenure_panel(
        fees=fees_df,
        rewards=rewards_df,
        anchors=anchor_df,
        prices=prices_df,
        config=panel_cfg,
    )
    panel_df = panel_builder.merge_cycle_metadata(panel_df, cycles_df)
    print(f"Panel contains {panel_df.shape[0]} tenures")
panel_df.head()


# ## 6. Validation Checks
# 
# Ensure we have consistent tenure coverage, expected coinbase value, and reasonable \(ho\) ranges.

# In[ ]:


if not panel_df.empty:
    missing_fees = panel_df['fees_stx_sum'].isna().sum()
    coinbase_anomalies = panel_df['coinbase_flag'].sum()
    rho_div_zero = panel_df['rho_flag_div0'].sum()
    print("Missing fee entries:", missing_fees)
    print("Coinbase anomalies:", coinbase_anomalies)
    print("Zero reward value entries:", rho_div_zero)

    expected_burns = panel_df['burn_block_height'].iloc[-1] - panel_df['burn_block_height'].iloc[0] + 1
    missing_burns = expected_burns - len(panel_df['burn_block_height'].unique())
    print("Missing burn heights:", missing_burns)

    sample = panel_df.sample(min(20, len(panel_df)))
    sample[['burn_block_height', 'fees_stx_sum', 'reward_amount_sats_sum', 'rho']]


# ## 7. Fee Analytics Per Window
# 
# Compute empirical fee-per-transaction statistics across rolling windows to benchmark against the 0.08 STX/tx baseline.

# In[ ]:


# SKIPPED: Fee analytics per window (Signal21 API rate limiting)
# Cell 23 temporarily disabled - see bd-21 for Hiro API migration plan
print("⏭️  Skipping fee analytics (Signal21 rate limits)")
print("   See docs/hiro_fee_migration_plan.md for migration to Hiro API")
fee_stats = {}
fee_summary_df = pd.DataFrame()


# ## 8. Scenario Engine
# 
# Estimate the incremental transactions, BTC commits, and PoX APY shifts for fee uplifts. `stacked_supply_stx` defaults to a rolling estimate when available, otherwise falls back to 1.35B STX.

# In[ ]:


if panel_df.empty:
    scenario_df = pd.DataFrame()
else:
    recent_panel = panel_df.tail(max(3_000, len(panel_df)))
    mean_fee_stx = recent_panel['fees_stx_sum'].median()
    mean_stx_btc = recent_panel['stx_btc'].mean()
    stacked_supply_estimate = (
        recent_panel['reward_stx_total'].rolling(REWARD_BLOCKS_PER_CYCLE).sum().dropna().iloc[-1]
        if len(recent_panel) >= REWARD_BLOCKS_PER_CYCLE
        else 1_350_000_000.0
    )
    scenario_cfg = scenarios.ScenarioConfig(
        fee_per_tx_stx=FEE_PER_TX_STX,
        rho_candidates=RHO_RANGE,
        coinbase_stx=COINBASE_STX,
        reward_cycles_blocks=REWARD_BLOCKS_PER_CYCLE,
        stacked_supply_stx=stacked_supply_estimate,
    )
    scenario_df = scenarios.build_scenarios(
        uplift_rates=UPLIFT_POINTS,
        mean_fee_stx=mean_fee_stx,
        mean_stx_btc=mean_stx_btc,
        config=scenario_cfg,
    )
    scenario_df


# ## 9. Coinbase Replacement Roadmap
# 
# This section shows **specific paths to replace the 1,000 STX coinbase** with fee revenue. For each target revenue increase, we calculate two pure strategies:
# - **Strategy A**: Fee multiplier needed (keeping transaction count constant)
# - **Strategy B**: Additional transactions needed (keeping fee/tx constant)

# In[ ]:


if panel_df.empty:
    roadmap_df = pd.DataFrame()
else:
    # Use last N days for realistic current market baseline
    cutoff_date = panel_df['burn_block_time_iso'].max() - pd.Timedelta(days=ROADMAP_WINDOW_DAYS)
    recent_panel = panel_df[panel_df['burn_block_time_iso'] >= cutoff_date]

    baseline_fees = recent_panel['fees_stx_sum'].median()
    baseline_txs = recent_panel['tx_count'].median()

    # Target increases: 100, 500, 1000 STX (1000 = full coinbase replacement)
    target_increases = [100, 500, 1000]

    roadmap_df = scenarios.build_replacement_roadmap(
        baseline_fees_stx=baseline_fees,
        baseline_tx_count=baseline_txs,
        coinbase_stx=COINBASE_STX,
        target_increases=target_increases,
    )

    print(f"Roadmap baseline: Last {ROADMAP_WINDOW_DAYS} days ({len(recent_panel)} tenures)")
    print(f"Baseline: {baseline_fees:.2f} STX fees/tenure, {baseline_txs:.0f} txs/tenure")
    print(f"Current total miner revenue: {COINBASE_STX + baseline_fees:.2f} STX/tenure")
    print(f"\nCoinbase Replacement Roadmap:\n")

    # Display roadmap with formatting
    display_df = roadmap_df.copy()
    display_df['target_increase_stx'] = display_df['target_increase_stx'].apply(lambda x: f"{x:.0f} STX")
    display_df['fee_multiplier'] = display_df['fee_multiplier'].apply(lambda x: f"{x:.2f}x")
    display_df['new_fee_per_tx'] = display_df['new_fee_per_tx'].apply(lambda x: f"{x:.2f} STX")
    display_df['additional_txs'] = display_df['additional_txs'].apply(lambda x: f"{x:,.0f}")
    display_df['new_tx_count'] = display_df['new_tx_count'].apply(lambda x: f"{x:.0f}")
    display_df['new_total_revenue'] = display_df['new_total_revenue'].apply(lambda x: f"{x:.2f} STX")
    display_df['pct_to_coinbase_replacement'] = display_df['pct_to_coinbase_replacement'].apply(lambda x: f"{x:.1f}%")

    display(display_df)

    roadmap_df


# ### PoX Miner Rewards Calculator
# 
# Experiment with different rho (commit ratio) and price assumptions to see how miner bids translate into BTC rewards for stackers. Each control includes a tooltip explaining what it does, and the table below defines every output metric.

# In[ ]:


# Interactive PoX miner rewards calculator
if widgets is None:
    display(Markdown('⚠️ <b>ipywidgets</b> is not installed in this environment — the interactive PoX calculator is disabled.'))
else:
    baseline_rho = float(panel_df.loc[panel_df['rho'].notna() & (panel_df['rho'] > 0), 'rho'].median())
    baseline_fees_stx = float(panel_df['fees_stx_sum'].median())
    baseline_stx_btc = float(panel_df['stx_btc'].median())
    baseline_stx_usd = float(panel_df['stx_usd'].median())
    baseline_btc_usd = float(panel_df['btc_usd'].median())

    circulating_supply_stx = const.DEFAULT_CIRCULATING_SUPPLY_USTX / const.USTX_PER_STX
    participation_default = 40.0
    if 'cycles_df' in globals() and isinstance(cycles_df, pd.DataFrame) and not cycles_df.empty and 'total_stacked_amount' in cycles_df.columns:
        stacked_vals = cycles_df['total_stacked_amount'].dropna()
        if not stacked_vals.empty:
            participation_default = float((stacked_vals.iloc[-1] / const.USTX_PER_STX) / circulating_supply_stx * 100)

    rho_slider = widgets.FloatSlider(
        value=1.0,
        min=0.4,
        max=1.6,
        step=0.02,
        description='Rho multiplier',
        description_tooltip='Scale the historical rho (BTC commit ratio). 1.0 = use observed median.'
    )
    fees_slider = widgets.FloatSlider(
        value=baseline_fees_stx,
        min=0.0,
        max=250.0,
        step=1.0,
        description='Fees (STX)',
        description_tooltip='Total STX fees per burn block (in addition to the 1,000 STX coinbase).'
    )
    stx_btc_slider = widgets.FloatSlider(
        value=baseline_stx_btc,
        min=0.00001,
        max=0.0003,
        step=0.000005,
        readout_format='.6f',
        description='STX/BTC',
        description_tooltip='Price of STX quoted in BTC.'
    )
    stx_usd_slider = widgets.FloatSlider(
        value=baseline_stx_usd,
        min=0.05,
        max=2.0,
        step=0.01,
        description='STX/USD',
        description_tooltip='Price of STX in USD for the optional USD readouts.'
    )
    btc_usd_slider = widgets.FloatSlider(
        value=baseline_btc_usd,
        min=10000,
        max=120000,
        step=100,
        description='BTC/USD',
        description_tooltip='Price of BTC in USD for the optional USD readouts.'
    )
    participation_slider = widgets.FloatSlider(
        value=participation_default,
        min=5.0,
        max=100.0,
        step=1.0,
        description='Participation %',
        description_tooltip='Share of circulating STX that is stacked. Used to estimate stacker APY.'
    )

    controls = widgets.VBox([
        widgets.HTML('<b>Inputs</b>'),
        rho_slider,
        fees_slider,
        stx_btc_slider,
        stx_usd_slider,
        btc_usd_slider,
        participation_slider,
    ])

    output = widgets.Output()

    metric_help = pd.DataFrame([
        ('rho_effective', 'Effective rho after applying the multiplier.'),
        ('reward_stx_total', 'Total STX reward per burn block (coinbase + fees).'),
        ('reward_value_btc', 'Reward value converted to BTC at the chosen price.'),
        ('miner_btc_per_tenure', 'BTC miners commit for the selected burn block.'),
        ('miner_btc_per_cycle', 'Total BTC committed over one 2,100-block PoX cycle.'),
        ('miner_btc_per_year', 'BTC commitment annualised using cycle cadence.'),
        ('stacker_apy_pct', 'Estimated annual BTC yield to stackers at the chosen participation.'),
    ], columns=['Metric', 'Definition'])

    def _format_value(value, unit=''):
        if value is None:
            return '—'
        if unit == '%':
            return f"{value:.2f}%"
        if unit == 'btc':
            return f"{value:.4f} BTC"
        if unit == 'stx':
            return f"{value:,.2f} STX"
        if unit == 'usd':
            return f"${value:,.2f}"
        return f"{value:,.4f}"

    def update_calculator(*_):
        output.clear_output()
        rho_effective = baseline_rho * rho_slider.value
        stacked_supply = circulating_supply_stx * (participation_slider.value / 100)
        summary = summarize_miner_rewards(
            rho=rho_effective,
            stx_btc_price=stx_btc_slider.value,
            fees_stx=fees_slider.value,
            btc_usd_price=btc_usd_slider.value,
            stx_usd_price=stx_usd_slider.value,
            stacked_supply_stx=stacked_supply,
        )
        display_rows = [
            ('Effective rho', summary['rho_effective'], ''),
            ('Reward per block', summary['reward_stx_total'], 'stx'),
            ('Reward value', summary['reward_value_btc'], 'btc'),
            ('Reward value (USD)', summary['reward_value_usd'], 'usd'),
            ('Miner BTC / block', summary['miner_btc_per_tenure'], 'btc'),
            ('Miner BTC / cycle', summary['miner_btc_per_cycle'], 'btc'),
            ('Miner BTC / year', summary['miner_btc_per_year'], 'btc'),
            ('Miner BTC / block (USD)', summary['miner_btc_per_tenure_usd'], 'usd'),
            ('Stacker APY (BTC)', summary['stacker_apy_pct'], '%'),
        ]
        df = pd.DataFrame(
            {
                'Metric': [label for label, *_ in display_rows],
                'Value': [_format_value(value, unit) for _, value, unit in display_rows],
            }
        )
        with output:
            display(Markdown(
                f"**Baseline rho:** {baseline_rho:.3f} &nbsp;|&nbsp; "
                f"**Circulating supply:** {circulating_supply_stx:,.0f} STX"
            ))
            display(df)
            display(Markdown('**Metric dictionary**'))
            display(metric_help)

    for ctrl in [rho_slider, fees_slider, stx_btc_slider, stx_usd_slider, btc_usd_slider, participation_slider]:
        ctrl.observe(update_calculator, names='value')

    update_calculator()
    widgets.VBox([controls, output])


# In[ ]:


# Coinbase Replacement Roadmap Visualization
from plotly.subplots import make_subplots

if not panel_df.empty and not roadmap_df.empty:
    # Use same 90-day window as roadmap calculation
    cutoff_date = panel_df['burn_block_time_iso'].max() - pd.Timedelta(days=ROADMAP_WINDOW_DAYS)
    recent_panel = panel_df[panel_df['burn_block_time_iso'] >= cutoff_date]

    baseline_fees = recent_panel['fees_stx_sum'].median()
    baseline_txs = recent_panel['tx_count'].median()
    baseline_fee_per_tx = baseline_fees / baseline_txs if baseline_txs else 0.0

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            '🎯 Pure Strategies Comparison',
            '🔄 Strategy Tradeoff Space',
            '📊 Coinbase Replacement Progress',
            '💡 Key Insights'
        ),
        specs=[
            [{"type": "table"}, {"type": "scatter"}],
            [{"type": "bar"}, {"type": "table"}]
        ],
        vertical_spacing=0.12,
        horizontal_spacing=0.10,
        row_heights=[0.45, 0.55]
    )

    # Panel 1: Pure Strategies Summary Table
    fee_strat = roadmap_df[roadmap_df['strategy'] == 'fee_multiplier'].copy()
    vol_strat = roadmap_df[roadmap_df['strategy'] == 'tx_volume'].copy()

    table_data = {
        'Target': [f"+{int(x)} STX" for x in fee_strat['target_increase_stx']],
        'Fee Strategy': [f"{m:.2f}x → {f:.2f} STX/tx" 
                        for m, f in zip(fee_strat['fee_multiplier'], fee_strat['new_fee_per_tx'])],
        'Volume Strategy': [f"+{int(a):,} txs → {int(t)} txs" 
                           for a, t in zip(vol_strat['additional_txs'], vol_strat['new_tx_count'])],
        'Progress': [f"{p:.0f}%" for p in fee_strat['pct_to_coinbase_replacement']]
    }

    fig.add_trace(
        go.Table(
            header=dict(
                values=[f'<b>{k}</b>' for k in table_data.keys()],
                fill_color='#2E86AB',
                align='left',
                font=dict(size=13, color='white')
            ),
            cells=dict(
                values=[table_data[k] for k in table_data.keys()],
                fill_color=[['#E8F4F8', '#D1E9F0', '#FFFFFF'] * 2],
                align='left',
                font=dict(size=12),
                height=30
            )
        ),
        row=1, col=1
    )

    # Panel 2: Tradeoff Contour Plot
    # Create meshgrid for contour plot
    fee_multipliers = np.linspace(1.0, 3.0, 50)
    tx_increases = np.linspace(0, 10000, 50)
    F, T = np.meshgrid(fee_multipliers, tx_increases)

    # Calculate revenue increase for each combination
    Z = (F - 1) * baseline_fees + T * baseline_fee_per_tx

    # Add contour plot
    fig.add_trace(
        go.Contour(
            x=fee_multipliers,
            y=tx_increases,
            z=Z,
            contours=dict(
                start=0,
                end=1200,
                size=100,
                showlabels=True,
                labelfont=dict(size=10, color='white')
            ),
            colorscale='Viridis',
            colorbar=dict(title="Revenue<br>Increase<br>(STX)", x=1.15),
            hovertemplate='Fee Mult: %{x:.2f}x<br>Extra Txs: %{y:,.0f}<br>Revenue: %{z:.0f} STX<extra></extra>'
        ),
        row=1, col=2
    )

    # Mark current baseline
    fig.add_trace(
        go.Scatter(
            x=[1.0],
            y=[0],
            mode='markers+text',
            marker=dict(size=15, color='red', symbol='star'),
            text=['Current'],
            textposition='top center',
            showlegend=False,
            hovertemplate='Baseline<extra></extra>'
        ),
        row=1, col=2
    )

    # Mark pure strategies for 1000 STX target
    roadmap_1000 = roadmap_df[roadmap_df['target_increase_stx'] == 1000]
    fee_mult_1000 = roadmap_1000[roadmap_1000['strategy'] == 'fee_multiplier']['fee_multiplier'].iloc[0]
    add_txs_1000 = roadmap_1000[roadmap_1000['strategy'] == 'tx_volume']['additional_txs'].iloc[0]

    fig.add_trace(
        go.Scatter(
            x=[fee_mult_1000, 1.0],
            y=[0, add_txs_1000],
            mode='markers+text',
            marker=dict(size=12, color='gold', symbol='diamond'),
            text=['Fee Path', 'Volume Path'],
            textposition=['top center', 'top center'],
            showlegend=False,
            hovertemplate='1000 STX Target<extra></extra>'
        ),
        row=1, col=2
    )

    # Panel 3: Progress Bars
    targets = [100, 500, 1000]
    colors = ['#A8DADC', '#457B9D', '#1D3557']

    for i, (target, color) in enumerate(zip(targets, colors)):
        pct = (target / COINBASE_STX) * 100
        fig.add_trace(
            go.Bar(
                x=[pct],
                y=[f'+{target} STX'],
                orientation='h',
                marker=dict(color=color),
                text=[f'{pct:.0f}% to coinbase replacement'],
                textposition='inside',
                showlegend=False,
                hovertemplate=f'Target: +{target} STX<br>Progress: {pct:.0f}%<extra></extra>'
            ),
            row=2, col=1
        )

    # Panel 4: Key Insights Table
    insights = {
        'Milestone': ['🟢 +100 STX (10%)', '🟡 +500 STX (50%)', '🔴 +1000 STX (100%)'],
        'Fee Strategy': [
            f"{roadmap_df[(roadmap_df['target_increase_stx']==100) & (roadmap_df['strategy']=='fee_multiplier')]['fee_multiplier'].iloc[0]:.2f}x fees",
            f"{roadmap_df[(roadmap_df['target_increase_stx']==500) & (roadmap_df['strategy']=='fee_multiplier')]['fee_multiplier'].iloc[0]:.2f}x fees",
            f"{roadmap_df[(roadmap_df['target_increase_stx']==1000) & (roadmap_df['strategy']=='fee_multiplier')]['fee_multiplier'].iloc[0]:.2f}x fees"
        ],
        'Volume Strategy': [
            f"+{int(roadmap_df[(roadmap_df['target_increase_stx']==100) & (roadmap_df['strategy']=='tx_volume')]['additional_txs'].iloc[0]):,} txs",
            f"+{int(roadmap_df[(roadmap_df['target_increase_stx']==500) & (roadmap_df['strategy']=='tx_volume')]['additional_txs'].iloc[0]):,} txs",
            f"+{int(roadmap_df[(roadmap_df['target_increase_stx']==1000) & (roadmap_df['strategy']=='tx_volume')]['additional_txs'].iloc[0]):,} txs"
        ]
    }

    fig.add_trace(
        go.Table(
            header=dict(
                values=[f'<b>{k}</b>' for k in insights.keys()],
                fill_color='#F1FAEE',
                align='left',
                font=dict(size=12)
            ),
            cells=dict(
                values=[insights[k] for k in insights.keys()],
                fill_color='white',
                align='left',
                font=dict(size=11),
                height=28
            )
        ),
        row=2, col=2
    )

    # Update axes
    fig.update_xaxes(title_text="Fee Multiplier", row=1, col=2)
    fig.update_yaxes(title_text="Additional Transactions", row=1, col=2)
    fig.update_xaxes(title_text="Progress to Coinbase Replacement (%)", range=[0, 105], row=2, col=1)

    # Overall layout
    fig.update_layout(
        height=1000,
        showlegend=False,
        title_text=f"<b>Roadmap to Coinbase Replacement</b><br><sup>Baseline (last {ROADMAP_WINDOW_DAYS}d): {baseline_fees:.0f} STX fees, {baseline_txs:.0f} txs/tenure ({baseline_fee_per_tx:.2f} STX/tx)</sup>",
        title_font_size=20
    )

    fig.show()

    # Save standalone
    fig.write_html(OUT_PATH / "coinbase_replacement_roadmap.html")
    print(f"\n✅ Roadmap dashboard saved to {OUT_PATH / 'coinbase_replacement_roadmap.html'}")
else:
    print("⚠️ No data available for roadmap visualization")


# ## 10. Interactive Dashboard
# 
# Comprehensive visualization showing scenario impacts, fee distributions, and trends.

# In[ ]:


# Create comprehensive scenario analysis dashboardfrom plotly.subplots import make_subplotsif not panel_df.empty and not scenario_df.empty:    # Dashboard with 6 panels    fig = make_subplots(        rows=3, cols=2,        subplot_titles=(            '📈 APY Shift by Fee Uplift',            '💰 Extra Transactions Needed',            '₿ BTC Commitment per Cycle',            '📊 Fee Distribution (Median vs Mean)',            '⏱️ Fees Over Time (Last 5000 Tenures)',            f'📋 Scenario Summary (rho={RHO_RANGE[1]:.2f})',                textposition='auto',            ),            row=1, col=1        )        # 2. Extra transactions needed    unique_uplifts = scenario_df.drop_duplicates('uplift')    fig.add_trace(        go.Bar(            x=unique_uplifts['uplift'] * 100,            y=unique_uplifts['delta_tx_count'],            text=unique_uplifts['delta_tx_count'].apply(lambda x: f'{x:,.0f}'),            textposition='auto',            marker_color='lightcoral',            showlegend=False,            name='Extra Txs'        ),        row=1, col=2    )        # 3. BTC commitment per cycle    for rho in RHO_RANGE:        subset = scenario_df[scenario_df['rho'] == rho]        fig.add_trace(            go.Scatter(                name=f'rho={rho}',                x=subset['uplift'] * 100,                y=subset['cycle_commit_sats'] / 1e8,                mode='lines+markers',                showlegend=False            ),            row=2, col=1        )        # 4. Fee distribution box plot    recent = panel_df.tail(3000)    fig.add_trace(        go.Box(            y=recent['fees_stx_sum'],            name='Fees',            marker_color='lightblue',            boxmean=True        ),        row=2, col=2    )        # 5. Fees over time    time_subset = panel_df.tail(5000)    fig.add_trace(        go.Scatter(            x=time_subset['burn_block_time_iso'],            y=time_subset['fees_stx_sum'],            mode='lines',            name='Fees',            line=dict(color='steelblue'),            showlegend=False        ),        row=3, col=1    )        # 6. Summary table    summary_data = scenario_df[scenario_df['rho'] == RHO_RANGE[1]][['uplift', 'delta_fee_stx', 'delta_tx_count', 'apy_shift_pct']].copy()    summary_data['uplift'] = summary_data['uplift'].apply(lambda x: f'{x*100:.0f}%')    summary_data['delta_fee_stx'] = summary_data['delta_fee_stx'].apply(lambda x: f'{x:.0f} STX')    summary_data['delta_tx_count'] = summary_data['delta_tx_count'].apply(lambda x: f'{x:,.0f}')    summary_data['apy_shift_pct'] = summary_data['apy_shift_pct'].apply(lambda x: f'{x:.4f}%')        fig.add_trace(        go.Table(            header=dict(                values=['<b>Uplift</b>', '<b>Extra Fees</b>', '<b>Extra Txs</b>', '<b>APY Shift</b>'],                fill_color='paleturquoise',                align='left',                font=dict(size=12)            ),            cells=dict(                values=[summary_data[col] for col in summary_data.columns],                fill_color='lavender',                align='left',                font=dict(size=11)            )        ),        row=3, col=2    )        # Update axes labels    fig.update_xaxes(title_text="Fee Uplift %", row=1, col=1)    fig.update_yaxes(title_text="APY Shift %", row=1, col=1)    fig.update_xaxes(title_text="Fee Uplift %", row=1, col=2)    fig.update_yaxes(title_text="Extra Transactions", row=1, col=2)    fig.update_xaxes(title_text="Fee Uplift %", row=2, col=1)    fig.update_yaxes(title_text="BTC per Cycle", row=2, col=1)    fig.update_yaxes(title_text="Fees (STX)", row=2, col=2)    fig.update_xaxes(title_text="Time", row=3, col=1)    fig.update_yaxes(title_text="Fees (STX)", row=3, col=1)        # Overall layout    median_fees = recent['fees_stx_sum'].median()    mean_fees = recent['fees_stx_sum'].mean()        fig.update_layout(        height=1200,        showlegend=True,        title_text=f"<b>Stacks PoX Flywheel Analysis Dashboard</b><br><sup>Baseline: {median_fees:.0f} STX median fees (vs {mean_fees:.0f} STX mean)</sup>",        title_font_size=22,        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)    )        fig.show()        # Also save standalone    fig.write_html(OUT_PATH / "scenario_dashboard.html")    print(f"✅ Dashboard saved to {OUT_PATH / 'scenario_dashboard.html'}")else:    print("⚠️ No data available for visualization")


# ## 11. Artifact Export
# 
# Persist key datasets to `./data/` and `./out/` for downstream usage.

# In[ ]:


if not panel_df.empty:
    panel_path = OUT_PATH / "tenure_panel.parquet"
    fees_path = OUT_PATH / "fees_by_tenure.parquet"
    rewards_path = OUT_PATH / "pox_rewards.parquet"
    price_path = OUT_PATH / "prices.parquet"
    scenario_path = OUT_PATH / "scenario_table.csv"

    panel_df.to_parquet(panel_path, index=False)
    fees_df.to_parquet(fees_path, index=False)
    rewards_df.to_parquet(rewards_path, index=False)
    prices_df.to_parquet(price_path, index=False)
    scenario_df.to_csv(scenario_path, index=False)

    print("Saved panel ->", panel_path)
    print("Saved fees ->", fees_path)
    print("Saved rewards ->", rewards_path)
    print("Saved prices ->", price_path)
    print("Saved scenario table ->", scenario_path)


# ## 12. Next Steps
# 
# - Extend to cycle-level aggregates (sum commits, rewards, rho by PoX cycle).
# - Add pool attribution analytics by incorporating stacker addresses.
# - Compare realized fees with Hiro mempool fee estimates for additional validation.
# - Integrate notebook with Deepnote (recommended) for easy sharing; sync with this repo for reproducibility.

# ## 13. PoX Yield Historical Analysis
# 
# Analyze historical PoX stacking yields using data from the Hiro API. This section calculates BTC-denominated APY for stackers across PoX cycles and compares yields to alternative Bitcoin yield products.

# In[ ]:


# Import yield calculation modules
from src import pox_yields, competitiveness

# Fetch PoX cycle data and calculate historical yields
print("Fetching PoX cycle data...")
cycles_yield_df = pox_yields.fetch_pox_cycles_data(force_refresh=FORCE_REFRESH)
rewards_by_cycle_df = pox_yields.aggregate_rewards_by_cycle(force_refresh=FORCE_REFRESH)

print(f"Retrieved {len(cycles_yield_df)} PoX cycles")
print(f"Aggregated rewards for {len(rewards_by_cycle_df)} cycles")

# Calculate APY metrics
apy_df = pox_yields.calculate_cycle_apy(cycles_yield_df, rewards_by_cycle_df)

print(f"\nPoX APY Statistics (last 10 cycles):")
recent_apy = apy_df.head(10)
print(f"  Mean APY: {recent_apy['apy_btc'].mean():.2f}%")
print(f"  Median APY: {recent_apy['apy_btc'].median():.2f}%")
print(f"  Min APY: {recent_apy['apy_btc'].min():.2f}%")
print(f"  Max APY: {recent_apy['apy_btc'].max():.2f}%")
print(f"  Std Dev: {recent_apy['apy_btc'].std():.2f}%")

apy_df.head(15)


# In[ ]:


# Visualize participation rate trends over cycles
import plotly.graph_objects as go

fig = go.Figure()

fig.add_trace(go.Scatter(
    x=apy_df['cycle_number'],
    y=apy_df['participation_rate_pct'],
    mode='lines+markers',
    name='Participation Rate',
    line=dict(color='#5546FF', width=2),
    marker=dict(size=6)
))

fig.update_layout(
    title='PoX Stacking Participation Rate Over Time',
    xaxis_title='PoX Cycle Number',
    yaxis_title='Participation Rate (%)',
    template='plotly_white',
    hovermode='x unified',
    height=400
)

fig.show()

print(f"\nCurrent Participation Rate: {apy_df.iloc[0]['participation_rate_pct']:.2f}%")
print(f"Mean Participation (last 20 cycles): {apy_df.head(20)['participation_rate_pct'].mean():.2f}%")


# In[ ]:


# Visualize APY trends over PoX cycles
fig = go.Figure()

fig.add_trace(go.Scatter(
    x=apy_df['cycle_number'],
    y=apy_df['apy_btc'],
    mode='lines+markers',
    name='BTC APY',
    line=dict(color='#F7931A', width=2),
    marker=dict(size=6)
))

# Add mean line
mean_apy = apy_df['apy_btc'].mean()
fig.add_hline(
    y=mean_apy,
    line_dash='dash',
    line_color='gray',
    annotation_text=f'Mean: {mean_apy:.2f}%',
    annotation_position='right'
)

fig.update_layout(
    title='PoX Stacker Yields (BTC-Denominated APY)',
    xaxis_title='PoX Cycle Number',
    yaxis_title='APY (%)',
    template='plotly_white',
    hovermode='x unified',
    height=400
)

fig.show()

print(f"\nRecent APY Trends:")
print(f"  Last 5 cycles mean: {apy_df.head(5)['apy_btc'].mean():.2f}%")
print(f"  Last 10 cycles mean: {apy_df.head(10)['apy_btc'].mean():.2f}%")
print(f"  Overall mean: {mean_apy:.2f}%")


# In[ ]:


# Display summary statistics table for recent cycles
from IPython.display import display

summary_df = apy_df.head(10).copy()
summary_df['total_stacked_stx'] = (summary_df['total_stacked_ustx'] / 1_000_000).round(0).astype(int)
summary_df['total_btc'] = (summary_df['total_btc_sats'] / 1e8).round(2)

display_cols = ['cycle_number', 'total_stacked_stx', 'total_btc', 'participation_rate_pct', 'apy_btc']
col_names = ['Cycle', 'Total Stacked (STX)', 'Total BTC', 'Participation (%)', 'APY (%)']

summary_table = summary_df[display_cols].copy()
summary_table.columns = col_names

print("Recent PoX Cycle Summary (Last 10 Cycles):\n")
display(summary_table.style.format({
    'Total Stacked (STX)': '{:,.0f}',
    'Total BTC': '{:.2f}',
    'Participation (%)': '{:.2f}',
    'APY (%)': '{:.2f}'
}))


# ## 14. Competitive Yield Comparison
# 
# Compare PoX stacking yields against alternative Bitcoin yield products including wBTC lending, CeFi platforms, and other DeFi yield opportunities. This analysis helps assess whether PoX yields are competitive enough to attract and retain stacker capital.

# In[ ]:


# Calculate current PoX yield metrics and competitive positioning
pox_apy_recent = apy_df.head(10)['apy_btc'].mean()
pox_apy_std = apy_df.head(10)['apy_btc'].std()

print(f"PoX Stacking APY (Recent 10 Cycles):")
print(f"  Mean: {pox_apy_recent:.2f}%")
print(f"  Std Dev: {pox_apy_std:.2f}%")

# Get competitive positioning analysis
positioning = competitiveness.get_competitive_positioning(pox_apy_recent, pox_apy_std)

print(f"\nCompetitive Positioning:")
print(f"  Rank: #{positioning['competitive_rank']} of {positioning['total_products']} products")
print(f"  Best Alternative: {positioning['best_alternative']} at {positioning['best_alternative_apy']:.2f}%")
print(f"  Yield Advantage vs Best: {positioning['yield_advantage_vs_best']:+.2f} percentage points")
print(f"  Average Yield Advantage: {positioning['avg_yield_advantage']:+.2f}%")
print(f"  Sharpe Ratio: {positioning['pox_sharpe']:.2f}")
print(f"  Risk Score: {positioning['pox_risk_score']}")


# In[ ]:


# Compare PoX yields against alternative Bitcoin yield products
comparison_df = competitiveness.compare_yields_across_products(pox_apy_recent, pox_apy_std)

# Rename and format columns for display
display_df = comparison_df.copy()
display_df = display_df.rename(columns={
    'product': 'Product',
    'alt_apy_median': 'Expected APY (%)',
    'yield_advantage_pp': 'Yield Advantage (pp)'
})

# Create APY Range column from benchmark data
display_df['APY Range (%)'] = display_df['Product'].apply(
    lambda p: f"{comparison_df[comparison_df['product'] == p]['alt_apy_median'].iloc[0] - 1:.1f}-{comparison_df[comparison_df['product'] == p]['alt_apy_median'].iloc[0] + 1:.1f}"
)

# Select and order columns for display
display_cols = ['Product', 'Expected APY (%)', 'APY Range (%)', 'Yield Advantage (pp)']
display_df = display_df[display_cols]

print("\nYield Comparison: PoX Stacking vs Alternative Bitcoin Products\n")
display(display_df.style.format({
    'Expected APY (%)': '{:.2f}',
    'Yield Advantage (pp)': '{:+.2f}'
}).background_gradient(subset=['Yield Advantage (pp)'], cmap='RdYlGn', vmin=-5, vmax=10))


# In[ ]:


# Visualize yield comparison across products
fig = go.Figure()

# Add bars for each product  
colors = ['#5546FF', '#F7931A', '#2A9D8F', '#E76F51', '#264653']
for idx, row in comparison_df.iterrows():
    fig.add_trace(go.Bar(
        x=[row['product']],
        y=[row['alt_apy_median']],
        name=row['product'],
        marker_color=colors[idx % len(colors)],
        showlegend=False
    ))

fig.update_layout(
    title='Bitcoin Yield Product Comparison',
    xaxis_title='Product',
    yaxis_title='Expected APY (%)',
    template='plotly_white',
    height=400,
    xaxis={'categoryorder': 'total descending'}
)

fig.show()

print(f"\nKey Insights:")
print(f"  Competitive Rank: #{positioning['competitive_rank']} of {positioning['total_products']} products")
print(f"  Yield Advantage vs Best Alternative: {positioning['yield_advantage_vs_best']:+.2f} percentage points")
print(f"  Average Yield Advantage: {positioning['avg_yield_advantage']:+.2f}%")
if positioning['yield_advantage_vs_best'] > 0:
    print(f"  ✅ PoX yields exceed the best alternative ({positioning['best_alternative']})")
elif positioning['yield_advantage_vs_best'] > -2:
    print(f"  📊 PoX yields are competitive with market alternatives")
else:
    print(f"  ⚠️  PoX yields lag behind {positioning['best_alternative']} by {abs(positioning['yield_advantage_vs_best']):.2f} pp")


# ## 15. Yield Sensitivity Analysis
# 
# Model how PoX stacking yields respond to changes in participation rates and miner BTC commitments. This sensitivity analysis helps understand the dynamics that drive stacker yields and identify scenarios for yield improvement.

# In[ ]:


# Build yield sensitivity scenarios using current cycle data
from src import scenarios

# Get baseline from most recent complete cycle
baseline_cycle = apy_df.iloc[0]
baseline_participation = baseline_cycle['participation_rate_pct']
baseline_apy = baseline_cycle['apy_btc']
baseline_stacked = baseline_cycle['total_stacked_ustx']
baseline_btc = baseline_cycle['total_btc_sats']

print(f"Baseline Metrics (Cycle {int(baseline_cycle['cycle_number'])}):")
print(f"  Participation Rate: {baseline_participation:.2f}%")
print(f"  APY: {baseline_apy:.2f}%")
print(f"  Total Stacked: {baseline_stacked/1e12:.2f}T microSTX")
print(f"  Total BTC: {baseline_btc/1e8:.2f} BTC")

# Generate sensitivity scenarios
sensitivity_df = scenarios.build_yield_sensitivity_scenarios(
    baseline_participation_rate=baseline_participation,
    baseline_apy_btc=baseline_apy,
    baseline_total_stacked_ustx=baseline_stacked,
    baseline_total_btc_sats=int(baseline_btc),
    participation_deltas=[-10, -5, 0, +5, +10],
    btc_deltas=[-25, 0, +25, +50],
)

print(f"\nGenerated {len(sensitivity_df)} sensitivity scenarios")
sensitivity_df.head(12)


# In[ ]:


# Create heatmap showing APY sensitivity to participation and BTC changes
import plotly.graph_objects as go

# Pivot data for heatmap
pivot_df = sensitivity_df.pivot_table(
    index='participation_delta',
    columns='btc_delta',
    values='new_apy_btc'
)

fig = go.Figure(data=go.Heatmap(
    z=pivot_df.values,
    x=[f"+{int(x)}%" if x >= 0 else f"{int(x)}%" for x in pivot_df.columns],
    y=[f"+{int(y)}%" if y >= 0 else f"{int(y)}%" for y in pivot_df.index],
    colorscale='RdYlGn',
    text=pivot_df.values.round(2),
    texttemplate='%{text:.2f}%',
    textfont={"size": 10},
    colorbar=dict(title="APY (%)")
))

fig.update_layout(
    title='PoX APY Sensitivity Matrix',
    xaxis_title='BTC Commitment Change',
    yaxis_title='Participation Rate Change',
    template='plotly_white',
    height=500,
    xaxis={'side': 'bottom'},
    yaxis={'autorange': 'reversed'}
)

fig.show()

print("\nKey Sensitivity Insights:")
print(f"  Best scenario (max APY): {sensitivity_df['new_apy_btc'].max():.2f}%")
print(f"  Worst scenario (min APY): {sensitivity_df['new_apy_btc'].min():.2f}%")
print(f"  APY range: {sensitivity_df['new_apy_btc'].max() - sensitivity_df['new_apy_btc'].min():.2f} percentage points")


# In[ ]:


# Display key scenario comparisons
print("Key Scenario Comparisons:\n")

# Baseline scenario (0,0)
baseline_row = sensitivity_df[(sensitivity_df['participation_delta'] == 0) & 
                               (sensitivity_df['btc_delta'] == 0)]
if not baseline_row.empty:
    print(f"📊 Baseline (no change):")
    print(f"   APY: {baseline_row.iloc[0]['new_apy_btc']:.2f}%\n")

# Best case: Lower participation, higher BTC
best_case = sensitivity_df.loc[sensitivity_df['new_apy_btc'].idxmax()]
print(f"✅ Best Case Scenario:")
print(f"   Participation: {best_case['participation_delta']:+.0f}% → {best_case['new_participation_rate']:.2f}%")
print(f"   BTC Commitment: {best_case['btc_delta']:+.0f}% → {best_case['new_total_btc_sats']/1e8:.2f} BTC")
print(f"   APY: {best_case['new_apy_btc']:.2f}%")
print(f"   APY Change: {best_case['apy_delta']:+.2f} percentage points\n")

# Worst case: Higher participation, lower BTC
worst_case = sensitivity_df.loc[sensitivity_df['new_apy_btc'].idxmin()]
print(f"⚠️  Worst Case Scenario:")
print(f"   Participation: {worst_case['participation_delta']:+.0f}% → {worst_case['new_participation_rate']:.2f}%")
print(f"   BTC Commitment: {worst_case['btc_delta']:+.0f}% → {worst_case['new_total_btc_sats']/1e8:.2f} BTC")
print(f"   APY: {worst_case['new_apy_btc']:.2f}%")
print(f"   APY Change: {worst_case['apy_delta']:+.2f} percentage points")


# ## 16. Competitive Thresholds
# 
# Calculate the minimum BTC commitments or maximum participation rates needed to maintain competitive stacker yields. This analysis identifies actionable targets for protocol improvements and ecosystem growth strategies.

# In[ ]:


# Calculate competitive thresholds for various target APYs
target_apys = [10.0, 12.0, 15.0, 18.0, 20.0]

thresholds_list = []
for target_apy in target_apys:
    threshold = scenarios.calculate_competitive_thresholds(
        target_apy_btc=target_apy,
        current_total_stacked_ustx=baseline_stacked,
        current_total_btc_sats=int(baseline_btc),
    )
    thresholds_list.append(threshold)

thresholds_df = pd.DataFrame(thresholds_list)

print("Competitive Thresholds Analysis:\n")
print("To achieve target APYs, either increase BTC commitments OR decrease participation:\n")

display(thresholds_df.style.format({
    'target_apy_btc': '{:.1f}%',
    'min_btc_sats_needed': lambda x: f"{x/1e8:.2f} BTC",
    'btc_increase_pct': '{:.1f}%',
    'max_participation_rate_pct': '{:.2f}%',
    'participation_decrease_pct': '{:.1f}%'
}).background_gradient(subset=['btc_increase_pct'], cmap='RdYlGn_r', vmin=0, vmax=100))


# In[ ]:


# Interpret threshold feasibility
print("Feasibility Assessment:\n")

for _, row in thresholds_df.iterrows():
    print(f"Target: {row['target_apy_btc']:.1f}% APY")
    print(f"  Status: {row['feasibility'].replace('_', ' ').title()}")

    if row['feasibility'] in ['achievable_btc', 'both']:
        print(f"  ✅ Achievable via BTC increase: +{row['btc_increase_pct']:.1f}% ({row['min_btc_sats_needed']/1e8:.2f} BTC)")

    if row['feasibility'] in ['achievable_participation', 'both']:
        print(f"  ✅ Achievable via participation decrease: {row['participation_decrease_pct']:.1f}% (to {row['max_participation_rate_pct']:.2f}%)")

    if row['feasibility'] == 'challenging':
        print(f"  ⚠️  Challenging: Requires +{row['btc_increase_pct']:.1f}% BTC increase")

    print()

# Identify most realistic improvement targets
print("Recommended Action Items:")
achievable_targets = thresholds_df[thresholds_df['feasibility'].isin(['achievable_btc', 'both'])]
if not achievable_targets.empty:
    best_target = achievable_targets.iloc[-1]  # Highest achievable APY
    print(f"  1. Target {best_target['target_apy_btc']:.1f}% APY via increased miner BTC commitments")
    print(f"     Required increase: +{best_target['btc_increase_pct']:.1f}% (from {baseline_btc/1e8:.2f} to {best_target['min_btc_sats_needed']/1e8:.2f} BTC)")
    print(f"  2. Focus on fee growth to boost BTC commitment incentives")
    print(f"  3. Explore yield-enhancing mechanisms (e.g., liquid stacking derivatives)")


# ## 17. Summary & Export
# 
# Summarize key findings from the yield competitiveness analysis and export data for further use.

# In[ ]:


# Generate executive summary of yield competitiveness analysis
print("=" * 80)
print("STACKS POX YIELD COMPETITIVENESS ANALYSIS - EXECUTIVE SUMMARY")
print("=" * 80)
print()

print(f"Analysis Date: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M UTC')}")
print(f"Data Window: Last {len(apy_df)} PoX cycles")
print()

print("1. CURRENT YIELD METRICS")
print("-" * 80)
print(f"   Recent APY (10-cycle mean): {pox_apy_recent:.2f}%")
print(f"   APY Volatility (std dev): {pox_apy_std:.2f}%")
print(f"   Participation Rate: {baseline_participation:.2f}%")
print(f"   Total BTC per Cycle: {baseline_btc/1e8:.2f} BTC")
print()

print("2. COMPETITIVE POSITIONING")
print("-" * 80)
print(f"   Rank: #{positioning['competitive_rank']} of {positioning['total_products']} Bitcoin yield products")
print(f"   Best Alternative: {positioning['best_alternative']} ({positioning['best_alternative_apy']:.2f}% APY)")
print(f"   Yield Advantage vs Best: {positioning['yield_advantage_vs_best']:+.2f} percentage points")
print(f"   Average Yield Advantage: {positioning['avg_yield_advantage']:+.2f}%")
print(f"   Sharpe Ratio: {positioning['pox_sharpe']:.2f}")
print(f"   Risk Score: {positioning['pox_risk_score']}")
print()

print("3. SENSITIVITY ANALYSIS")
print("-" * 80)
print(f"   APY Range (across scenarios): {sensitivity_df['new_apy_btc'].min():.2f}% - {sensitivity_df['new_apy_btc'].max():.2f}%")
print(f"   Best Case APY: {sensitivity_df['new_apy_btc'].max():.2f}% (lower participation + higher BTC)")
print(f"   Worst Case APY: {sensitivity_df['new_apy_btc'].min():.2f}% (higher participation + lower BTC)")
print()

print("4. COMPETITIVE THRESHOLDS")
print("-" * 80)
achievable = thresholds_df[thresholds_df['feasibility'].isin(['achievable_btc', 'both'])]
if not achievable.empty:
    max_achievable = achievable['target_apy_btc'].max()
    target_row = achievable[achievable['target_apy_btc'] == max_achievable].iloc[0]
    print(f"   Highest Achievable Target: {max_achievable:.1f}% APY")
    print(f"   Required BTC Increase: +{target_row['btc_increase_pct']:.1f}%")
    print(f"   Target BTC per Cycle: {target_row['min_btc_sats_needed']/1e8:.2f} BTC")
else:
    print(f"   All targets require >50% BTC increases (challenging)")
print()

print("5. KEY RECOMMENDATIONS")
print("-" * 80)
# Provide strategic recommendations based on competitive positioning
if positioning['yield_advantage_vs_best'] > 0:
    print(f"   • ✅ PoX yields are competitive - maintain current trajectory")
    print(f"   • Focus on stability and participation growth")
elif positioning['yield_advantage_vs_best'] > -2:
    print(f"   • 📊 PoX yields are adequate but could improve")
    print(f"   • Target modest BTC commitment increases via fee growth")
else:
    print(f"   • ⚠️  PoX yields need improvement to remain competitive")
    print(f"   • Prioritize mechanisms to boost BTC commitments")

if not achievable.empty:
    print(f"   • Target {max_achievable:.1f}% APY through fee growth and BTC commitment incentives")
print(f"   • Monitor participation rates to prevent yield dilution")
print(f"   • Explore yield enhancement mechanisms (liquid stacking, DeFi integration)")
print()
print("=" * 80)


# In[ ]:


# Export yield analysis datasets for further use
apy_export_path = OUT_PATH / "pox_apy_history.csv"
apy_df.to_csv(apy_export_path, index=False)
print(f"✅ Exported historical APY data: {apy_export_path}")

# Export yield comparison
comparison_export_path = OUT_PATH / "yield_comparison.csv"
comparison_df.to_csv(comparison_export_path, index=False)
print(f"✅ Exported yield comparison: {comparison_export_path}")

# Export sensitivity scenarios
sensitivity_export_path = OUT_PATH / "yield_sensitivity_scenarios.csv"
sensitivity_df.to_csv(sensitivity_export_path, index=False)
print(f"✅ Exported sensitivity scenarios: {sensitivity_export_path}")

# Export competitive thresholds
thresholds_export_path = OUT_PATH / "competitive_thresholds.csv"
thresholds_df.to_csv(thresholds_export_path, index=False)
print(f"✅ Exported competitive thresholds: {thresholds_export_path}")

print(f"\n📁 All yield analysis data exported to: {OUT_PATH}")
print(f"\n🎉 Yield Competitiveness Analysis Complete!")

