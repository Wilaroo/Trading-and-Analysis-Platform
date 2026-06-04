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

## 6. Still needed before writing patches
- Run hosted `diag_setup_inventory.py` on DGX → exact live variant strings,
  dormant list, orphan list, unmapped list. (paste output back.)
- Operator to point at the specific cheat-sheet / gameplan-template image
  uploads (292 generic `image.png` assets — can't be auto-identified) so any
  setup detail not already in the 3 transcribed docs can be folded in.
