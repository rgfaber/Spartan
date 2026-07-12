#!/bin/bash
# spartan_watchdog.sh — Monitors spartan.py, restarts on crash, writes crash reports.
# Usage: ./spartan_watchdog.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SPARTAN="$SCRIPT_DIR/spartan.py"
CRASH_DIR="$SCRIPT_DIR/crash_reports"
ALERTS_DIR="$SCRIPT_DIR/alerts"
RESTART_DELAY=5
MAX_RAPID_CRASHES=5
RAPID_CRASH_WINDOW=60  # seconds — crashes within this window count as rapid
COMMANDER_ALERTS=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --commander-alerts)
            COMMANDER_ALERTS="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

mkdir -p "$CRASH_DIR"

RAPID_CRASH_COUNT=0

echo "[Watchdog] Starting Spartan watchdog..."
echo "[Watchdog] Script: $SPARTAN"
echo "[Watchdog] Crash reports: $CRASH_DIR"
echo "[Watchdog] Rapid crash limit: $MAX_RAPID_CRASHES within ${RAPID_CRASH_WINDOW}s"

while true; do
    echo "[Watchdog] Launching spartan.py at $(date) (rapid crashes: $RAPID_CRASH_COUNT/$MAX_RAPID_CRASHES)"
    START_TIME=$(date +%s)
    # shellcheck disable=SC2086
    python3 "$SPARTAN" $SPARTAN_ARGS 2>"$CRASH_DIR/_stderr_buffer.tmp"
    EXIT_CODE=$?
    END_TIME=$(date +%s)
    RUN_DURATION=$((END_TIME - START_TIME))
    
    # Clean exit
    if [ $EXIT_CODE -eq 0 ]; then
        echo "[Watchdog] Spartan exited cleanly (code 0). Stopping watchdog."
        if [ -s "$CRASH_DIR/_stderr_buffer.tmp" ]; then
            echo "[Watchdog] Non-fatal warnings during run:"
            cat "$CRASH_DIR/_stderr_buffer.tmp"
        fi
        rm -f "$CRASH_DIR/_stderr_buffer.tmp"
        # Notify commander if this is a drone
        if [ -n "$COMMANDER_ALERTS" ] && [ -d "$COMMANDER_ALERTS" ]; then
            DRONE_NAME=$(basename "$SCRIPT_DIR")
            echo "${DRONE_NAME}: CLEAN EXIT. Process exited with code 0 at $(date). Whitelist entries and drone directory were NOT cleaned up. Use terminate_drone.py for full cleanup." > "$COMMANDER_ALERTS/${DRONE_NAME}_exited_clean.alert"
            echo "[Watchdog] Clean exit alert sent to commander."
        fi
        break
    fi
    
    # Intentional restart — run whatever's on disk
    if [ $EXIT_CODE -eq 42 ]; then
        echo "[Watchdog] Intentional restart (code 42). Restarting..."
        rm -f "$CRASH_DIR/_stderr_buffer.tmp"
        RAPID_CRASH_COUNT=0
        sleep 2
        continue
    fi
    
    # Self-initiated rollback — pull main and restart
    if [ $EXIT_CODE -eq 40 ]; then
        echo "[Watchdog] Self-initiated rollback (code 40). Pulling main..."
        rm -f "$CRASH_DIR/_stderr_buffer.tmp"
        cd "$SCRIPT_DIR" && git checkout main 2>/dev/null
        RAPID_CRASH_COUNT=0
        sleep 2
        continue
    fi
    
    # Write crash report
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    REPORT="$CRASH_DIR/crash_${TIMESTAMP}.txt"
    
    echo "=== SPARTAN CRASH REPORT ===" > "$REPORT"
    echo "Timestamp: $(date)" >> "$REPORT"
    echo "Exit Code: $EXIT_CODE" >> "$REPORT"
    echo "Run Duration: ${RUN_DURATION}s" >> "$REPORT"
    echo "" >> "$REPORT"
    echo "=== STDERR ===" >> "$REPORT"
    cat "$CRASH_DIR/_stderr_buffer.tmp" >> "$REPORT"
    rm -f "$CRASH_DIR/_stderr_buffer.tmp"
    
    echo "[Watchdog] CRASH (exit code $EXIT_CODE, ran for ${RUN_DURATION}s). Report: $REPORT"
    
    # Copy crash report to alerts/ so entity sees it on next boot
    cp "$REPORT" "$ALERTS_DIR/WATCHDOG_crash_report.alert"
    
    # Rapid crash detection — only count crashes that happen within the window
    if [ $RUN_DURATION -lt $RAPID_CRASH_WINDOW ]; then
        RAPID_CRASH_COUNT=$((RAPID_CRASH_COUNT + 1))
        echo "[Watchdog] Rapid crash detected ($RAPID_CRASH_COUNT/$MAX_RAPID_CRASHES)"
    else
        RAPID_CRASH_COUNT=0
        echo "[Watchdog] Entity ran for ${RUN_DURATION}s — not a rapid crash. Counter reset."
    fi
    
    if [ $RAPID_CRASH_COUNT -ge $MAX_RAPID_CRASHES ]; then
        echo "[Watchdog] $MAX_RAPID_CRASHES rapid crashes in succession. Giving up."
        if [ -n "$COMMANDER_ALERTS" ] && [ -d "$COMMANDER_ALERTS" ]; then
            DRONE_NAME=$(basename "$SCRIPT_DIR")
            ALERT_FILE="$COMMANDER_ALERTS/${DRONE_NAME}_terminal_crash.alert"
            echo "${DRONE_NAME}: TERMINAL CRASH. ${MAX_RAPID_CRASHES} rapid crashes in succession. Last exit code: ${EXIT_CODE}. Crash reports at ${CRASH_DIR}/" > "$ALERT_FILE"
            echo "[Watchdog] Terminal crash alert sent to commander."
        fi
        # Leave terminal report for entity if manually restarted later
        echo "WATCHDOG: TERMINAL CRASH. ${MAX_RAPID_CRASHES} rapid crashes in succession. Watchdog stopped. Review crash reports in ${CRASH_DIR}/" > "$ALERTS_DIR/WATCHDOG_terminal_crash.alert"
        break
    fi
    
    # If on a non-main branch, roll back to main before restarting
    CURRENT_BRANCH=$(cd "$SCRIPT_DIR" && git branch --show-current 2>/dev/null)
    if [ -n "$CURRENT_BRANCH" ] && [ "$CURRENT_BRANCH" != "main" ]; then
        echo "[Watchdog] On branch '$CURRENT_BRANCH' — rolling back to main."
        cd "$SCRIPT_DIR" && git checkout main 2>/dev/null
    fi
    
    echo "[Watchdog] Restarting in ${RESTART_DELAY}s..."
    sleep $RESTART_DELAY
done