#!/usr/bin/env bash
# Tmux session wrapper for uninterruptible wallet history backfill
#
# Usage:
#   ./scripts/backfill_tmux.sh [start|attach|stop|status]
#
# Features:
#   - Named tmux session (stx-backfill) for SSH persistence
#   - Caffeinate wrapper to prevent macOS sleep
#   - Dual-pane layout: backfill runner + live monitor
#   - Auto-attach on subsequent calls
#   - Clean shutdown handling

set -euo pipefail

# Configuration
SESSION_NAME="stx-backfill"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
BACKFILL_SCRIPT="$SCRIPT_DIR/backfill_wallet_history.py"
MONITOR_SCRIPT="$SCRIPT_DIR/monitor_backfill.py"
LOG_FILE="$PROJECT_ROOT/out/backfill.log"
PID_FILE="$PROJECT_ROOT/out/backfill.pid"

# Default backfill parameters (overridable via environment)
TARGET_DAYS="${TARGET_DAYS:-365}"
MAX_PAGES="${MAX_PAGES:-5000}"
MAX_ITERATIONS="${MAX_ITERATIONS:-0}"  # 0 = infinite
DELAY="${DELAY:-5}"  # seconds between iterations

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

# Check if tmux is installed
check_tmux() {
    if ! command -v tmux &> /dev/null; then
        error "tmux is not installed. Install with: brew install tmux"
        exit 1
    fi
}

# Check if session exists
session_exists() {
    tmux has-session -t "$SESSION_NAME" 2>/dev/null
}

# Start new tmux session with backfill
start_session() {
    if session_exists; then
        warn "Session '$SESSION_NAME' already exists. Use 'attach' to reconnect."
        info "Or use 'stop' first to terminate the existing session."
        exit 1
    fi

    info "Creating tmux session '$SESSION_NAME' for 365-day backfill..."

    # Ensure output directory exists
    mkdir -p "$PROJECT_ROOT/out"

    # Clear previous log and PID files
    : > "$LOG_FILE"
    rm -f "$PID_FILE"

    # Create new detached session
    tmux new-session -d -s "$SESSION_NAME" -n "backfill"

    # Set up the backfill pane (pane 0)
    info "Setting up backfill runner in main pane..."
    tmux send-keys -t "$SESSION_NAME:0.0" "cd $PROJECT_ROOT" C-m
    tmux send-keys -t "$SESSION_NAME:0.0" "source .venv/bin/activate" C-m

    # Display configuration
    tmux send-keys -t "$SESSION_NAME:0.0" "echo '================================================================================'" C-m
    tmux send-keys -t "$SESSION_NAME:0.0" "echo 'STX Wallet Backfill - Uninterruptible Mode'" C-m
    tmux send-keys -t "$SESSION_NAME:0.0" "echo '================================================================================'" C-m
    tmux send-keys -t "$SESSION_NAME:0.0" "echo 'Target days: $TARGET_DAYS'" C-m
    tmux send-keys -t "$SESSION_NAME:0.0" "echo 'Max pages per iteration: $MAX_PAGES'" C-m
    tmux send-keys -t "$SESSION_NAME:0.0" "echo 'Max iterations: $MAX_ITERATIONS (0 = infinite)'" C-m
    tmux send-keys -t "$SESSION_NAME:0.0" "echo 'Delay between iterations: ${DELAY}s'" C-m
    tmux send-keys -t "$SESSION_NAME:0.0" "echo ''" C-m
    tmux send-keys -t "$SESSION_NAME:0.0" "echo 'Press Ctrl+B then D to detach (process continues in background)'" C-m
    tmux send-keys -t "$SESSION_NAME:0.0" "echo 'Reattach with: make backfill-tmux or ./scripts/backfill_tmux.sh attach'" C-m
    tmux send-keys -t "$SESSION_NAME:0.0" "echo '================================================================================'" C-m
    tmux send-keys -t "$SESSION_NAME:0.0" "echo ''" C-m
    tmux send-keys -t "$SESSION_NAME:0.0" "sleep 2" C-m

    # Start backfill with caffeinate (prevents sleep)
    BACKFILL_CMD="caffeinate -i $VENV_PYTHON -u $BACKFILL_SCRIPT --target-days $TARGET_DAYS --max-pages $MAX_PAGES --max-iterations $MAX_ITERATIONS --delay $DELAY"
    tmux send-keys -t "$SESSION_NAME:0.0" "$BACKFILL_CMD 2>&1 | tee $LOG_FILE" C-m

    # Split window horizontally for monitor
    sleep 1
    info "Setting up live monitor in bottom pane..."
    tmux split-window -t "$SESSION_NAME:0" -v -p 40

    # Set up monitor pane (pane 1)
    tmux send-keys -t "$SESSION_NAME:0.1" "cd $PROJECT_ROOT" C-m
    tmux send-keys -t "$SESSION_NAME:0.1" "source .venv/bin/activate" C-m
    tmux send-keys -t "$SESSION_NAME:0.1" "sleep 3" C-m  # Wait for backfill to start
    tmux send-keys -t "$SESSION_NAME:0.1" "$VENV_PYTHON $MONITOR_SCRIPT --target-days $TARGET_DAYS" C-m

    # Focus on the backfill pane
    tmux select-pane -t "$SESSION_NAME:0.0"

    success "Tmux session '$SESSION_NAME' created successfully!"
    info ""
    info "Pane layout:"
    info "  Top (60%):    Backfill runner with caffeinate (prevents sleep)"
    info "  Bottom (40%): Live progress monitor (auto-refreshing)"
    info ""
    info "Commands:"
    info "  Detach:      Ctrl+B then D (process keeps running)"
    info "  Reattach:    make backfill-tmux"
    info "  Stop:        make backfill-tmux-stop"
    info "  Quick check: make backfill-status"
    info ""
    info "Attaching to session in 2 seconds..."
    sleep 2

    # Attach to the session
    tmux attach-session -t "$SESSION_NAME"
}

# Attach to existing session
attach_session() {
    if ! session_exists; then
        error "Session '$SESSION_NAME' does not exist. Use 'start' to create it."
        exit 1
    fi

    info "Attaching to existing session '$SESSION_NAME'..."
    info "Press Ctrl+B then D to detach (process continues running)"
    sleep 1
    tmux attach-session -t "$SESSION_NAME"
}

# Stop the session
stop_session() {
    if ! session_exists; then
        warn "Session '$SESSION_NAME' does not exist."
        exit 0
    fi

    info "Stopping tmux session '$SESSION_NAME'..."

    # Send Ctrl+C to backfill pane to trigger graceful shutdown
    info "Sending interrupt signal to backfill process..."
    tmux send-keys -t "$SESSION_NAME:0.0" C-c

    # Wait a moment for graceful shutdown
    sleep 2

    # Kill the session
    tmux kill-session -t "$SESSION_NAME"

    # Clean up PID file
    rm -f "$PID_FILE"

    success "Session stopped."
}

# Show session status
show_status() {
    if ! session_exists; then
        echo "Status: ${YELLOW}Not running${NC}"
        echo ""
        echo "Start with: make backfill-tmux"
        exit 0
    fi

    echo "Status: ${GREEN}Running${NC}"
    echo ""
    echo "Session details:"
    tmux list-sessions -F "  Name: #{session_name}" -f "#{==:#{session_name},$SESSION_NAME}"
    tmux list-sessions -F "  Created: #{session_created_string}" -f "#{==:#{session_name},$SESSION_NAME}"
    tmux list-sessions -F "  Windows: #{session_windows}" -f "#{==:#{session_name},$SESSION_NAME}"
    echo ""
    echo "Commands:"
    echo "  Attach:      make backfill-tmux"
    echo "  Stop:        make backfill-tmux-stop"
    echo "  Quick check: make backfill-status"
    echo ""

    # Show brief progress if check script exists
    if [[ -f "$SCRIPT_DIR/check_backfill_status.py" ]]; then
        info "Current progress:"
        "$VENV_PYTHON" "$SCRIPT_DIR/check_backfill_status.py" --target-days "$TARGET_DAYS" 2>/dev/null || true
    fi
}

# Main command dispatcher
main() {
    check_tmux

    local command="${1:-}"

    case "$command" in
        start)
            start_session
            ;;
        attach)
            attach_session
            ;;
        stop)
            stop_session
            ;;
        status)
            show_status
            ;;
        "")
            # Default: attach if exists, otherwise start
            if session_exists; then
                attach_session
            else
                start_session
            fi
            ;;
        *)
            error "Unknown command: $command"
            echo ""
            echo "Usage: $0 [start|attach|stop|status]"
            echo ""
            echo "Commands:"
            echo "  start   - Create new tmux session (fails if already exists)"
            echo "  attach  - Attach to existing session (fails if not running)"
            echo "  stop    - Stop the session and backfill process"
            echo "  status  - Show session status and progress"
            echo "  (none)  - Smart mode: attach if exists, otherwise start"
            echo ""
            echo "Environment variables:"
            echo "  TARGET_DAYS=$TARGET_DAYS      - Days of history to fetch"
            echo "  MAX_PAGES=$MAX_PAGES         - Max pages per iteration"
            echo "  MAX_ITERATIONS=$MAX_ITERATIONS  - Max iterations (0=infinite)"
            echo "  DELAY=$DELAY               - Seconds between iterations"
            exit 1
            ;;
    esac
}

main "$@"
