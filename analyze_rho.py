#!/usr/bin/env python3
"""
Analyze historical rho (commitment ratio) values from panel data.

This script validates the default rho = 0.5 assumption by examining
actual historical data.
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src import pox_constants as const
from src.scenarios import ScenarioConfig

# Paths
PANEL_PATH = Path("out/tenure_panel.parquet")
OUTPUT_DIR = Path("out")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze historical rho (commitment ratio).")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Skip visualization generation (useful for CI validation).",
    )
    return parser.parse_args()

def load_panel_data():
    """Load tenure panel data."""
    if not PANEL_PATH.exists():
        raise FileNotFoundError(f"Panel data not found at {PANEL_PATH}")

    df = pd.read_parquet(PANEL_PATH)
    print(f"✓ Loaded {len(df):,} tenure records")

    # Use burn_block_time_iso as timestamp
    if 'burn_block_time_iso' in df.columns:
        df['timestamp'] = pd.to_datetime(df['burn_block_time_iso'])
        print(f"  Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    else:
        print("  No timestamp column found")

    return df

def analyze_rho_statistics(df):
    """Calculate comprehensive rho statistics."""
    print("\n" + "="*70)
    print("RHO STATISTICAL ANALYSIS")
    print("="*70)

    # Overall statistics
    print("\n1. OVERALL STATISTICS (all tenures)")
    print("-" * 70)
    total_records = len(df)
    print(f"Total tenures: {total_records:,}")

    # Check for div-by-zero cases
    if 'rho_flag_div0' in df.columns:
        div_zero_count = df['rho_flag_div0'].sum()
        div_zero_pct = (div_zero_count / total_records) * 100
        print(f"Zero reward value (rho_flag_div0): {div_zero_count:,} ({div_zero_pct:.2f}%)")
    else:
        div_zero_count = 0
        print("No rho_flag_div0 column found")

    # Filter valid rho values (exclude div-by-zero and actual zeros)
    valid_rho = df[~df.get('rho_flag_div0', False) & (df['rho'] > 0)]['rho']
    valid_count = len(valid_rho)
    valid_pct = (valid_count / total_records) * 100

    print(f"Valid rho values (>0, no div0): {valid_count:,} ({valid_pct:.2f}%)")
    print(f"Zero or invalid rho: {total_records - valid_count:,} ({100-valid_pct:.2f}%)")

    # Statistics on valid rho
    print("\n2. VALID RHO DISTRIBUTION")
    print("-" * 70)
    print(f"Mean:   {valid_rho.mean():.4f}")
    print(f"Median: {valid_rho.median():.4f}")
    print(f"Std:    {valid_rho.std():.4f}")
    print(f"Min:    {valid_rho.min():.4f}")
    print(f"Max:    {valid_rho.max():.4f}")

    print("\nPercentiles:")
    percentiles = [5, 10, 25, 50, 75, 90, 95]
    for p in percentiles:
        val = valid_rho.quantile(p/100)
        print(f"  {p:>3}th: {val:.4f}")

    # Scenario bracket validation
    print("\n3. SCENARIO BRACKET VALIDATION")
    print("-" * 70)
    current_brackets = ScenarioConfig().rho_candidates
    print(f"Current brackets: {list(current_brackets)}")
    for bracket in current_brackets:
        percentile = (valid_rho <= bracket).mean() * 100
        print(f"  {bracket:.2f} is at {percentile:.1f}th percentile")

    # Recommended brackets based on actual quartiles
    p25 = valid_rho.quantile(0.25)
    p50 = valid_rho.quantile(0.50)
    p75 = valid_rho.quantile(0.75)
    print(f"\nRecommended brackets (25th, 50th, 75th percentiles):")
    print(f"  [{p25:.2f}, {p50:.2f}, {p75:.2f}]")

    # Distribution by ranges
    print("\n4. RHO RANGE DISTRIBUTION")
    print("-" * 70)
    ranges = [
        (0.0, 0.1, "Very low (0.0-0.1)"),
        (0.1, 0.3, "Low (0.1-0.3)"),
        (0.3, 0.5, "Medium-low (0.3-0.5)"),
        (0.5, 0.7, "Medium-high (0.5-0.7)"),
        (0.7, 1.0, "High (0.7-1.0)"),
        (1.0, 1.5, "Very high (1.0-1.5)"),
        (1.5, 2.0, "Extreme (1.5-2.0)"),
    ]

    for low, high, label in ranges:
        count = ((valid_rho >= low) & (valid_rho < high)).sum()
        pct = (count / valid_count) * 100
        print(f"{label:25s}: {count:6,} ({pct:5.1f}%)")

    return {
        'total_records': total_records,
        'valid_count': valid_count,
        'div_zero_count': div_zero_count,
        'valid_rho': valid_rho,
        'mean': valid_rho.mean(),
        'median': valid_rho.median(),
        'std': valid_rho.std(),
        'p25': p25,
        'p50': p50,
        'p75': p75,
    }

def analyze_temporal_trends(df):
    """Analyze how rho changes over time."""
    print("\n" + "="*70)
    print("TEMPORAL TREND ANALYSIS")
    print("="*70)

    # Ensure timestamp is datetime
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')

    # Filter valid rho
    valid_df = df[~df.get('rho_flag_div0', False) & (df['rho'] > 0)].copy()

    if len(valid_df) == 0:
        print("No valid rho data for temporal analysis")
        return None

    # Monthly statistics
    print("\n1. MONTHLY RHO TRENDS")
    print("-" * 70)
    valid_df['month'] = valid_df['timestamp'].dt.to_period('M')
    monthly = valid_df.groupby('month')['rho'].agg(['mean', 'median', 'std', 'count'])
    monthly = monthly[monthly['count'] >= 10]  # Only months with sufficient data

    print(f"Months with data: {len(monthly)}")
    if len(monthly) > 0:
        print("\nRecent months:")
        print(monthly.tail(6).to_string())

        # Trend analysis
        if len(monthly) >= 3:
            early_median = monthly.head(3)['median'].mean()
            recent_median = monthly.tail(3)['median'].mean()
            trend = ((recent_median - early_median) / early_median) * 100
            print(f"\nTrend: Early median={early_median:.3f}, Recent median={recent_median:.3f}")
            print(f"       Change: {trend:+.1f}%")

    # Rolling statistics
    print("\n2. ROLLING 30-DAY STATISTICS")
    print("-" * 70)
    if 'timestamp' in valid_df.columns:
        valid_df = valid_df.set_index('timestamp')
        rolling_30d = valid_df['rho'].rolling('30D', min_periods=10).agg(['mean', 'median', 'std'])

        if len(rolling_30d.dropna()) > 0:
            print("Last 5 periods:")
            print(rolling_30d.dropna().tail(5).to_string())

            # Volatility assessment
            recent_std = rolling_30d['std'].tail(30).mean()
            print(f"\nRecent 30-day volatility (avg std): {recent_std:.3f}")

    # PoX cycle analysis (if cycle data available)
    if 'cycle_id' in df.columns:
        print("\n3. POX CYCLE ANALYSIS")
        print("-" * 70)
        valid_df_reset = valid_df.reset_index()
        cycle_stats = valid_df_reset.groupby('cycle_id')['rho'].agg(['mean', 'median', 'std', 'count'])
        cycle_stats = cycle_stats[cycle_stats['count'] >= 5]

        print(f"Cycles with data: {len(cycle_stats)}")
        if len(cycle_stats) > 0:
            print("\nRecent cycles:")
            print(cycle_stats.tail(6).to_string())

    return monthly

def create_visualizations(df, stats, *, default_rho: float):
    """Generate rho distribution and trend visualizations."""
    print("\n" + "="*70)
    print("GENERATING VISUALIZATIONS")
    print("="*70)

    valid_rho = stats['valid_rho']

    # Create figure with subplots
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Rho (Commitment Ratio) Analysis', fontsize=16, fontweight='bold')

    # 1. Histogram
    ax1 = axes[0, 0]
    ax1.hist(valid_rho, bins=50, edgecolor='black', alpha=0.7)
    ax1.axvline(default_rho, color='red', linestyle='--', linewidth=2, label=f'Default ({default_rho:.2f})')
    ax1.axvline(valid_rho.median(), color='green', linestyle='--', linewidth=2, label=f'Actual Median ({valid_rho.median():.3f})')
    ax1.set_xlabel('Rho (BTC committed / Reward value)')
    ax1.set_ylabel('Frequency')
    ax1.set_title('Rho Distribution (Valid Values)')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # 2. Box plot
    ax2 = axes[0, 1]
    box_data = [valid_rho]
    bp = ax2.boxplot(box_data, vert=True, patch_artist=True)
    bp['boxes'][0].set_facecolor('lightblue')
    ax2.axhline(default_rho, color='red', linestyle='--', linewidth=2, label=f'Default ({default_rho:.2f})')
    ax2.set_ylabel('Rho')
    ax2.set_xticklabels(['All Valid'])
    ax2.set_title('Rho Box Plot (Outliers Shown)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    # 3. Time series (if timestamp available)
    ax3 = axes[1, 0]
    if 'timestamp' in df.columns:
        valid_df = df[~df.get('rho_flag_div0', False) & (df['rho'] > 0)].copy()
        valid_df['timestamp'] = pd.to_datetime(valid_df['timestamp'])
        valid_df = valid_df.sort_values('timestamp')

        ax3.scatter(valid_df['timestamp'], valid_df['rho'], alpha=0.3, s=10)
        ax3.axhline(default_rho, color='red', linestyle='--', linewidth=2, label=f'Default ({default_rho:.2f})')
        ax3.axhline(valid_rho.median(), color='green', linestyle='--', linewidth=2, label=f'Median ({valid_rho.median():.3f})')
        ax3.set_xlabel('Date')
        ax3.set_ylabel('Rho')
        ax3.set_title('Rho Over Time')
        ax3.legend()
        ax3.grid(True, alpha=0.3)
        plt.setp(ax3.xaxis.get_majorticklabels(), rotation=45)
    else:
        ax3.text(0.5, 0.5, 'No timestamp data', ha='center', va='center')
        ax3.set_title('Rho Over Time (No Data)')

    # 4. Cumulative distribution
    ax4 = axes[1, 1]
    sorted_rho = np.sort(valid_rho)
    cumulative = np.arange(1, len(sorted_rho) + 1) / len(sorted_rho) * 100
    ax4.plot(sorted_rho, cumulative, linewidth=2)
    ax4.axvline(default_rho, color='red', linestyle='--', linewidth=2, label=f'Default ({default_rho:.2f})')
    ax4.axvline(valid_rho.median(), color='green', linestyle='--', linewidth=2, label=f'Median ({valid_rho.median():.3f})')
    ax4.set_xlabel('Rho')
    ax4.set_ylabel('Cumulative %')
    ax4.set_title('Cumulative Distribution Function')
    ax4.legend()
    ax4.grid(True, alpha=0.3)

    plt.tight_layout()

    # Save figure
    output_path = OUTPUT_DIR / "rho_analysis.png"
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"✓ Saved visualization: {output_path}")

    plt.close()

def generate_report(stats, *, default_rho: float):
    """Generate final report with recommendations."""
    print("\n" + "="*70)
    print("CONFIDENCE ASSESSMENT & RECOMMENDATIONS")
    print("="*70)

    median = stats['median']
    diff = abs(median - default_rho)
    diff_pct = (diff / default_rho) * 100

    print("\n1. DEFAULT VALUE VALIDATION")
    print("-" * 70)
    print(f"Current default:     {default_rho:.4f}")
    print(f"Observed median:     {median:.4f}")
    print(f"Difference:          {diff:.4f} ({diff_pct:.1f}%)")

    if diff_pct < 5:
        verdict = "VALIDATED ✓"
        confidence = "HIGH (9/10)"
    elif diff_pct < 10:
        verdict = "ACCEPTABLE ~"
        confidence = "MEDIUM-HIGH (7/10)"
    elif diff_pct < 20:
        verdict = "NEEDS ADJUSTMENT !"
        confidence = "MEDIUM (5/10)"
    else:
        verdict = "INCORRECT ✗"
        confidence = "LOW (3/10)"

    print(f"\nVerdict:             {verdict}")
    print(f"Confidence in {default_rho:.2f}:   {confidence}")

    print("\n2. RECOMMENDED ACTIONS")
    print("-" * 70)

    if diff_pct >= 10:
        print(f"→ UPDATE default to {median:.3f} in pox_constants.py")
    else:
        print(f"→ KEEP default at {default_rho:.2f} (within {diff_pct:.1f}% of observed median)")

    print(f"→ UPDATE scenario brackets from [0.3, 0.5, 0.7] to [{stats['p25']:.2f}, {stats['p50']:.2f}, {stats['p75']:.2f}]")
    print(f"→ DOCUMENT rho validation in README or docs/")
    print(f"→ ADD rho analysis to notebook outputs")

    # Data quality
    valid_pct = (stats['valid_count'] / stats['total_records']) * 100
    if valid_pct < 80:
        print(f"\n⚠ WARNING: Only {valid_pct:.1f}% of tenures have valid rho")
        print("  → Investigate rho_flag_div0 cases")
        print("  → Consider filtering or imputation strategy")

    print("\n3. CONFIDENCE BREAKDOWN")
    print("-" * 70)
    print("Metric definition:       HIGH    (rho = BTC/reward_value is clear)")
    print("Calculation accuracy:    HIGH    (verified in tests)")
    print(f"Default value ({default_rho:.2f}): {confidence.split()[0]:8s}(based on {diff_pct:.1f}% difference)")
    print(f"Data coverage:           {'HIGH' if valid_pct >= 80 else 'MEDIUM':8s}({valid_pct:.1f}% valid records)")
    print(f"Temporal stability:      {'TBD':8s}(see temporal analysis above)")
    print("-" * 70)

    # Overall confidence
    if diff_pct < 10 and valid_pct >= 80:
        overall = "HIGH (8/10)"
    elif diff_pct < 20 and valid_pct >= 60:
        overall = "MEDIUM (6/10)"
    else:
        overall = "MEDIUM-LOW (4/10)"

    print(f"\nOVERALL CONFIDENCE:      {overall}")

def main():
    """Run complete rho analysis."""
    args = parse_args()
    default_rho = const.DEFAULT_COMMITMENT_RATIO

    print("\n" + "="*70)
    print("RHO (COMMITMENT RATIO) VALIDATION ANALYSIS")
    print("="*70)

    # Load data
    df = load_panel_data()

    # Statistical analysis
    stats = analyze_rho_statistics(df)

    # Temporal trends
    analyze_temporal_trends(df)

    # Visualizations
    if args.validate_only:
        print("\n(--validate-only) Skipping visualization generation")
    else:
        create_visualizations(df, stats, default_rho=default_rho)

    # Final report
    generate_report(stats, default_rho=default_rho)

    print("\n" + "="*70)
    print("ANALYSIS COMPLETE")
    print("="*70)
    if not args.validate_only:
        print(f"\nOutputs saved to: {OUTPUT_DIR}")
        print("  - rho_analysis.png (visualizations)")

if __name__ == "__main__":
    main()
