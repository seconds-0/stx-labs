#!/usr/bin/env bash
# Health check for wallet history backfill process
#
# Usage:
#   ./scripts/backfill_health_check.sh [--target-days DAYS] [--stall-threshold SECONDS]
#
# Exit codes:
#   0 - Healthy: process running and making progress
#   1 - Not running: no backfill process found
#   2 - Stalled: process alive but no progress detected
#   3 - Database issues: cannot read database or corrupted
#   4 - Configuration error: missing files or invalid setup
#
# Features:
#   - Checks process is alive (via PID or tmux session)
#   - Verifies database is accessible and not locked
#   - Detects stalled progress (no new rows in N minutes)
#   - Validates log file is growing
#   - Returns detailed status for automation

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
DB_PATH="$PROJECT_ROOT/data/cache/wallet_metrics.duckdb"
LOG_FILE="$PROJECT_ROOT/out/backfill.log"
PID_FILE="$PROJECT_ROOT/out/backfill.pid"
CHECK_STATUS_SCRIPT="$SCRIPT_DIR/check_backfill_status.py"

# Parameters
TARGET_DAYS="${TARGET_DAYS:-365}"
STALL_THRESHOLD="${STALL_THRESHOLD:-600}"  # 10 minutes default

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
info() {
    echo -e "${BLUE}ℹ${NC} $*"
}

success() {
    echo -e "${GREEN}✓${NC} $*"
}

warn() {
    echo -e "${YELLOW}⚠${NC} $*"
}

error() {
    echo -e "${RED}✗${NC} $*"
}

# Parse arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --target-days)
                TARGET_DAYS="$2"
                shift 2
                ;;
            --stall-threshold)
                STALL_THRESHOLD="$2"
                shift 2
                ;;
            --help)
                echo "Usage: $0 [--target-days DAYS] [--stall-threshold SECONDS]"
                echo ""
                echo "Options:"
                echo "  --target-days DAYS         Expected target days (default: 365)"
                echo "  --stall-threshold SECONDS  Time without progress = stalled (default: 600)"
                echo ""
                echo "Exit codes:"
                echo "  0 - Healthy and making progress"
                echo "  1 - Not running"
                echo "  2 - Stalled (no progress)"
                echo "  3 - Database issues"
                echo "  4 - Configuration error"
                exit 0
                ;;
            *)
                error "Unknown option: $1"
                exit 4
                ;;
        esac
    done
}

# Check if process is running
check_process_running() {
    # Method 1: Check PID file
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            success "Process running (PID: $pid)"
            return 0
        else
            warn "PID file exists but process $pid is not running"
        fi
    fi

    # Method 2: Check tmux session
    if command -v tmux &> /dev/null; then
        if tmux has-session -t "stx-backfill" 2>/dev/null; then
            success "Tmux session 'stx-backfill' is running"
            return 0
        fi
    fi

    # Method 3: Look for process by name
    if pgrep -f "backfill_wallet_history.py" > /dev/null 2>&1; then
        local pid
        pid=$(pgrep -f "backfill_wallet_history.py" | head -1)
        success "Found backfill process (PID: $pid)"
        return 0
    fi

    error "No backfill process found"
    return 1
}

# Check if database is accessible
check_database_accessible() {
    if [[ ! -f "$DB_PATH" ]]; then
        error "Database not found at: $DB_PATH"
        return 1
    fi

    # Try to query database (read-only)
    if ! "$VENV_PYTHON" -c "import duckdb; conn = duckdb.connect('$DB_PATH', read_only=True); conn.execute('SELECT 1').fetchone(); conn.close()" 2>/dev/null; then
        error "Cannot access database (may be locked or corrupted)"
        return 1
    fi

    success "Database is accessible"
    return 0
}

# Check if progress is being made
check_progress() {
    if [[ ! -f "$LOG_FILE" ]]; then
        warn "Log file not found at: $LOG_FILE"
        return 1
    fi

    # Check log file modification time
    local log_age
    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS
        log_age=$(( $(date +%s) - $(stat -f %m "$LOG_FILE") ))
    else
        # Linux
        log_age=$(( $(date +%s) - $(stat -c %Y "$LOG_FILE") ))
    fi

    if [[ $log_age -gt $STALL_THRESHOLD ]]; then
        error "Log file not modified in ${log_age}s (threshold: ${STALL_THRESHOLD}s)"
        warn "Process may be stalled or hung"
        return 1
    fi

    success "Log file updated ${log_age}s ago (fresh)"

    # Check for recent progress indicators in log
    local recent_lines
    recent_lines=$(tail -20 "$LOG_FILE")

    if echo "$recent_lines" | grep -qE "(Fetching|completed|Progress:|Current status)"; then
        success "Recent progress indicators found in log"
        return 0
    else
        warn "No recent progress indicators in last 20 log lines"
        return 1
    fi
}

# Get current backfill status
get_status_details() {
    if [[ ! -f "$CHECK_STATUS_SCRIPT" ]]; then
        warn "Status script not found: $CHECK_STATUS_SCRIPT"
        return 1
    fi

    info "Fetching detailed status..."
    "$VENV_PYTHON" "$CHECK_STATUS_SCRIPT" --target-days "$TARGET_DAYS" 2>/dev/null || {
        warn "Could not fetch detailed status (database may be busy)"
        return 1
    }
}

# Main health check
main() {
    parse_args "$@"

    echo "================================================================================"
    echo "Wallet Backfill Health Check"
    echo "================================================================================"
    echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "Target days: $TARGET_DAYS"
    echo "Stall threshold: ${STALL_THRESHOLD}s"
    echo ""

    local exit_code=0
    local health_status="UNKNOWN"

    # Check 1: Process running
    echo "Check 1: Process Status"
    echo "--------------------------------------------------------------------------------"
    if check_process_running; then
        echo ""
    else
        health_status="NOT_RUNNING"
        exit_code=1
        echo ""
        echo "Result: ${RED}NOT RUNNING${NC}"
        echo ""
        echo "To start backfill:"
        echo "  make backfill-tmux"
        echo ""
        exit $exit_code
    fi

    # Check 2: Database accessible
    echo "Check 2: Database Accessibility"
    echo "--------------------------------------------------------------------------------"
    if check_database_accessible; then
        echo ""
    else
        health_status="DATABASE_ERROR"
        exit_code=3
        echo ""
        echo "Result: ${RED}DATABASE ERROR${NC}"
        echo ""
        echo "Troubleshooting:"
        echo "  1. Check if another process has the database locked"
        echo "  2. Try: lsof $DB_PATH"
        echo "  3. Restart backfill if necessary"
        echo ""
        exit $exit_code
    fi

    # Check 3: Progress detection
    echo "Check 3: Progress Detection"
    echo "--------------------------------------------------------------------------------"
    if check_progress; then
        health_status="HEALTHY"
        exit_code=0
        echo ""
    else
        health_status="STALLED"
        exit_code=2
        echo ""
        echo "Result: ${YELLOW}STALLED (no recent progress)${NC}"
        echo ""
        echo "Possible causes:"
        echo "  1. Process is waiting for API responses (check network)"
        echo "  2. Process is stuck in retry loop (check log for errors)"
        echo "  3. Process may need to be restarted"
        echo ""
        echo "Recent log entries:"
        tail -10 "$LOG_FILE" 2>/dev/null || echo "Cannot read log file"
        echo ""
        exit $exit_code
    fi

    # Check 4: Detailed status (optional, non-blocking)
    echo "Check 4: Detailed Status"
    echo "--------------------------------------------------------------------------------"
    get_status_details || warn "Skipping detailed status (database busy or script unavailable)"
    echo ""

    # Final summary
    echo "================================================================================"
    case "$health_status" in
        HEALTHY)
            echo "Health Status: ${GREEN}HEALTHY ✓${NC}"
            echo ""
            echo "The backfill process is running and making progress."
            echo "Continue monitoring with: make backfill-tail"
            ;;
        STALLED)
            echo "Health Status: ${YELLOW}STALLED ⚠${NC}"
            echo ""
            echo "The process is running but not making progress."
            echo "Monitor logs or consider restarting."
            ;;
        NOT_RUNNING)
            echo "Health Status: ${RED}NOT RUNNING ✗${NC}"
            echo ""
            echo "Start with: make backfill-tmux"
            ;;
        DATABASE_ERROR)
            echo "Health Status: ${RED}DATABASE ERROR ✗${NC}"
            echo ""
            echo "Database is inaccessible or corrupted."
            ;;
        *)
            echo "Health Status: ${YELLOW}UNKNOWN${NC}"
            ;;
    esac
    echo "================================================================================"

    exit $exit_code
}

main "$@"
