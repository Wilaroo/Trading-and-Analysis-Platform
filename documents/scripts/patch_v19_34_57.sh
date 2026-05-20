#!/usr/bin/env bash
# v19.34.57 — Apply BotTrade.__post_init__ trade_type stamping fix
# Run this from your DGX inside the project root:
#   ~/Trading-and-Analysis-Platform $  bash patch_v19_34_57.sh
# It is idempotent — re-running is a no-op once the patch is applied.

set -euo pipefail

cd "$(dirname "$0")"

python3 << 'PYEOF'
from pathlib import Path
import sys

p = Path("backend/services/trading_bot_service.py")
src = p.read_text()

ANCHOR = """    # Now threaded all the way through scanner → bot → evaluator → trade.
    alert_id: Optional[str] = None

    def to_dict(self) -> Dict:"""

REPLACEMENT = '''    # Now threaded all the way through scanner → bot → evaluator → trade.
    alert_id: Optional[str] = None

    def __post_init__(self):
        """v19.34.57 — Audit-gap closer: stamp `trade_type` at construction.

        Pre-v19.34.57, `trade_type` was only stamped inside the fill block
        of `services/trade_execution.py` (~lines 790-835). That meant any
        trade that never reached fill — REJECTED by the bot's pre-trade
        gates, VETOED by risk guards, or aborted before broker submission —
        was persisted with `trade_type='unknown'`. Audit revealed 227 such
        rows, polluting paper/live attribution and live-readiness gating.
        The fill-time block stays canonical (it reads the *actual* IB
        account_id from the pusher snapshot — the truth for filled rows).
        This `__post_init__` only fixes the construction-time default so
        rejected/vetoed trades inherit the operator's configured intent
        from `IB_ACCOUNT_ACTIVE`. On any import or env-load failure it
        leaves the field as the dataclass default ("unknown") — never
        worse than the legacy behavior.
        """
        if self.trade_type == "unknown":
            try:
                from services.account_guard import load_account_expectation
                self.trade_type = load_account_expectation().active_mode
            except Exception:
                # Stay on the dataclass default — preserves legacy behavior.
                self.trade_type = "unknown"

    def to_dict(self) -> Dict:'''

if "def __post_init__" in src and "v19.34.57" in src:
    print("[v19.34.57] already applied — no-op.")
    sys.exit(0)

if ANCHOR not in src:
    print("[v19.34.57] ANCHOR not found — file may have drifted. ABORTING.", file=sys.stderr)
    sys.exit(1)

new_src = src.replace(ANCHOR, REPLACEMENT, 1)
p.write_text(new_src)
print("[v19.34.57] PATCHED:", p)
PYEOF

echo ""
echo "[v19.34.57] Restart backend so the new dataclass loads:"
echo "  sudo systemctl restart sentcom-backend   # (or your backend service name)"
echo ""
echo "[v19.34.57] Optional: run the regression test"
echo "  cd backend && python -m pytest tests/test_trade_type_init_v19_34_57.py -v"
