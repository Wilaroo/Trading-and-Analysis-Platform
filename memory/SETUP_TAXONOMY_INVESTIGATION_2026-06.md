# Setup / Trade / Style / Variant — Taxonomy Investigation (2026-06)

> Triggered by: operator noticed `rubber_band_long` (and peers) missing from the
> bracket backtest. Root question: "how are trades / setups / styles / variants
> labeled, and how should they be reclassified / merged vs Bellafiore?"
> This doc is the investigation; the applier patches come after the DGX audit.

## 1. The real problem: FIVE parallel, drifting taxonomies

There is no single source of truth. The same concept is encoded in 5 places that
do **not** agree, each with its own alias table and its own suffix-stripping:

| # | Location | What it keys on | Alias mechanism |
|---|----------|-----------------|-----------------|
| 1 | `enhanced_scanner._enabled_setups` (38) | **base** names (`rubber_band`, `vwap_fade`, `mean_reversion`) | none |
| 2 | `enhanced_scanner._check_*` detectors | stamps **directional variants** on the alert/trade `setup_type`: `rubber_band_long` (L3654), `vwap_fade_long` (L3812), `mean_reversion_long` (L4687), `off_sides_short`, `*_confirmed` | `split("_long")[0].split("_short")[0]` ad-hoc at L3252 / L1849 / L7534 |
| 3 | `smb_integration.SETUP_REGISTRY` (~50) | has BOTH base + `_long`/`_short` as separate configs; `category`, `default_style`, `direction` | `SMB_SETUP_ALIASES` (big_dawg→big_dog, gap_and_go→gap_give_go, bounce→rubber_band, stuffed→off_sides, scalp→spencer_scalp, market_play→hitchhiker, opening_range_breakout→orb…) + `get_directional_setup_name()` |
| 4 | `market_setup_classifier` | canonical trade names in `TRADE_SETUP_MATRIX` | `TRADE_ALIASES` (puppy_dog→big_dog, tidal_wave→bouncy_ball, vwap_bounce→first_vwap_pullback) + `EXPERIMENTAL_TRADES` |
| 5 | `trade_style_classifier.SETUP_TO_STYLE` (+ frontend `tradeStyleMeta.js`) | base names → style bucket | `STYLE_ALIAS` + `DIRECTIONAL_SUFFIXES` = only (`_long`,`_short`,`_buy`,`_sell`) |

**Consequence:** a single new setup or variant must be hand-edited in up to 5
places (incl. JS) or it silently degrades to `unknown` → wrong style → wrong
horizon/bracket/sizing → dropped from grading and backtests.

## 2. Concrete defects this causes

A. **Suffix-strip gaps in the Style map (#5).** It strips only `_long/_short/_buy/_sell`:
   - `rubber_band_long`, `vwap_fade_long/short`, `mean_reversion_long`, `off_sides_short` → resolve OK.
   - `range_break_confirmed`, `breakout_confirmed` → **NOT** stripped, **NOT** mapped → `unknown`.
     (`breakdown_confirmed` happens to be mapped to multi_day; its siblings are not.)
   - **Open question for the audit:** the operator referenced `rubber_band_scalp_long`
     (a `_scalp_long` *infix*). Current code emits only `rubber_band_long`. Either
     older code wrote `_scalp_long` rows that still live in `bot_trades`, or it was
     an approximation. `diag_setup_inventory.py` (hosted) settles this empirically.

B. **Aliases not applied at stats/grading time.** `puppy_dog`, `tidal_wave`,
   `vwap_bounce` are enabled AND fire as their own `setup_type`, but the matrix
   treats them as aliases → their trades are graded as separate buckets from
   `big_dog`/`bouncy_ball`/`first_vwap_pullback`. Sample sizes fragment; no
   bucket reaches significance.

C. **Variant split fragments direction stats.** `vwap_fade_long` + `vwap_fade_short`
   graded as two tiny buckets even though config (style/stop/bracket) is identical.
   (Backtest already showed long +90 vs short +43 — direction DOES matter for
   *edge*, but NOT for *config lookup*.)

D. **`category` (SMB) never flows through.** `SetupConfig.category`
   (trend_momentum/catalyst_driven/reversal/consolidation/specialized) exists in
   the registry but is not stamped on the alert/trade, so grading/EV can't roll
   up by category and the bracket-V2 "momentum class" scope has nothing canonical
   to filter on.

## 3. Bellafiore alignment (research + uploaded docs)

Sources: `documents/TRADING_TAXONOMY.md`, `documents/SMB_INTEGRATION_ANALYSIS.md`,
`memory/SETUPS_AND_TRADES.md`, *One Good Trade* / *The Playbook* (web).

- **Two-layer Setup(daily) × Trade(intraday) model is faithful to Bellafiore.** Keep it.
- Bellafiore playbook families ≈ our 5 categories:
  reversal · fade · momentum/continuation · scalp · pullback/support · intraday-level · breakout.
  Our `SetupCategory` (trend_momentum / catalyst_driven / reversal / consolidation /
  specialized) maps cleanly — only "fade" vs "reversal" are merged in ours (fine).
- **Execution Style** (scalp / intraday / multi_day / swing / investment / position)
  is correctly modeled as ORTHOGONAL to setup category. The bug is purely that
  directional-variant naming pollutes the Style lookup, not the model itself.
- SMB's M2M/T2H/A+ are *style + grade*, already absorbed (scalp/intraday + A/B/C grade).

**Net:** the conceptual model is sound and Bellafiore-faithful. The debt is
purely *naming plumbing* (5 unsynced tables), not classification theory.

## 4. Recommended target architecture (single source of truth)

Create ONE module, e.g. `services/setup_taxonomy.py`:

```
CANONICAL_SETUPS: { base_name: {
    display, category(SMB), default_style, direction_default,
    aliases: [...],            # absorbs SMB_SETUP_ALIASES + TRADE_ALIASES
    momentum_class: bool,      # drives INTRADAY_BRACKET_V2 scope
    enabled: bool,             # replaces _enabled_setups membership
} }

def canonicalize(raw_setup_type) -> base_name:
    # 1. lower/trim 2. strip ALL suffixes (_long,_short,_scalp,_scalp_long,
    #    _scalp_short,_confirmed,_intraday,_buy,_sell) 3. apply alias table
```

- `canonicalize()` is used for **config lookups only**: style, stop rule,
  bracket scope, F-gate, grading roll-up.
- Grading **keeps the raw variant** for direction-split edge stats, but also
  stores `canonical_setup` so the scoreboard can aggregate at base level AND
  drill to long/short.
- The 4 legacy maps become thin shims that import from this module (or are
  deleted after callers migrate). Frontend `tradeStyleMeta.js` stays mirrored
  but is fed by an emitted JSON so it can't drift.

## 5. Sequencing (confirms operator's option-a-first proposal)

1. **Canonicalization layer first** (this doc's §4) — unblocks everything; no behavior change beyond correct routing. Reversible.
2. **Dead-detector cleanup** — env-flagged removal of ~12 dormant detectors from `_enabled_setups` (confirm exact list from audit §A-dormant before disabling).
3. **`INTRADAY_BRACKET_V2`** — scope = `momentum_class` setups via canonical names (squeeze, vwap_continuation, vwap_bounce, gap_fade, bouncy_ball + variants); excludes faders/reversion.
4. Then Issue-3 grade math (median R, clamp risk<$1, classify_close) on the now-clean buckets.

Directional variants: **keep split for grading, canonical for config** (operator agreed; backtest justifies it).

## 5b. Operator cheat-sheet uploads located + transcribed (2026-06)

Found the playbook upload set in asset job `job_d6955c15-1754-…` (scanned all
291 image assets by brightness/white-bg; cheat sheets = tall white pages).
Confirmed the in-code taxonomy is a faithful transcription of these:

- **Source matrix image** (`c233xv23`/`qtp2fmgt`/`7rcm3v09`, dupes): the exact
  Trade × Setup grid that `TRADE_SETUP_MATRIX` came from. 20 trades × 7 setups,
  teal=with-trend, red=countertrend. **Display names end in "Scalp"**
  (Rubber Band Scalp, Off Sides Scalp, Backside Scalp, Fashionably Late Scalp,
  Second Chance Scalp, Hitchhiker Scalp, Spencer Scalp) → this is the origin of
  historical `_scalp_long`/`_scalp_short` variant strings the operator saw.
- **7 SETUP (daily) definition pages** (750×860 w/ charts): Gap & Go, Range
  Break, **Day 2** (Day-1 move >1 ATR, close top-20% range → Pullbacks/Trend-
  Continuation), Gap Down Into Support, Gap Up Into Resistance, Overextension,
  Volatility In Range — map 1:1 to `MarketSetup` enum.
- **TRADE (intraday) cheat-sheet pages** transcribed (each: why/entry/stop/exit/
  prob±/time/avoid). Key class + management detail for BRACKET_V2 scoping:
  | Trade | class | dir | exit mgmt (from cheat sheet) |
  |---|---|---|---|
  | Premarket High Break | momentum | long | hold till 9-EMA(1m) close-below |
  | Back-Through Open | momentum | long | 9-EMA(1m) close-below / 2-bar break |
  | VWAP Continuation | momentum/trend | long | ½ into HOD, trail 21-EMA(1m) |
  | Opening Range Break (ORB) | momentum/trend | both | two legs, ½+½; stop < VWAP |
  | Bouncy Ball | momentum breakdown | short | new 2-min high / 9-EMA reclaim |
  | The 3:30 Trade | momentum (power hr) | both | exit into blowoff volume |
  | First Move Up | fade/reversal (M2M) | short | two legs ½+½; stop 1¢ > HOD; 2 tries |
  | First Move Down | fade/reversal (M2M) | long | two legs ½+½; stop 1¢ < LOD; 2 tries |
  | Bella Fade | fade/reversal (M2M) | both | two waves ½+½; stop < LOD; 2 tries |

  **BRACKET_V2 implication confirmed by the operator's own rules:** momentum
  trades are managed by *trailing an EMA after 1-2 legs* (tight initial, runner),
  while fades are *fixed two-wave mean-reversion* (1 try ≈ tight, no runner).
  This is exactly the momentum-vs-fader split — the cheat sheets independently
  justify scoping INTRADAY_BRACKET_V2 to the momentum class only.

- Non-cheat-sheet brights (the wide ~1900×900 / 5059×1097 white images) are
  light-theme app UI screenshots, not playbook docs. `IMG_1304` = a Sharpe-ratio
  article. The three big `.jpeg` photos = monitor photos of the training
  dashboard.

**Conclusion:** the conceptual taxonomy already matches the operator's cheat
sheets. No reclassification of *meaning* is needed — only the naming-plumbing
unification in §4, plus carrying the cheat-sheet `class` (momentum/fade) +
`category` through to grading and bracket scope.

## 6. Still needed before writing patches
**[RESOLVED 2026-06]** — live audit ran on DGX. Results in §7.

## 7. Live DB audit results (diag_setup_inventory.py, 2026-06)

38 enabled detectors; 72 style-map entries.

**Variant splits (config-identical, graded as 2):**
- `vwap_fade_long` (177t) + `vwap_fade_short` (190t) = **367 trades** fragmented
- `mean_reversion_long/_short` (30t), `rubber_band_long/_short` (9t), `breakout`/`breakout_confirmed` (13t)
- Base names `vwap_fade`, `mean_reversion`, `rubber_band`, `off_sides`, `range_break` show "dormant" in [A] ONLY because the detector stamps the variant — they ARE active.

**bouncy_ball → UNMAPPED→unknown** (359a/33t) — FIXED (style maps + canonical).

**Edge-polluting artifacts (exclude from grading/EV):** `reconciled_excess_slice` (123t),
`reconciled_orphan` (123t), `imported_from_ib` (2t), `carry_forward_watch`, `approaching_*`.

**A whole second scanner universe fires (NOT in `_enabled_setups`)** — swing/position/investment:
`accumulation_entry` (533t), `rs_leader_break` (183t), `daily_squeeze` (132t),
`pocket_pivot` (65t), `power_trend_stack` (49t), `daily_breakout` (46t),
`stage_2_breakout` (44t), `three_week_tight` (43t), + flags/triangles/stages. Mostly
style-mapped OK; now also class-mapped (swing/position) in setup_taxonomy.

**Genuinely dormant intraday detectors (no base AND no variant firing):**
`back_through_open`, `breaking_news`, `first_move_up`, `first_vwap_pullback`,
`hitchhiker`, `spencer_scalp`, `time_of_day_fade`, `up_through_open`, plus near-dead
`9_ema_scalp` (1a/0t), `abc_scalp` (23a/0t), `the_3_30_trade` (4a/0t),
`premarket_high_break` (7a/2t), `first_move_down` (4a/0t).
→ Note most are OPENING-AUCTION (9:33-9:45) trades → hypothesis: opening-window
data/gating issue suppressing the whole opening cohort. TRIAGE (repair vs retire)
pending operator sign-off + proximity probe, NOT a blind cull.

**Top live volume (trades 90d):** squeeze 507, vwap_fade(long+short) 367,
accumulation_entry 533, rs_leader_break 183, daily_squeeze 132, gap_fade 113,
vwap_bounce 77, vwap_continuation 82, pocket_pivot 65.

## 8. Shipped — v19.34.267 step a1 (canonical taxonomy foundation)
- `services/setup_taxonomy.py` — `canonicalize()` / `is_edge_excluded()` /
  `setup_class()` / `is_momentum_class()` / `style_of()`. Pure addition.
- `tests/test_setup_taxonomy.py` — 16 tests (green).
- bouncy_ball → intraday in backend `SETUP_TO_STYLE` + frontend `tradeStyleMeta.js`.
- Applier: paste.rs/GuAUW.
- Distinct-firing setups (puppy_dog/tidal_wave/vwap_bounce) deliberately NOT merged
  (pending decision). Artifacts excluded via `is_edge_excluded`.

### Next (after sign-off)
- a2: grading/EV roll-up — stamp `canonical_setup` + `class`, exclude artifacts, dedupe variant splits.
- a3: route `trade_style_classifier` + scanner `_enabled_setups` through `canonicalize()`.
- Dormant-detector triage (esp. opening-auction cohort).
- INTRADAY_BRACKET_V2 scoped to `is_momentum_class`.
