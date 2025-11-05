#!/usr/bin/env bash
# macOS-compatible notebook progress watcher

LOG_FILE="${1:-out/notebook.log}"

echo "Watching $LOG_FILE (Ctrl+C to stop)"
echo "─────────────────────────────────────"

while true; do
    clear
    echo "📊 Notebook Progress - $(date +"%H:%M:%S")"
    echo "─────────────────────────────────────"
    
    # Show last 15 lines of log
    tail -15 "$LOG_FILE" 2>/dev/null || echo "Waiting for log file..."
    
    echo ""
    echo "─────────────────────────────────────"
    echo "Press Ctrl+C to stop watching"
    
    sleep 2
done
