# v391 — TQS Sub-Score Descriptor Layer + 2 Data-Integrity Fixes (2026-06-18)

## Why
Operator audit (HBAN readout as punchlist): two pillars emitted FALSE-positive
signals from absent data, and the raw 0-100 sub-scores were opaque ("VIX 85 — is
that good?"). Goal: every sub-score gets a plain-language verdict + the actual
reading, and the false positives are killed.

## Changes
New: `backend/services/tqs/descriptors.py` — `verdict_for(score)` band
(Strong/Favorable/Neutral/Caution/Weak/No-data) + helpers (vix_descriptor,
weekday_name, humanize).

Each pillar `to_dict()` now emits a `display` block per sub-score:
`{label, verdict, reading}` built from raw values it already holds. Stored on
the alert inside `tqs_breakdown` (no recompute on drill-down).

### Integrity fixes (folded in)
1. **Fundamental/Institutional** — when ownership data is absent, no longer
   scores the placeholder default 50% through the 40-70 "ideal" band (which
   emitted a fake `"Good institutional ownership (50%) (+)"` factor). Guarded
   with `if not _inst_absent`. Reading → "No institutional data", verdict "No data".
2. **Execution/Entry-Tendency** — entry slippage/chase only come from the EOD
   `trader_profiles` batch; when empty, slippage defaulted to 0.0 → scored 85 +
   "Excellent entry execution (+)" (absence reported as excellence). Now
   neutralises to 50 + "No entry-execution data yet" when `not profile_has_data`.
3. **Setup/EV** — honest reading "Est. from R:R · no live expectancy" + verdict
   "No data" when the R:R proxy is used (it's used book-wide; `strategy_ev_r` is
   never stamped).

### UI reveals
- v389 **Financial** sub-score and the **AI-model** alignment sub-score are now
  exposed as components (were factor-only / hidden) → they render automatically.

### Frontend
`frontend/src/components/sentcom/v5/TqsPillarPanel.jsx` — renders verdict chip
(colour-mapped) + reading per sub-score; falls back to the old compact grid for
legacy alerts that lack a `display` block.

## Expected score effect
Removing the two false positives slightly LOWERS scores where they were
inflating: institutional (was a fake +) and entry-tendency (85→50 when no data).
This is the integrity fix working as intended.

## Files / SHAs (PRE → POST)
- descriptors.py NEW → 365fb732
- scripts/test_tqs_descriptors.py NEW (verification harness)
- setup_quality.py 83f8077e → c1ca9193
- technical_quality.py f0f529f3 → 1de445fc
- fundamental_quality.py 311679c1 → 31b5f7c6
- context_quality.py d979b933 → 2db8ff56
- execution_quality.py 55fe7985 → cf34fea9
- TqsPillarPanel.jsx 254aa323 → 8aca2854

## Deploy
paste.rs patcher: https://paste.rs/CGxg0  (gzip+base64, PRE-SHA drift guard,
.bak.v391 backups). Run from repo root:
  .venv/bin/python backend/scripts/patch_v391_tqs_descriptors.py --check
  .venv/bin/python backend/scripts/patch_v391_tqs_descriptors.py
  ./start_backend.sh --force   + rebuild frontend
Verify live: PYTHONPATH=backend .venv/bin/python backend/scripts/test_tqs_descriptors.py

## Tested
Local sandbox (no IB/Mongo): all 5 pillars produce display blocks; institutional
& entry-tendency honesty assertions PASS; full engine `calculate_tqs().to_dict()`
clean. Live DGX visual verification pending operator apply + frontend rebuild.

## Audit follow-ups still OPEN (🟠 blind defaults, diag-first)
- EV: wire `strategy_ev_r` onto alerts (or keep proxy, now honestly labeled).
- Tape (else-30), Sector (rank-6→50), RVOL (1.0→60), Pattern taxonomy gap
  (trend_continuation + others unmapped in SETUP_BASE_SCORES) — propose ONE
  read-only DGX diag measuring book-wide default-vs-real rates before fixing.
- Issue 2: wire IB fundamental warm-fill into scheduler_service.py (nightly).
