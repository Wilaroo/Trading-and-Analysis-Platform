#!/usr/bin/env python3
"""patch_memory_docs_v320fg.py  —  2026-06-16

Syncs the v320f + v320g session memory updates into:
  • memory/CHANGELOG.md  (prepend new top-section, anchored on the v6/15
    entry that's currently the top entry on the DGX)
  • memory/PRD.md        (prepend a new top-banner before the existing
    2026-06-15 P-WIRE banner)

ANCHORED EDITS (no full-file SHA256 — those big docs drift between agents).
Each edit asserts a unique string anchor exists; aborts cleanly on drift.

FLAGS:
  --check   Dry-run. Prints anchor matches + what would be inserted.
  --apply   Writes the edits (with .bak side-files).
"""
import argparse
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.expanduser("~/Trading-and-Analysis-Platform")
CHANGELOG_PATH = os.path.join(REPO_ROOT, "memory", "CHANGELOG.md")
PRD_PATH = os.path.join(REPO_ROOT, "memory", "PRD.md")

# Anchor must be unique to the existing top entry on the DGX so we KNOW
# we're prepending in the right spot.
CHANGELOG_ANCHOR = "## 2026-06-15 (evening) — P-WIRE Phase 2 investigation + Issue 2 backfill enqueued"

PRD_ANCHOR = "> **🔜 2026-06-15 — P-WIRE Phase 2 INVESTIGATION COMPLETE."

# ---------------------------------------------------------------------------
# NEW CONTENT
# ---------------------------------------------------------------------------
CHANGELOG_PREPEND = """## 2026-06-16 — v320f mislabel cleanup APPLIED + v320g SPCX surgical repair APPLIED

### v19.34.320f-fix1 — Mislabeled-bar relabel/dedup/quarantine (paste.rs/uB64p, sha 7b4812b2)

Resolves Issue 2 from prior fork (handoff): 386,919 `bar_size='1 day'` rows in
`ib_historical_data` whose `date` field was a full timestamp (len > 10) —
i.e., 1-minute bars wearing a daily label. Prior sample diag projected that
a bulk DELETE would have lost ~250k unique 1-min records.

**Outcome (FINISHED block):**
- pre: 386,919 → post: 0 mislabeled rows
- `unique_relabel`: **251,551** — rows with no 1-min sibling; `bar_size` flipped to `'1 min'`
- `exact_delete`: **95,242** — true OHLCV-identical duplicates of an existing 1-min sibling
- `partial_stage`: **40,126** — sibling exists but OHLCV drifts (likely consolidated-tape vs single-exchange feed; ~9–11% of population); QUARANTINED via `bar_size='partial_review_v320f'`, full doc copied to `ib_historical_data_partial_review` (preserving the potentially-better high-volume data for operator triage)
- audit: `mislabel_relabel_audit_v320f` collection holds all 386,919 actions with `_v320f_id`, original snapshots, drift_keys → full `--rollback` available
- Runtime: ~10 min @ ~600/s on the DGX

**Drift analysis (from `diag_mislabeled_bars_relabel_plan.py`):** top-25 symbols
each had exactly 1,950 rows (= 5 trading days × 390 RTH minutes), proving a
single systematic bad backfill batch in mid-March 2026. Partial-bucket rows
all showed mislabeled volume 2–10× higher than 1-min siblings — consistent
with a consolidated-tape feed vs single-exchange canonical.

**Design:** `--check / --apply / --resume / --rollback / --status`, batched
in 1,000-row chunks with `/tmp/v320f_relabel_checkpoint.json` resumability,
per-row sibling re-probe at apply time (handles race conditions), unique-idx
collision auto-downgrade-to-delete branch. Self-SHA256 stamped on audit
rows.

### v19.34.320g — SPCX `id=31651c71` surgical close-side rebuild (paste.rs/BhyZn, sha 9713042a)

Resolves Issue 1 from prior fork: a single SPCX `bot_trades` row closed by
the v19.31-era OCA-external close path which updated `realized_pnl`
(using `fill_price=172.59` as the entry basis) but left `exit_price`,
`net_pnl`, and `pnl_pct` un-finalized.

**Outcome (read-back verified):**
- `exit_price`: None → **189.30** (canonical from `ib_executions` order_id=408355, exec_id=00025b49.6a36c069.01.01, SELL 42sh @ 189.30 @ 2026-06-15T19:50:00Z)
- `net_pnl`: -1.00 → **698.65** (= realized_pnl 699.65 − total_commissions 1.00)
- `pnl_pct`: 9.0909 → **9.68** (= (189.30 − 172.59) / 172.59 × 100)
- `realized_pnl=699.65` left unchanged (already internally consistent: `(189.25−172.59)*42=699.72` within 5¢ rounding of IB exec)
- audit `_id=6a30e419caab658cd0b24668` in `bot_trades_repair_audit_v320g` with embedded IB exec ref + full before/after + `expected_before` snapshot for replay

**Safety:** Apply verified all 13 preconditions (`symbol/direction/shares/status/entry_price/fill_price/exit_price/realized_pnl/net_pnl/pnl_pct/total_commissions/entered_by/close_reason`) before any write. Update filter included `EXPECTED_BEFORE` values as a race-guard. Audit row inserted BEFORE the update for crash-safety. Read-back verify PASS.

### Both repairs are reversible
```bash
.venv/bin/python backend/scripts/repair_v320f_relabel_mislabeled_bars.py --rollback
.venv/bin/python backend/scripts/repair_v320g_spcx_exit_backfill.py --rollback
```

### Scripts delivered this session
- `backend/scripts/diag_v320g_spcx_exit_lookup.py` (paste.rs/4Roce, sha 02f7f76c) — READ-ONLY SPCX exit_price triangulation across ib_executions + bot_orders + back-calc.
- `backend/scripts/repair_v320f_relabel_mislabeled_bars.py` (paste.rs/uB64p, sha 7b4812b2) — applied to 386,919 rows.
- `backend/scripts/repair_v320g_spcx_exit_backfill.py` (paste.rs/BhyZn, sha 9713042a) — applied to 1 row.

### Pending follow-up
- Operator review of the 40,126 quarantined rows in `ib_historical_data_partial_review`. Each has full `ohlcv_1min_existing` snapshot — operator decides which feed (high-volume mislabeled vs low-volume canonical) should be promoted.
- Issue 3 (Atlas credentials rotation) — still USER VERIFICATION PENDING.

---

"""

PRD_PREPEND = """> **🔜 2026-06-16 — Issue 1 + Issue 2 from prior fork BOTH RESOLVED.
> (1) v320f-fix1 cleanup applied to 386,919 mislabeled `ib_historical_data`
> rows: 251,551 unique 1-min bars RESCUED (relabeled), 95,242 true duplicates
> removed, 40,126 partial-OHLCV-drift rows QUARANTINED to
> `bar_size='partial_review_v320f'` (full doc preserved in
> `ib_historical_data_partial_review` — likely consolidated-tape feed vs
> single-exchange canonical, awaiting operator triage). Pre→post: 386,919→0
> mislabeled. Full `--rollback` available via `mislabel_relabel_audit_v320f`.
> (2) v320g surgical rebuild applied to SPCX `id=31651c71`:
> `exit_price` None→189.30 (from `ib_executions` order_id=408355),
> `net_pnl` -1.00→698.65, `pnl_pct` 9.09→9.68; `realized_pnl=699.65` left
> unchanged (internally consistent w/ fill_price basis); audit
> `6a30e419caab658cd0b24668`; read-back verified. Next priorities
> per backlog: P-WIRE Phase 2 (BLOCKED on ~146 more resolved shadow
> decisions), [P-TARGET] rare-regime label realignment, multi-bar-size
> shadow logging, v320c ingest-time prevention (`reqHeadTimeStamp`),
> v321 EOD Flatten Modal in V5 UI. Atlas rotation still USER VERIFICATION
> PENDING.**

"""


# ---------------------------------------------------------------------------
def _read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def _backup_and_write(p, new_content):
    bak = p + ".bak." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    os.rename(p, bak)
    with open(p, "w", encoding="utf-8") as f:
        f.write(new_content)
    return bak


def _plan(path, anchor, prepend_text):
    if not os.path.exists(path):
        return None, f"MISSING file: {path}"
    body = _read(path)
    if prepend_text.strip().split("\n", 1)[0] in body:
        return None, "ALREADY APPLIED (top text already present)"
    if anchor not in body:
        return None, f"ANCHOR NOT FOUND in {path}: {anchor!r}"
    # Find the anchor's line-start.
    idx = body.find(anchor)
    # Prepend just before the anchor.
    new = body[:idx] + prepend_text + body[idx:]
    return new, "OK"


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    plans = [
        (CHANGELOG_PATH, CHANGELOG_ANCHOR, CHANGELOG_PREPEND, "CHANGELOG.md"),
        (PRD_PATH, PRD_ANCHOR, PRD_PREPEND, "PRD.md"),
    ]
    results = []
    for path, anchor, text, name in plans:
        new, status = _plan(path, anchor, text)
        results.append((name, path, new, status))
        print(f"  [{name:>12}] {status}")
        if new is not None and args.check:
            print(f"               will prepend {len(text):,} chars before anchor.")

    if args.check:
        print("\n  re-run with --apply to write.")
        return

    # --apply
    any_blocked = any(new is None and "ALREADY APPLIED" not in status
                      for _, _, new, status in results)
    if any_blocked:
        print("\n  ABORT: one or more files are blocked (anchor missing). "
              "No writes performed.")
        sys.exit(2)
    for name, path, new, status in results:
        if new is None:
            continue  # already-applied or no-op
        bak = _backup_and_write(path, new)
        print(f"  [{name:>12}] wrote · backup at {os.path.basename(bak)}")
    print("\n  DONE.")


if __name__ == "__main__":
    main()
