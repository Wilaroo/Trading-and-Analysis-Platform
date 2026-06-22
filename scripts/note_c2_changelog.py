#!/usr/bin/env python3
"""
note_c2_changelog.py — prepend the (C2) CHANGELOG entry (newest-first). Idempotent.
    PYTHONPATH=backend .venv/bin/python scripts/note_c2_changelog.py
    git add memory/CHANGELOG.md && git commit -m "C2: CHANGELOG note" && git push origin main
"""
import os

ANCHOR = "(C2) — IB-mark fallback for frozen open-trade marks"
ENTRY = """## 2026-06-22 — (C2) — IB-mark fallback for frozen open-trade marks (UPL/L7/kill-switch) — READY (apply pending)
diag_c (paste.rs/TJBxG) proved the handoff's TGT=0.00 issue is RESOLVED — all 25
holds carry a target + OCA attached (ATT=Y), all scanner bot_fired, none adopted.
The real residual was MARKS: 17/25 holds had current_price pinned at fill →
unrealized_pnl frozen at $0.00, while 8 tracked live. Root cause (traced through
position_manager.update_open_positions): held names that lose a pusher L1 quote
slot get a stale per-symbol _pushed_at, so the staleness guard (MANAGE_STALE_QUOTE
_SECONDS, ~line 749) `continue`s past the mark update (line 751), leaving the mark
frozen at entry. The existing _stale_resub_set drain (throttled 1/60s) couldn't
keep them fresh (pusher sub cap). FIX (patch_c2, paste.rs/1U9U8): instead of
fighting the cap, use IB's authoritative per-position marketPrice/unrealizedPNL —
pushed for EVERY position every cycle regardless of L1 subscription (sentcom_
service already trusts this source). New method
PositionManager._apply_ib_position_marks(bot), called at the END of
update_open_positions, stamps current_price = IB marketPrice and recomputes
unrealized_pnl / pnl_pct with the EXACT existing formula ((cp-fill)*remaining_shares
long / inverse short; pnl_pct from original_shares) — ONLY for trades the quote
path could not refresh (missing or pinned at fill); never clobbers a mark the live
quote moved this cycle. Purely additive: stops still evaluate on the real-time
quote path and fire server-side at IB. Env-gated POSITION_IB_MARK_FALLBACK
(default on; =0 disables). FAIL-OPEN (no pusher / any error → no-op). Span-SHA
guarded (PRE 8b3288ec), idempotent, .c2.bak, AST-compile, --check/--rollback.
pytest 6/6 (paste.rs/sVHXH): frozen-long stamped, short UPL sign correct, moving
mark left alone, env-off noop, no-IB-mark noop, pusher-disconnected noop.
BEHAVIOR NOTE: once marks are real, the kill-switch's unrealized sum reflects the
held names' TRUE (possibly negative) drawdown instead of $0 — correct risk
accounting; flagged to operator. Operator manually closed/cancelled all positions
3:55pm ET 2026-06-22, so C2 is preventive for next session's holds.

"""

for cand in ["memory/CHANGELOG.md", os.path.join(os.path.dirname(__file__), "..", "memory", "CHANGELOG.md")]:
    if os.path.isfile(cand):
        p = os.path.abspath(cand)
        c = open(p, encoding="utf-8").read()
        if ANCHOR in c:
            print(f"Idempotent: anchor present in {p} — no change.")
        else:
            open(p, "w", encoding="utf-8").write(ENTRY + c)
            print(f"Prepended (C2) entry to {p}.")
        break
else:
    print("ERROR: memory/CHANGELOG.md not found. Run from repo root.")
