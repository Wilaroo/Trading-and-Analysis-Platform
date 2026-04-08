#!/bin/bash
# ============================================================
#  TRAINING PIPELINE MONITOR — Real-Time Dashboard
#  Run on DGX Spark: ./monitor_training.sh
# ============================================================

REPO_DIR="${HOME}/Trading-and-Analysis-Platform"
LOG_FILE="${REPO_DIR}/backend/training_subprocess.log"
BACKEND_URL="http://localhost:8001"
MONGO_CONTAINER="mongodb"
DB_NAME="tradecommand"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m' # No Color

clear
echo -e "${BOLD}${CYAN}"
echo "  ========================================================"
echo "   TRADECOMMAND AI TRAINING PIPELINE — LIVE MONITOR"
echo "   $(date '+%Y-%m-%d %H:%M:%S')"
echo "  ========================================================"
echo -e "${NC}"

# ---- FUNCTION: Fetch status from MongoDB directly ----
get_mongo_status() {
    sudo docker exec $MONGO_CONTAINER mongosh --quiet $DB_NAME --eval "
        let s = db.training_pipeline_status.findOne({_id: 'pipeline'});
        if (!s) { print('NO_STATUS'); quit(); }
        let ph = s.phase_history || {};
        let phases = Object.entries(ph).sort((a,b) => (a[1].order||0) - (b[1].order||0));
        print('PHASE: ' + (s.phase || 'idle'));
        print('MODEL: ' + (s.current_model || '-'));
        print('PROGRESS: ' + (s.models_completed || 0) + '/' + (s.models_total || 0));
        print('PHASE_PCT: ' + ((s.current_phase_progress || 0)).toFixed(1) + '%');
        print('STARTED: ' + (s.started_at || '-'));
        let now = new Date();
        let started = s.started_at ? new Date(s.started_at) : now;
        let elapsed_min = ((now - started) / 60000).toFixed(0);
        print('ELAPSED: ' + elapsed_min + 'm');
        print('ERRORS: ' + (s.errors ? s.errors.length : 0));
        print('---LAST_MODELS---');
        let recent = (s.completed_models || []).slice(-3);
        recent.forEach(m => {
            let acc_str = m.accuracy ? (m.accuracy * 100).toFixed(1) + '%' : '-';
            print('  OK ' + m.name + ' (acc: ' + acc_str + ')');
        });
        print('---PHASES---');
        phases.forEach(([k, v]) => {
            let status_icon = v.status === 'done' ? 'DONE' : v.status === 'running' ? 'RUNNING' : v.status;
            let elapsed = v.elapsed_seconds ? (v.elapsed_seconds/60).toFixed(1) + 'm' : '-';
            let acc = v.avg_accuracy ? (v.avg_accuracy * 100).toFixed(1) + '%' : '-';
            print('  P' + (v.phase_num || '?') + ' [' + status_icon + '] ' + (v.label || k) + ' | models: ' + (v.models_trained||0) + '/' + (v.expected_models||'?') + ' | failed: ' + (v.models_failed||0) + ' | acc: ' + acc + ' | time: ' + elapsed);
        });
        print('---ERRORS---');
        (s.errors || []).slice(-5).forEach(e => {
            print('  [' + e.at + '] ' + e.model + ': ' + e.error);
        });
    " 2>/dev/null
}

# ---- FUNCTION: System resource check ----
get_system_stats() {
    echo -e "${DIM}--- SYSTEM RESOURCES ---${NC}"

    # Memory
    local mem_info=$(free -g | awk '/^Mem:/ {printf "Used: %dGB / %dGB (%.0f%%)", $3, $2, $3/$2*100}')
    local mem_pct=$(free | awk '/^Mem:/ {printf "%.0f", $3/$2*100}')
    local mem_color=$GREEN
    if [ "$mem_pct" -gt 80 ]; then mem_color=$RED;
    elif [ "$mem_pct" -gt 60 ]; then mem_color=$YELLOW; fi
    echo -e "  RAM:  ${mem_color}${mem_info}${NC}"

    # Swap
    local swap_info=$(free -g | awk '/^Swap:/ {if($2>0) printf "Used: %dGB / %dGB", $3, $2; else print "None"}')
    local swap_used=$(free -g | awk '/^Swap:/ {print $3}')
    local swap_color=$GREEN
    if [ "$swap_used" -gt 2 ]; then swap_color=$RED;
    elif [ "$swap_used" -gt 0 ]; then swap_color=$YELLOW; fi
    echo -e "  Swap: ${swap_color}${swap_info}${NC}"

    # GPU (if nvidia-smi available)
    if command -v nvidia-smi &>/dev/null; then
        local gpu_info=$(nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)
        if [ -n "$gpu_info" ]; then
            local gpu_util=$(echo "$gpu_info" | cut -d',' -f1 | tr -d ' ')
            local gpu_mem_used=$(echo "$gpu_info" | cut -d',' -f2 | tr -d ' ')
            local gpu_mem_total=$(echo "$gpu_info" | cut -d',' -f3 | tr -d ' ')
            local gpu_temp=$(echo "$gpu_info" | cut -d',' -f4 | tr -d ' ')
            local gpu_color=$GREEN
            if [ "$gpu_temp" -gt 85 ]; then gpu_color=$RED;
            elif [ "$gpu_temp" -gt 75 ]; then gpu_color=$YELLOW; fi
            echo -e "  GPU:  ${gpu_color}${gpu_util}% util | ${gpu_mem_used}MB / ${gpu_mem_total}MB | ${gpu_temp}C${NC}"
        fi
    fi

    # CPU load
    local load=$(uptime | awk -F'load average:' '{print $2}' | xargs)
    echo -e "  Load: ${DIM}${load}${NC}"

    # Training processes
    local n_procs=$(pgrep -fc training_subprocess 2>/dev/null || echo 0)
    local proc_color=$GREEN
    if [ "$n_procs" -gt 1 ]; then proc_color=$RED; fi
    echo -e "  Training procs: ${proc_color}${n_procs}${NC}"
}

# ---- FUNCTION: Pretty print MongoDB status ----
print_status() {
    local status_output=$(get_mongo_status)

    if [ "$status_output" = "NO_STATUS" ] || [ -z "$status_output" ]; then
        echo -e "${YELLOW}  No training status found in MongoDB.${NC}"
        echo -e "${DIM}  Start training from the NIA UI or call /api/ai-training/start${NC}"
        return
    fi

    echo -e "${DIM}--- PIPELINE STATUS ---${NC}"

    while IFS= read -r line; do
        case "$line" in
            PHASE:*)
                local phase="${line#PHASE: }"
                if [ "$phase" = "idle" ] || [ "$phase" = "done" ]; then
                    echo -e "  Phase:    ${GREEN}${phase}${NC}"
                else
                    echo -e "  Phase:    ${YELLOW}${BOLD}${phase}${NC}"
                fi
                ;;
            MODEL:*)
                echo -e "  Model:    ${WHITE}${line#MODEL: }${NC}"
                ;;
            PROGRESS:*)
                echo -e "  Progress: ${CYAN}${line#PROGRESS: }${NC} models"
                ;;
            PHASE_PCT:*)
                local pct="${line#PHASE_PCT: }"
                echo -e "  Batch:    ${CYAN}${pct}${NC}"
                ;;
            STARTED:*)
                echo -e "  Started:  ${DIM}${line#STARTED: }${NC}"
                ;;
            ELAPSED:*)
                echo -e "  Elapsed:  ${DIM}${line#ELAPSED: }${NC}"
                ;;
            ERRORS:*)
                local err_count="${line#ERRORS: }"
                if [ "$err_count" -gt 0 ]; then
                    echo -e "  Errors:   ${RED}${err_count}${NC}"
                else
                    echo -e "  Errors:   ${GREEN}0${NC}"
                fi
                ;;
            "---LAST_MODELS---")
                echo ""
                echo -e "${DIM}--- RECENTLY COMPLETED ---${NC}"
                ;;
            "  OK "*)
                echo -e "  ${GREEN}${line:2}${NC}"
                ;;
            "---PHASES---")
                echo ""
                echo -e "${DIM}--- PHASE BREAKDOWN ---${NC}"
                ;;
            "---ERRORS---")
                echo ""
                ;;
            "  P"*)
                # Color based on status
                if echo "$line" | grep -q "RUNNING"; then
                    echo -e "  ${YELLOW}${BOLD}${line:2}${NC}"
                elif echo "$line" | grep -q "DONE"; then
                    echo -e "  ${GREEN}${line:2}${NC}"
                else
                    echo -e "  ${DIM}${line:2}${NC}"
                fi
                ;;
            "  ["*)
                echo -e "  ${RED}${line:2}${NC}"
                ;;
        esac
    done <<< "$status_output"
}

# ---- MAIN LOOP ----
echo -e "${DIM}Monitoring mode: Dashboard refreshes every 10s${NC}"
echo -e "${DIM}Log tail follows: ${LOG_FILE}${NC}"
echo -e "${DIM}Press Ctrl+C to exit${NC}"
echo ""

# Check if log file exists
if [ ! -f "$LOG_FILE" ]; then
    echo -e "${YELLOW}Log file not found yet: ${LOG_FILE}${NC}"
    echo -e "${DIM}It will appear when training starts.${NC}"
fi

# Start background log tail (with color highlighting)
tail_training_log() {
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE" 2>/dev/null | while IFS= read -r line; do
            case "$line" in
                *"ERROR"*|*"FAILED"*|*"error"*|*"failed"*)
                    echo -e "${RED}${line}${NC}"
                    ;;
                *"Phase"*|*"PHASE"*|*"Starting phase"*)
                    echo -e "${YELLOW}${BOLD}${line}${NC}"
                    ;;
                *"completed"*|*"DONE"*|*"Success"*|*"trained"*)
                    echo -e "${GREEN}${line}${NC}"
                    ;;
                *"accuracy"*|*"acc="*|*"val_acc"*)
                    echo -e "${CYAN}${line}${NC}"
                    ;;
                *)
                    echo -e "${DIM}${line}${NC}"
                    ;;
            esac
        done
    fi
}

# Run dashboard refresh in background
dashboard_loop() {
    while true; do
        sleep 10
        # Print separator
        echo ""
        echo -e "${BLUE}════════════════════════════════════════ $(date '+%H:%M:%S') ════════════════════════════════════════${NC}"
        print_status
        echo ""
        get_system_stats
        echo -e "${BLUE}════════════════════════════════════════════════════════════════════════════════════${NC}"
        echo ""
    done
}

# Initial status dump
echo -e "${BLUE}════════════════════════════════════════ $(date '+%H:%M:%S') ════════════════════════════════════════${NC}"
print_status
echo ""
get_system_stats
echo -e "${BLUE}════════════════════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BOLD}${WHITE}--- LIVE LOG STREAM ---${NC}"
echo ""

# Launch both: dashboard refreshes every 10s + live log tail
dashboard_loop &
DASHBOARD_PID=$!

# Trap Ctrl+C to clean up
trap "kill $DASHBOARD_PID 2>/dev/null; echo -e '\n${NC}Monitor stopped.'; exit 0" INT TERM

# Foreground: tail the log
tail_training_log

# If log doesn't exist yet, wait for it
while [ ! -f "$LOG_FILE" ]; do
    sleep 2
done
tail_training_log

# Keep alive
wait
