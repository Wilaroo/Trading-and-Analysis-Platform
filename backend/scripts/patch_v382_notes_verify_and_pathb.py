#!/usr/bin/env python3
"""
patch_v382_notes — memory/CHANGELOG.md + memory/ROADMAP.md notes ONLY.

Records, in the durable repo notes, that:
  - v379 (smart_filter grade-gate) is LIVE-VERIFIED post-restart,
  - v381 (dedup mark_fired post-trade) is LIVE-VERIFIED post-restart,
  - the Path B read-only probe diag_v382_tqs_pillar_compression.py shipped.

WHY this is a notes-only ANCHOR patcher (not a SHA byte-guard):
  per AGENTS.md §0.5 rule #5, the append-only CHANGELOG legitimately diverges
  between DGX / repo / sandbox. So we PREPEND by anchor and are idempotent on a
  version marker — we do NOT pin a full-file SHA (that would false-abort on a
  same-day entry the other side lacks). No backend code is touched here; the
  v379/v381 CODE changes were already applied + pushed via their own patchers.

Usage (DGX, repo root):
  .venv/bin/python backend/scripts/patch_v382_notes_verify_and_pathb.py --check
  .venv/bin/python backend/scripts/patch_v382_notes_verify_and_pathb.py
  .venv/bin/python backend/scripts/patch_v382_notes_verify_and_pathb.py --rollback
"""
import sys
from pathlib import Path

CHANGELOG = Path("memory/CHANGELOG.md")
ROADMAP = Path("memory/ROADMAP.md")

# ---- CHANGELOG: idempotency marker + insertion anchor + the block to prepend ----
CL_MARKER = "v382 TQS Path B probe shipped"
CL_ANCHOR = "## 2026-06-18 — v381 DEDUP mark_fired POST-TRADE"
CL_BLOCK = """## 2026-06-18 — v382 TQS Path B probe shipped + v379/v381 LIVE-VERIFIED + diag `--since` filter
Both prior fixes confirmed correct on post-restart (18:43 UTC) live data; Path B read-only probe built.

### v381 (dedup mark_fired post-trade) — \u2705 LIVE-VERIFIED
`diag_v380 --days 1 --since "2026-06-18 18:43"` \u2192 `dedup_cooldown` drops = **0** (the dominant
`BLOCKED_NO_TRADE_DAY` class collapsed from 92.9% to 0). After v381 the cooldown can only be *created*
when a trade actually opens, so phantom cooldowns for never-traded keys are gone. (Full-RTH re-confirm
next session with plain `--days 1`.)

### v379 (smart_filter grade-gate) — \u2705 LIVE-VERIFIED
`diag_v379 --days 1 --since "2026-06-18 18:43"` \u2192 **0** borderline `"TQS (X)\u2026threshold (75)"` skips
(the impossible gate is gone); the only 3 smart_filter_skips are the legit low-win-rate branch
(`win<0.35` / neg-EV \u2014 a different, correct gate v379 doesn't touch). Borderline band no longer
hard-blocks. (~30 min late-afternoon sample; full-RTH re-confirm next session.)

### Tooling
- `diag_v379`/`diag_v380` gained a `--since "YYYY-MM-DD HH:MM"` (UTC) filter to isolate
  post-restart-only drops from same-day pre-fix residue.
- **`diag_v382_tqs_pillar_compression.py`** (READ-ONLY) shipped for **Path B** scoping (paste.rs/Aw9pa):
  dumps per-pillar score distributions (setup/technical/fundamental/context/execution) + composite,
  the absent-fundamental\u219250 pinning %, the `TQS_SETUP_DECOMPRESS` neutral-50 %, and composite
  grade-floor headroom. **NEXT:** run on DGX (`--days 5`) to scope the TQS de-compression math before
  touching any scoring.


"""

# ---- ROADMAP: replace the stale "NEXT SESSION" verify bullets with the verified state ----
RM_OLD = """## \U0001f534 NEXT SESSION (after 2026-06-18)
- **P1 — VERIFY v379 (smart_filter grade-gate) live:** APPLIED on DGX (paste.rs/ow794), restart +
  RTH pending. After restart, `diag_v379_smartfilter_input_probe.py --days 1` \u2192 borderline skips
  should reason on the calibrated GRADE (not the mislabeled "TQS (60)"); B-grade borderlines should
  fire. Tune live with SMART_FILTER_BORDERLINE_MIN_GRADE=C|B|A (no redeploy). Rollback: patcher --rollback.
- **P1 — Issue 4: dedup_cooldown blocking continuation re-entries** (HON all-day trend). Investigate
  why dedup blocks valid re-entries on trending names. (Was queued after Issue 3 = now v379.)
- **P1 — Path B: de-compress the TQS scale itself** (the deeper root cause behind v379). Turn off
  TQS_SETUP_DECOMPRESS once v310 C-1 confirmably feeds real SMB; re-baseline absent-fundamental\u219250 so
  the raw composite spans 0-100. Re-rates the whole book \u2192 own validation pass (grade dist pre/post)."""
RM_NEW = """## \U0001f534 NEXT SESSION (after 2026-06-18)
- \u2705 **P1 — v379 (smart_filter grade-gate) — LIVE-VERIFIED** (post-restart 18:43 UTC): 0 borderline
  "TQS (X)\u2026threshold(75)" skips; only legit low-win-rate skips remain. Full-RTH re-confirm next session
  (plain `diag_v379 --days 1`); tune live with SMART_FILTER_BORDERLINE_MIN_GRADE=C|B|A if needed.
- \u2705 **P1 — Issue 4 / v381 (dedup mark_fired post-trade) — LIVE-VERIFIED** (post-restart): dedup_cooldown
  drops = 0 (BLOCKED_NO_TRADE_DAY collapsed 92.9%\u21920). Full-RTH re-confirm next session.
- \U0001f7e1 **P1 — Path B: de-compress the TQS scale itself** (the deeper root cause behind v379) — **ACTIVE**.
  Read-only probe `diag_v382_tqs_pillar_compression.py` SHIPPED (paste.rs/Aw9pa). NEXT: run on DGX
  (`--days 5`), read per-pillar stdev + absent-fundamental-50 pinning %, THEN scope the math:"""
RM_MARKER = "v381 (dedup mark_fired post-trade) — LIVE-VERIFIED**"


def _apply(check: bool) -> int:
    if not CHANGELOG.exists() or not ROADMAP.exists():
        print("ABORT: run from the repo root (memory/CHANGELOG.md + memory/ROADMAP.md not found).")
        return 2

    cl = CHANGELOG.read_text()
    rm = ROADMAP.read_text()
    cl_new, rm_new = cl, rm
    cl_changed = rm_changed = False

    # CHANGELOG prepend (idempotent on marker)
    if CL_MARKER in cl:
        print("CHANGELOG: already has v382 block — skip.")
    elif CL_ANCHOR in cl:
        cl_new = cl.replace(CL_ANCHOR, CL_BLOCK + CL_ANCHOR, 1)
        cl_changed = True
        print("CHANGELOG: will prepend v382 block above the v381 entry.")
    else:
        print("ABORT: CHANGELOG anchor not found (divergence). Upload your copy:")
        print("       curl --data-binary @memory/CHANGELOG.md https://paste.rs/  — and rebuild.")
        return 3

    # ROADMAP replace (idempotent on marker)
    if RM_MARKER in rm:
        print("ROADMAP: already marks v379/v381 verified — skip.")
    elif RM_OLD in rm:
        rm_new = rm.replace(RM_OLD, RM_NEW, 1)
        rm_changed = True
        print("ROADMAP: will mark v379/v381 LIVE-VERIFIED + Path B ACTIVE.")
    else:
        print("ABORT: ROADMAP 'NEXT SESSION (after 2026-06-18)' block not found verbatim (divergence).")
        print("       Upload your copy: curl --data-binary @memory/ROADMAP.md https://paste.rs/")
        return 4

    if check:
        print("\n--check OK (no writes). Re-run without --check to apply.")
        return 0

    if cl_changed:
        CHANGELOG.with_suffix(".md.bak.v382").write_text(cl)
        CHANGELOG.write_text(cl_new)
        print(f"WROTE {CHANGELOG} (backup .md.bak.v382)")
    if rm_changed:
        ROADMAP.with_suffix(".md.bak.v382").write_text(rm)
        ROADMAP.write_text(rm_new)
        print(f"WROTE {ROADMAP} (backup .md.bak.v382)")
    print("DONE. Now: git add -A && git commit && git push origin main")
    return 0


def _rollback() -> int:
    n = 0
    for f in (CHANGELOG, ROADMAP):
        bak = f.with_suffix(".md.bak.v382")
        if bak.exists():
            f.write_text(bak.read_text())
            bak.unlink()
            print(f"ROLLED BACK {f}")
            n += 1
    if not n:
        print("No .bak.v382 backups found — nothing to roll back.")
    return 0


if __name__ == "__main__":
    if "--rollback" in sys.argv:
        sys.exit(_rollback())
    sys.exit(_apply(check="--check" in sys.argv))
