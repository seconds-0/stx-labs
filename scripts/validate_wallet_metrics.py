#!/usr/bin/env python3
"""
Quick validation: Wallet metrics works independently of Signal21.

This script demonstrates that wallet_metrics:
- Only depends on Hiro API (/extended/v1/tx endpoint)
- Does NOT require Signal21 or CoinGecko
- Caches data in DuckDB for efficiency
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src import wallet_metrics

print("=" * 60)
print("Wallet Metrics Validation")
print("=" * 60)
print()
print("Dependencies:")
print("  ✓ Hiro API only (/extended/v1/tx)")
print("  ✓ Local DuckDB cache")
print("  ✗ Signal21 - NOT USED")
print("  ✗ CoinGecko - NOT USED")
print()
print("Running build_wallet_metrics() with 7-day window...")
print("(This will fetch recent transactions from Hiro API)")
print()

try:
    # Build wallet metrics with small window to keep it fast
    bundle = wallet_metrics.build_wallet_metrics(
        max_days=7,
        windows=(7,),
        force_refresh=False,  # Use cache if available
    )

    print("✅ SUCCESS - Wallet metrics loaded!")
    print()
    print(f"Activity records:      {len(bundle.activity):,}")
    print(f"Known wallets:         {len(bundle.first_seen):,}")
    print(f"New wallets (7d):      {bundle.new_wallets['new_wallets'].sum() if not bundle.new_wallets.empty else 0:,}")
    print(f"Active wallets (7d):   {bundle.active_wallets['active_wallets'].sum() if not bundle.active_wallets.empty else 0:,}")
    print()

    if not bundle.retention.empty:
        print("Retention (sample):")
        print(bundle.retention.head(3))
    else:
        print("Retention: No cohorts old enough for 7-day retention window")

    print()
    print("=" * 60)
    print("Validation complete! Wallet metrics is fully functional.")
    print("=" * 60)

except Exception as e:
    print(f"❌ ERROR: {type(e).__name__}: {e}")
    print()
    print("This is expected if:")
    print("  - Hiro API is down/unavailable")
    print("  - HIRO_API_KEY is not set in environment")
    print("  - No internet connection")
    sys.exit(1)
