#!/usr/bin/env bash
# Sync .env file to all git worktrees
#
# This script ensures all worktrees have a copy of the .env file since
# gitignored files are not shared between worktrees.
#
# Usage:
#   ./scripts/sync_env.sh [source_env_path]
#
# If source_env_path is not provided, uses /Users/alexanderhuth/Code/stx-labs/.env

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default source .env location
DEFAULT_SOURCE="/Users/alexanderhuth/Code/stx-labs/.env"
SOURCE_ENV="${1:-$DEFAULT_SOURCE}"

echo "🔄 Syncing .env files across worktrees..."
echo ""

# Verify source .env exists
if [[ ! -f "$SOURCE_ENV" ]]; then
    echo -e "${RED}❌ ERROR: Source .env not found at: $SOURCE_ENV${NC}"
    echo ""
    echo "Please provide a valid .env file path:"
    echo "  $0 /path/to/.env"
    exit 1
fi

echo -e "${GREEN}✓${NC} Source .env found: $SOURCE_ENV"
echo ""

# Show what's in the source .env (masked)
echo "Source .env contains:"
while IFS= read -r line; do
    # Skip comments and empty lines
    if [[ "$line" =~ ^[[:space:]]*# ]] || [[ -z "$line" ]]; then
        continue
    fi

    # Extract key and mask value
    if [[ "$line" =~ ^([^=]+)= ]]; then
        key="${BASH_REMATCH[1]}"
        echo "  - ${key}=***"
    fi
done < "$SOURCE_ENV"
echo ""

# Find all worktrees
WORKTREES=$(git worktree list --porcelain | grep "^worktree " | cut -d' ' -f2)

synced_count=0
skipped_count=0

for worktree in $WORKTREES; do
    dest="$worktree/.env"

    # Skip if same as source (avoid copying to itself)
    if [[ "$dest" -ef "$SOURCE_ENV" ]]; then
        echo -e "${YELLOW}⊘${NC} Skipping $worktree (source location)"
        skipped_count=$((skipped_count + 1))
        continue
    fi

    # Check if destination already exists and is identical
    if [[ -f "$dest" ]] && cmp -s "$SOURCE_ENV" "$dest"; then
        echo -e "${GREEN}✓${NC} Already synced: $worktree"
        skipped_count=$((skipped_count + 1))
        continue
    fi

    # Copy .env to worktree
    cp "$SOURCE_ENV" "$dest"
    echo -e "${GREEN}✓${NC} Synced to: $worktree"
    synced_count=$((synced_count + 1))
done

echo ""
echo "─────────────────────────────────────"
echo -e "${GREEN}✓ Sync complete!${NC}"
echo "  Updated: $synced_count worktree(s)"
echo "  Skipped: $skipped_count worktree(s)"
echo ""

# Verify all worktrees now have .env
echo "Verification:"
missing=0
for worktree in $WORKTREES; do
    if [[ -f "$worktree/.env" ]]; then
        echo -e "  ${GREEN}✓${NC} $worktree/.env exists"
    else
        echo -e "  ${RED}✗${NC} $worktree/.env MISSING"
        missing=$((missing + 1))
    fi
done

echo ""
if [[ $missing -eq 0 ]]; then
    echo -e "${GREEN}✓ All worktrees have .env files!${NC}"
    exit 0
else
    echo -e "${RED}⚠ Warning: $missing worktree(s) still missing .env${NC}"
    exit 1
fi
