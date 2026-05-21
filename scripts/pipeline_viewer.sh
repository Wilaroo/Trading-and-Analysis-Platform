#!/usr/bin/env bash
# v19.34.73 — Two-pane pipeline viewer launcher.
#
# Opens a tmux session with:
#   • Left pane (large): full pipeline tail (scan → AI → fill → close)
#   • Right pane (smaller): errors-only + warnings
#
# Usage:
#   bash scripts/pipeline_viewer.sh
#
# Inside tmux:
#   Ctrl+B then D    → detach (session keeps running in background)
#   tmux attach -t sentcom   → re-attach later
#   Ctrl+B then arrow → switch pane
#   Ctrl+B then x    → kill the focused pane
#
# To wire this into your Windows .bat startup flow:
#   ssh dgx "tmux new-session -d -s sentcom 'bash ~/Trading-and-Analysis-Platform/scripts/pipeline_viewer.sh'"
# Then `ssh dgx -t "tmux attach -t sentcom"` to view live.

set -euo pipefail

SESSION="sentcom"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v tmux >/dev/null 2>&1; then
    echo "tmux not installed. Install it with:"
    echo "  sudo apt install -y tmux"
    echo ""
    echo "Falling back to single-pane mode in this terminal..."
    exec bash "$REPO_DIR/scripts/tail_pipeline.sh"
fi

# Kill any prior session so we start fresh
tmux kill-session -t "$SESSION" 2>/dev/null || true

# Create new session with the main pipeline pane (left, ~70%)
tmux new-session -d -s "$SESSION" -x 200 -y 50 \
    -n pipeline "bash $REPO_DIR/scripts/tail_pipeline.sh"

# Split vertically: right side gets the errors pane (~30%)
tmux split-window -h -t "$SESSION:pipeline" -p 30 \
    "bash $REPO_DIR/scripts/tail_pipeline.sh --errors"

# Add a 3rd window for trades-only (Ctrl+B 2 to switch)
tmux new-window -t "$SESSION" -n trades \
    "bash $REPO_DIR/scripts/tail_pipeline.sh --trades"

# Add a 4th window for scanner-only (Ctrl+B 3)
tmux new-window -t "$SESSION" -n scanner \
    "bash $REPO_DIR/scripts/tail_pipeline.sh --scan"

# Add a 5th window for raw all-events (Ctrl+B 4)
tmux new-window -t "$SESSION" -n raw \
    "bash $REPO_DIR/scripts/tail_pipeline.sh --all"

# Switch focus back to the pipeline window
tmux select-window -t "$SESSION:pipeline"

# Attach
tmux attach -t "$SESSION"
