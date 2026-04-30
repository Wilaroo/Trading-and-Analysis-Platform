#!/usr/bin/env bash
# morning_check.sh — pre-RTH autopilot readiness check
#
# Run on Spark each morning (~9:00 AM ET) to verify the bot is ready
# for fully automated trading. Calls /api/system/morning-readiness
# and prints a colour-coded breakdown.
#
# Designed to be cron-able:
#   30 8 * * 1-5 /home/spark-1a60/Trading-and-Analysis-Platform/scripts/morning_check.sh
#
# Exit code: 0 if green, 1 if yellow, 2 if red. Use in scripts:
#   morning_check.sh && curl -X POST .../trading-bot/start

set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8001}"

# Colours — disabled if not a tty.
if [[ -t 1 ]]; then
    GREEN=$'\033[0;32m'
    YELLOW=$'\033[0;33m'
    RED=$'\033[0;31m'
    BOLD=$'\033[1m'
    DIM=$'\033[2m'
    RESET=$'\033[0m'
else
    GREEN="" YELLOW="" RED="" BOLD="" DIM="" RESET=""
fi

response=$(curl -fsS "${API_BASE}/api/system/morning-readiness" 2>/dev/null || echo '{}')

if [[ -z "$response" || "$response" == "{}" ]]; then
    echo "${RED}${BOLD}MORNING CHECK FAILED${RESET} — backend unreachable at ${API_BASE}"
    exit 2
fi

verdict=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('verdict','red'))")
summary=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('summary','no summary'))")

case "$verdict" in
    green)  COLOUR="$GREEN" ;;
    yellow) COLOUR="$YELLOW" ;;
    red|*)  COLOUR="$RED" ;;
esac

echo
echo "${COLOUR}${BOLD}════════════════════════════════════════════════════════════${RESET}"
echo "${COLOUR}${BOLD}  ${summary}${RESET}"
echo "${COLOUR}${BOLD}════════════════════════════════════════════════════════════${RESET}"
echo

# Per-check breakdown.
RESPONSE_JSON="$response" python3 << 'PYEOF'
import json, os
data = json.loads(os.environ.get("RESPONSE_JSON", "{}"))
checks = data.get("checks", {})

GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
RED = "\033[0;31m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

ICONS = {"green": f"{GREEN}\u2713{RESET}",
         "yellow": f"{YELLOW}!{RESET}",
         "red": f"{RED}\u2717{RESET}"}

for name, c in checks.items():
    status = c.get("status", "red")
    detail = c.get("detail", "")
    icon = ICONS.get(status, "?")
    print(f"  {icon}  {BOLD}{name:<26}{RESET}  {detail}")
    if status == "red" and c.get("fix"):
        print(f"     {DIM}fix: {c['fix']}{RESET}")
print()
print(f"{DIM}generated {data.get('generated_at_et','')}  ({'RTH' if data.get('is_rth') else 'pre/post'}){RESET}")
PYEOF

# Exit code aligned with verdict.
case "$verdict" in
    green)  exit 0 ;;
    yellow) exit 1 ;;
    *)      exit 2 ;;
esac
