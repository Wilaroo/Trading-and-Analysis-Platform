#!/usr/bin/env bash
# v19.34.58 — Surface synthetic-bookings inline on the HUD P&L tile
# Run from your DGX project root:
#   ~/Trading-and-Analysis-Platform $  bash patch_v19_34_58.sh
# Idempotent — re-running is a no-op once applied.

set -euo pipefail
cd "$(dirname "$0")"

python3 << 'PYEOF'
from pathlib import Path
import sys

p = Path("frontend/src/components/sentcom/panels/PipelineHUDV5.jsx")
src = p.read_text()

ANCHOR = '''                <span data-testid="pipeline-pnl-unrealized" className={unrealizedColor}>
                  U {formatMoney(unrealizedNum)}
                </span>
              </div>
            </div>'''

REPLACEMENT = '''                <span data-testid="pipeline-pnl-unrealized" className={unrealizedColor}>
                  U {formatMoney(unrealizedNum)}
                </span>
              </div>
              {/* v19.34.58 — Inline synthetic-bookings line.
                  Pre-v19.34.58 the synthetic-closeout context lived ONLY
                  in the title="" tooltip. Operator review 2026-05-20:
                  with R=$0.00\u00b0 and 11 synthetic closeouts totaling
                  -$2,507, the chip read as "nothing happened today" at
                  a glance \u2014 the \u00b0 glyph wasn't loud enough to overcome
                  the dominant zero. This line surfaces the synthetic
                  count + session sum directly under the R/U split when
                  count > 0, so the synthetic loss is visible without a
                  hover. Same data as the tooltip, just promoted. */}
              {realizedPnlSyntheticCount > 0 && (
                <div
                  data-testid="pipeline-pnl-synthetic-line"
                  className="flex items-baseline gap-1 text-[11px] v5-mono text-zinc-500"
                  title="Synthetic closeouts: bot records that IB had already realized in prior sessions. Excluded from today R to avoid double-counting against IB's books."
                >
                  <span>+{realizedPnlSyntheticCount} synthetic</span>
                  <span className="text-zinc-700">\u00b7</span>
                  <span
                    className={
                      (totalRealizedPnlSession ?? realizedPnlSyntheticSum ?? 0) >= 0
                        ? 'text-emerald-500/80'
                        : 'text-rose-500/80'
                    }
                  >
                    session {formatMoney(totalRealizedPnlSession ?? realizedPnlSyntheticSum ?? 0)}
                  </span>
                </div>
              )}
            </div>'''

if "v19.34.58" in src and "pipeline-pnl-synthetic-line" in src:
    print("[v19.34.58] already applied - no-op.")
    sys.exit(0)

if ANCHOR not in src:
    print("[v19.34.58] ANCHOR not found - file may have drifted. ABORTING.", file=sys.stderr)
    sys.exit(1)

p.write_text(src.replace(ANCHOR, REPLACEMENT, 1))
print("[v19.34.58] PATCHED:", p)
PYEOF

echo ""
echo "[v19.34.58] Frontend hot-reloads automatically. Hard-refresh your browser tab"
echo "             (Ctrl+Shift+R) to see the new synthetic-bookings line under R/U."
echo ""
echo "             Expected new line on the HUD when synthetic closeouts exist:"
echo "               R +\$0.00\u00b0   U \u2212\$169"
echo "               +11 synthetic \u00b7 session \u2212\$2,507"
