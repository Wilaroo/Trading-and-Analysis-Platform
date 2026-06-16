#!/usr/bin/env python3
"""patch_memory_docs_v320_gate_session.py  —  2026-06-16 PM

Appends today's morning session (v320 gate observe-mode deploy + OCA
mislabel investigation + sanitize_v2 rerun + bonus v325 reach-gate
signal) to memory/CHANGELOG.md and memory/PRD.md banner.

Anchored on the v320f/g entry committed last night (b1d66b7b).
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = os.path.expanduser("~/Trading-and-Analysis-Platform")
CHANGELOG = os.path.join(REPO, "memory", "CHANGELOG.md")
PRD = os.path.join(REPO, "memory", "PRD.md")

CHANGELOG_ANCHOR = "## 2026-06-16 — v320f mislabel cleanup APPLIED + v320g SPCX surgical repair APPLIED"
PRD_ANCHOR = "> **🔜 2026-06-16 — Issue 1 + Issue 2 from prior fork BOTH RESOLVED."

CHANGELOG_PREPEND = """## 2026-06-16 (PM) — v19.34.320 daily-bar premarket gate APPLIED (observe mode) + OCA mislabel investigation

### v19.34.320 — Daily-bar premarket gate, observe-mode rollout (paste.rs/h5qCR, patcher sha 0d37639c)

Inserts a pre-cutoff ET gate in `opportunity_evaluator.evaluate_opportunity`
that suppresses entries whose `trade_style ∈ {multi_day, swing, position,
investment}` OR `setup_type ∈ {daily_breakout, rs_leader_break,
stage_2_breakout, power_trend_stack, pocket_pivot, three_week_tight,
accumulation_entry, daily_squeeze}` when current ET time is before
`V320_DAILY_BAR_CUTOFF_ET` (default 10:00).

Rationale: today's daily OHLCV bar isn't mature until ~30 min into RTH.
Setups consuming today's daily bar pre-10:00 ET read incomplete/whippy
data → poor entries. Premarket-firing diag (30d window) showed 158× pre-9:30
ET `rs_leader_break` fires and 156× `daily_breakout` fires — material exposure.

**Patcher** is AGENTS.md §2.2-compliant:
- Anchored base64 (old, new) chunk pair (170-char old, ~5,100-char new)
- Per-file SHA256 PRE + POST hash guards
- Aborts cleanly on pre-mismatch, OLD-not-unique, or projected post-mismatch
- Post-apply on-disk hash verify with auto-restore on mismatch
- `--check / --apply / --rollback / --status`
- `EXPECTED_PRE_SHA=ce3624c52cb6c03f...` `EXPECTED_POST_SHA=886bb28761779e61...`

**Policy ENV**: `V320_DAILY_BAR_GATE_POLICY={block,observe,off}` (default block).
Deployed today as `observe` for safe 1-day rollout — logs `👁️ [v19.34.320
OBSERVE] daily-bar gate would BLOCK ...` but allows trade through.

**Apply result**: ✓ post-hash verified; backup at
`opportunity_evaluator.py.bak.20260616T133509`; stamp at /tmp/v320_gate.applied;
backend restarted via `./start_backend.sh --force` (per §2.4); all 8 health
subsystems green; IB connected via ib_direct.

**Observation window 9:35-10:00 ET**: ZERO `[v19.34.320]` lines — no
eligible daily-bar setups fired in today's window. Decision pending
tomorrow morning whether to flip to `block`.

### OCA close-reason mislabel investigation (diag_oca_close_reason_landscape.py)

User caught a VERIFY-BEFORE-CLAIM hole: agent's prior claim "ZERO target_hit
on 112 sanitized trades → bracket geometry is the leak" was based on a
labeling artifact. ARM (id=fc0903e3) hit PT1 @ 414.02 yesterday but
bot_trades shows `close_reason=oca_closed_externally_v19_31`, `exit_price=None`,
`net_pnl=-1.00` — same bug pattern as v320g SPCX.

**Scope landscape (read-only diag run)**:
- 465 total `oca_closed_externally_v19_31` trades across history
- 461 (99.1%) `no_exec_match` — `ib_executions` collection only started
  capturing in June; May has no ground truth
- 4 classified: 2 target hits (ARM, SPCX) + 2 stop losses (DVN, CBZ)

**Implications**:
- Historical relabel pass (`v320h`) is low-yield (only 4 recoverable trades)
- **Source-code fix is the real lead**: every IB-OCA-closed trade currently
  flows through a catch-all that overwrites the correct `close_reason` and
  drops `exit_price/net_pnl/pnl_pct`. Affects ALL future closes too.
- "Horizon-scaled bracket geometry" hypothesis is NEITHER confirmed nor
  refuted — May data has no ground truth, June data is thin

### Bonus signal — v19.34.325 HSBG reach-gate empirical evidence

During observe-mode tail today, caught:
`🚫 [v325 HSBG reach-gate] Blocking KRE second_chance — PT1 needs 2.07x
the expected price travel for a scalp hold (PT1 Δ$1.11 vs envelope $0.54)`

This is a DIFFERENT gate but provides empirical support for the ROADMAP-queued
horizon-scaled bracket-geometry hypothesis: targets ARE being placed too far
relative to the time-window envelope. Worth bookmarking for the geometry
rework planning.

### sanitize_v2 rerun (2026-06-16 13:05Z)

Re-ran `diag_sanitized_closed_trades.py`. Core grew 102→112 (+10 in 4 days).
Era trajectory confirms cleanup work is paying off:
- 2026-02: n=2, avgR=-0.50
- 2026-03: n=4, avgR=-0.70
- 2026-04: n=4, avgR=-0.08
- 2026-05: n=34, win=35.3%, avgR=-0.04
- **2026-06: n=68, win=44.1%, avgR=-0.00** ← trustworthy era

A-grade on sanitized: n=14, win=50%, avgR=+0.16 (only positive-expectancy
group). Grade calibration is NOT inverted on clean data (prior "inverted"
claim was an artifact of unsanitized noise).

### Windows ops tooling — `scripts/tail-v320-gate.ps1` (paste.rs/TrxPq, sha 985e9b11)

PowerShell wrapper for SSH+grep tailing the DGX backend log from the
Windows PC. Per AGENTS.md §15 — pings 192.168.50.2 first, validates
OpenSSH client, uses `tail -F` + `grep --line-buffered` for live
streaming. Configurable filter, line count, host. Ctrl-C exits cleanly.

### Files added this session
- `backend/scripts/diag_setup_trade_catalog_deep_audit.py` — 10-section setup landscape audit (raw)
- `backend/scripts/diag_v320_premarket_daily_bar_setups.py` — pre-cutoff fire analysis
- `backend/scripts/diag_arm_target_hit_probe.py` — ARM-class OCA mislabel triangulation
- `backend/scripts/diag_oca_close_reason_landscape.py` — system-wide OCA classification
- `backend/scripts/patch_v320_daily_bar_premarket_gate.py` — §2.2-compliant gate patcher
- `scripts/tail-v320-gate.ps1` — Windows SSH+tail ops tool

### Pending follow-up (next session)

1. **Tomorrow 09:30 ET**: review overnight observe-mode log → flip
   `V320_DAILY_BAR_GATE_POLICY=observe` → `block` if scope looks sensible.
2. **Real bug to fix**: OCA-external close path in
   `backend/services/position_manager.py` / `bracket_reissue_service.py` —
   when IB-side OCA fills close a position, classify the leg (target vs
   stop) and finalize `exit_price/net_pnl/pnl_pct` at runtime so future
   ARM/SPCX cases don't recur.
3. **Investigate**: 77 unmatched June OCA trades (window? partial fills?
   symbol case?) before declaring v320h scope final.
4. **Quiet-moment cleanup**: stale CVNA:d1d6b5b7 pending order (the
   v19.34.300 safety gate is correctly refusing to abandon it).

---

"""

PRD_PREPEND = """> **🔜 2026-06-16 (PM) — v19.34.320 daily-bar premarket gate APPLIED in OBSERVE mode.
> Anchored §2.2-compliant patcher (paste.rs/h5qCR, sha 0d37639c) inserted gate
> in `opportunity_evaluator.evaluate_opportunity` before the v19.34.173 F-gate.
> PRE=ce3624c5, POST=886bb287 (both verified on apply). Backup at
> opportunity_evaluator.py.bak.20260616T133509. Backend restarted via
> `./start_backend.sh --force`; 8/8 subsystems green. ENV
> `V320_DAILY_BAR_GATE_POLICY=observe` in backend/.env. Today's 9:35-10:00 ET
> window: zero gate fires (no eligible daily-bar setups emitted).
> Tomorrow 09:30 ET: review log, decide observe→block.
> **OCA-mislabel landscape clarified**: only 4 recoverable across history
> (461/465 no_exec_match — ib_executions only started capturing in June).
> Source-code fix in OCA-external close path is the real bug worth chasing.
> Bonus: v325 reach-gate caught KRE/second_chance PT1@2.07x envelope —
> empirical support for ROADMAP horizon-scaled bracket-geometry rework.
> sanitize_v2 rerun: 102→112 clean core; June n=68 wr=44.1% avgR=-0.00
> (trustworthy era). A-grade on sanitized: n=14 win=50% avgR=+0.16 (grade
> calibration NOT inverted on clean data). Windows ops tool shipped:
> `scripts/tail-v320-gate.ps1` (paste.rs/TrxPq, sha 985e9b11).**

"""


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def _write(p, body):
    bak = p + ".bak." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    os.rename(p, bak)
    Path(p).write_text(body, encoding="utf-8")
    return bak


def _plan(path, anchor, text, name):
    if not os.path.exists(path):
        return None, f"MISSING: {path}"
    body = _read(path)
    first_marker = text.strip().split("\n", 1)[0]
    if first_marker in body:
        return None, "ALREADY APPLIED"
    if anchor not in body:
        return None, "ANCHOR NOT FOUND"
    return body.replace(anchor, text + anchor, 1), "OK"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    plans = [
        (CHANGELOG, CHANGELOG_ANCHOR, CHANGELOG_PREPEND, "CHANGELOG.md"),
        (PRD, PRD_ANCHOR, PRD_PREPEND, "PRD.md"),
    ]
    blocked = False
    for path, anchor, text, name in plans:
        new, status = _plan(path, anchor, text, name)
        print(f"  [{name:>14}] {status}")
        if status not in ("OK", "ALREADY APPLIED"):
            blocked = True
        if args.apply and new is not None:
            bak = _write(path, new)
            print(f"                  wrote · backup at {os.path.basename(bak)}")
    if blocked and args.apply:
        print("\n  Some files blocked; partial apply may have occurred above.")
        sys.exit(2)
    if args.check:
        print("\n  re-run with --apply to write.")


if __name__ == "__main__":
    main()
