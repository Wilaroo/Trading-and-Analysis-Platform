#!/usr/bin/env bash
# v19.34.73 — Real-time pipeline / bot-decision viewer.
#
# Tails /tmp/backend.log (and /tmp/sentcom-backend.log) with color-coded
# filtering so the operator can see the full trade lifecycle in real time:
#   scan → alert → AI verdict → fill → bracket → manage → close.
#
# Usage:
#   bash scripts/tail_pipeline.sh           # full pipeline (default)
#   bash scripts/tail_pipeline.sh --all     # everything, no filter
#   bash scripts/tail_pipeline.sh --scan    # scanner & alerts only
#   bash scripts/tail_pipeline.sh --ai      # AI evaluations & verdicts
#   bash scripts/tail_pipeline.sh --trades  # fills + closes + brackets
#   bash scripts/tail_pipeline.sh --errors  # warnings & errors only
#   bash scripts/tail_pipeline.sh --symbol ADI   # filter to one symbol
#
# Two-pane mode (recommended):
#   tmux new-session -d -s sentcom 'bash scripts/tail_pipeline.sh --trades'
#   tmux split-window -h          'bash scripts/tail_pipeline.sh --errors'
#   tmux attach -t sentcom
#
# Color palette:
#   cyan    = scan / signal
#   blue    = AI evaluation
#   magenta = AI verdict / decision
#   green   = fill / success
#   yellow  = skip / dedup / cooldown
#   red     = error / rejection / abort
#   bold    = bracket / OCA
#   gray    = informational

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────
LOG_PRIMARY="/tmp/backend.log"
LOG_SECONDARY="/tmp/sentcom-backend.log"

# ── ANSI ──────────────────────────────────────────────────────────────
RESET=$'\033[0m'
BOLD=$'\033[1m'
DIM=$'\033[2m'
CYAN=$'\033[36m'
BLUE=$'\033[34m'
MAGENTA=$'\033[35m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
RED=$'\033[31m'
GRAY=$'\033[90m'

# ── Args ──────────────────────────────────────────────────────────────
MODE="pipeline"
SYMBOL=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --all)     MODE="all"; shift ;;
        --scan)    MODE="scan"; shift ;;
        --ai)      MODE="ai"; shift ;;
        --trades)  MODE="trades"; shift ;;
        --errors)  MODE="errors"; shift ;;
        --symbol)  SYMBOL="${2:-}"; shift 2 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//' | head -30
            exit 0
            ;;
        *) echo "Unknown flag: $1 (use --help)"; exit 1 ;;
    esac
done

# ── Verify log file ───────────────────────────────────────────────────
if [[ ! -f "$LOG_PRIMARY" ]]; then
    echo -e "${RED}ERROR:${RESET} $LOG_PRIMARY not found."
    echo "Is the backend running? Try: ./start_backend.sh"
    exit 1
fi

# ── Filter patterns per mode (egrep extended regex) ───────────────────
# Each mode is a union of grep patterns that must match for a line to
# pass through. Lines that match are then colorized below.

case "$MODE" in
    all)
        FILTER=".*"
        ;;
    scan)
        # Scanner activity + alert lifecycle
        FILTER='(scanner|Evaluating|fired ·|dropped|dedup|alert_id|squeeze|gap_fade|hod_breakout|breakout_confirmed|range_break|big_dog|accumulation|vwap_fade)'
        ;;
    ai)
        # AI verdicts + opportunity_evaluator
        FILTER='(VERDICT|ai_verdict|AI evaluation|REJECT|APPROVE|opportunity_evaluator|sym.?dir.?cap|symbol_cooldown|smart_filter|TQS )'
        ;;
    trades)
        # Fills, closes, brackets, OCA
        FILTER='(Filled |Trade closed|close_trade|close_position|OCA|bracket|attach.?bracket|naked.?sweep|reconcile|eod.?close|stop.?run|trailing.?stop|scale.?out)'
        ;;
    errors)
        # Anything red-flag
        FILTER='(ERROR|CRITICAL|WARNING|Error [0-9]+|Exception|Traceback|rejected|race_risk|timeout|disconnect|reconnect failed|aborted|fail|NAKED)'
        ;;
    pipeline|*)
        # Full lifecycle: scan + AI + trades + errors (default)
        FILTER='(scanner|Evaluating|fired ·|dropped|dedup|VERDICT|ai_verdict|REJECT|sym.?dir.?cap|Filled |Trade closed|close_trade|close_position|OCA|bracket|attach.?bracket|naked.?sweep|reconcile|eod.?close|trailing.?stop|scale.?out|ERROR|CRITICAL|Error [0-9]+|race_risk|timeout|disconnect|v19\.[0-9]+\.[0-9]+|🛑|✅|🔁|⏭️|🧹|🤔|🤖|🎯|⚠️)'
        ;;
esac

# Symbol filter (intersect with mode filter)
SYM_FILTER=""
if [[ -n "$SYMBOL" ]]; then
    SYM_FILTER="$(echo "$SYMBOL" | tr '[:lower:]' '[:upper:]')"
fi

# ── Header banner ────────────────────────────────────────────────────
clear
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${CYAN}║          SentCom — Real-time Pipeline Viewer (v19.34.73)         ║${RESET}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════════════╝${RESET}"
echo -e "  ${DIM}log:${RESET} $LOG_PRIMARY"
echo -e "  ${DIM}mode:${RESET} ${BOLD}$MODE${RESET}    ${DIM}symbol filter:${RESET} ${BOLD}${SYMBOL:-<all>}${RESET}"
echo -e "  ${DIM}press Ctrl+C to exit${RESET}"
echo -e "${GRAY}──────────────────────────────────────────────────────────────────────${RESET}"

# ── Tail + filter + color ────────────────────────────────────────────
# `-F` follows file across rotation/truncation (start_backend.sh
# overwrites /tmp/backend.log on each restart).
# `--line-buffered` flushes per-line so colors appear in real time.

tail -n 100 -F "$LOG_PRIMARY" 2>/dev/null | \
    grep --line-buffered -E "$FILTER" | \
    grep --line-buffered -E "${SYM_FILTER:-.}" | \
    while IFS= read -r line; do
        # Strip ANSI if any (defensive — backend doesn't emit color but
        # nested tail sometimes adds prefix bytes)
        clean="$(echo "$line" | tr -d '\r')"

        # Determine color based on content
        # Order matters — most specific first.
        if [[ "$clean" =~ (ERROR|CRITICAL|Exception|Traceback|race_risk|race_aborted|🛑) ]]; then
            color="$RED"
        elif [[ "$clean" =~ (WARNING|warn|rejected|reject|disconnect|reconnect|timeout|fail|🚨|⚠️) ]]; then
            color="$YELLOW"
        elif [[ "$clean" =~ (Filled |✅|Trade closed.*P&L|naked_sweep.*success) ]]; then
            color="$GREEN"
        elif [[ "$clean" =~ (VERDICT|ai_verdict|REJECT|APPROVE|🤖|🎯) ]]; then
            color="$MAGENTA"
        elif [[ "$clean" =~ (Evaluating|🤔|TQS\ |fired\ ·) ]]; then
            color="$BLUE"
        elif [[ "$clean" =~ (scanner|squeeze|gap_fade|hod_breakout|breakout_confirmed|range_break|big_dog|accumulation|vwap_fade) ]]; then
            color="$CYAN"
        elif [[ "$clean" =~ (OCA|bracket|attach.?bracket|naked.?sweep|reconcile|trailing.?stop|scale.?out) ]]; then
            color="$BOLD"
        elif [[ "$clean" =~ (dedup|cooldown|⏭️|🔁) ]]; then
            color="$DIM"
        else
            color="$GRAY"
        fi

        # Add a compact timestamp prefix (strip the long INFO: prefix
        # that FastAPI emits)
        ts="$(date +%H:%M:%S)"
        # Drop the noise prefix if present
        compact="$(echo "$clean" | sed -E 's/^INFO:\s+[0-9.]+:[0-9]+ - //')"

        echo -e "${DIM}${ts}${RESET} ${color}${compact}${RESET}"
    done
