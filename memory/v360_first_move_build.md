# v360 — `first_move_up` / `first_move_down` evaluation → BOTH SUPPRESSED

**Date:** 2026-06-18
**Setups:** `first_move_up` (INT, SHORT fade of the first morning push to HOD, "MORN-01")
and `first_move_down` (INT, LONG fade of the first morning flush to LOD, "MORN-02").
**Verdict:** SUPPRESS both (`return None`) — structurally negative-EV counter-trend morning fades.
**Live file built against:** `enhanced_scanner.py` whole-file SHA
`8ff8213235dd51887ce9218b0985fb1f9a7ee9d9ce1b97edf13cf6733318af92` (operator `extract_func.py`).

## Structural finding
Both are counter-trend morning fades. `first_move_up` shorts a fresh-HOD push that is >1.5%
off the open, within 0.5% of HOD, RSI≥68, >1.0% above VWAP, rvol≥1.5; targets VWAP/open, stops
0.25·ATR above HOD. `first_move_down` is the mirror LONG (flush to LOD, RSI≤32, ≤−1.0% below
VWAP). In each case the entry gates *require* a volume-confirmed momentum thrust and then bet
on immediate mean-reversion against it — the opposite of what the validated continuation setups
(`9_ema_scalp`, `vwap_continuation`, `gap_and_go`) trade in the same window.

## Evidence
1. **Intraday replay** (`diag_v360_first_move_replay.py`, 180d / 300-sym, 5-min bars):
   | setup | dir | n | win% | winsorAvg(±5) R | medR | note |
   |---|---|---|---|---|---|---|
   | first_move_up | SHORT | 2392 | 27% | −0.106 (tightened −0.101) | −1.0 | >50% hit full stop |
   | first_move_down | LONG | 2274 | 24% | −0.176 (tightened −0.188) | −1.0 | >50% hit full stop |
   Tightening the push/RSI gates (push 2.0, RSI 72) did **not** flip either to +EV — it only
   thinned sample while EV stayed negative.
2. **Ground truth too thin to rely on** (`diag_setup_ground_truth.py`): first_move_up n=0,
   first_move_down n=2 resolved live fills — insufficient, so the replay is the verdict driver.
3. **Doctrine alignment**: consistent with the prior fade suppressions — `vwap_bounce` (v354),
   `fashionably_late` (v357), and `squeeze` (v359) were all suppressed for the same reason
   (fading momentum / negative-EV). The genuine morning edge is captured by the with-trend
   continuation trades, not these fades.

## Action
- Patcher `backend/scripts/patch_v360_first_move_suppress.py` — **dual** anchored-chunk
  patcher (whole-file PRE-SHA `8ff8213235dd…` guard + BOTH OLD-byte anchors each matched
  exactly once + post-write self-verify; `--check` dry-run; auto-backup to `*.v360.bak`).
  Swaps each function body for `return None` + a docstring citing this audit.
  - NOTE (2026-06-18): the OLD anchor base64 had three Cyrillic-homoglyph corruptions
    (`А`/`Б`/`Р` → ASCII `A`/`B`/`R`) that broke decoding; fixed, both anchors now decode to
    the exact live function source and the patcher compiles.
- Regression test `backend/tests/test_v360_first_move_suppress.py` — asserts both functions
  return None on would-fire snapshots.
- Diag: `diag_v360_first_move_replay.py`.

## Deploy (DGX, repo root)
```bash
curl -sS -o /tmp/patch_v360.py https://paste.rs/<id>
.venv/bin/python /tmp/patch_v360.py --check          # SHA + dual-anchor guard dry-run
.venv/bin/python /tmp/patch_v360.py                  # apply (auto-backup)
curl -sS -o backend/tests/test_v360_first_move_suppress.py https://paste.rs/<test-id>
.venv/bin/python -m pytest backend/tests/test_v360_first_move_suppress.py -q
git add backend/ memory/ && git commit -m "v360: suppress first_move_up/down (negative-EV morning fades)" && git push origin main
git status --short                                   # must be clean BEFORE restart
./start_backend.sh --force
```
If `--check` aborts on SHA mismatch, the DGX `enhanced_scanner.py` has drifted since extract:
re-run `extract_func.py` for both functions + the whole-file SHA, paste the output back, and
I'll rebase the anchors.

## Setups adjudicated so far (Replay→Validate template)
- v353 second_chance (re-aligned), v354 vwap_bounce (suppressed), v355 orb (rewritten),
  v356 daily_breakout (preserved +EV), v357 fashionably_late (suppressed),
  v358 daily_squeeze (long-only), v359 squeeze (suppressed),
  **v360 first_move_up + first_move_down (both suppressed).**

## Next in queue
`big_dog`, `gap_give_go`, `spencer_scalp`.
