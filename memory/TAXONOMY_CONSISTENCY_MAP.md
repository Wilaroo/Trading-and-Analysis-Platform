# Taxonomy Consistency Map & Migration Plan (system-wide)
> Goal (operator, 2026-06): unify naming across NIA, Diagnostics, Trade Journals,
> Command Center, and the AI/bot/trade pipeline so the new canonical taxonomy +
> 2-axis class model propagate everywhere **without breaking anything**.

## 0. Governing principle — STAMP ONCE, READ EVERYWHERE (delegate, don't rewrite)

`resolve_trade_style` is imported in only ~3 places. Almost every consumer does
NOT re-classify — it **reads fields already stamped** on the alert/trade
(`setup_type`, `trade_style`, `market_setup`, `strategy_name`). So consistency
is achieved by:
  1. One SSOT module: `services/setup_taxonomy.py`.
  2. The few naming-logic OWNERS delegate to it (become thin shims).
  3. The WRITE path stamps the descriptive tags ONCE; everyone reads them.
We do NOT rewrite the ~80 reader files. Function signatures/return shapes are
preserved, so nothing downstream changes behavior unexpectedly.

## 1. Naming-logic OWNERS (the only real risk points)

| Owner | What it owns | Migration |
|---|---|---|
| `services/setup_taxonomy.py` | **SSOT**: canonicalize · is_edge_excluded · strategy_family · exit_archetype · style_of | extend (this plan) |
| `services/trade_style_classifier.py` | `SETUP_TO_STYLE`, `DIRECTIONAL_SUFFIXES` (only `_long/_short/_buy/_sell`) | `_strip_directional_suffix` → call `setup_taxonomy.canonicalize`; keep `resolve_trade_style` signature |
| `services/smb_integration.py` | `SETUP_REGISTRY` (default_style, category, direction), `SMB_SETUP_ALIASES`, `get_directional_setup_name` | aliases delegate to SSOT; registry stays as the per-setup config store but `category`→ aligned to `strategy_family` |
| `services/market_setup_classifier.py` | `TRADE_SETUP_MATRIX`, `TRADE_ALIASES`, `EXPERIMENTAL_TRADES`, daily SETUP classify (`DAILY_HISTORY_DAYS=30`) | aliases delegate to SSOT; add **horizon-aware lookback** |
| `services/enhanced_scanner.py` | `_enabled_setups`, regime maps, `_check_*` (stamps variant `setup_type` + `trade_style` + `market_setup`) | stamp `canonical_setup`/`strategy_family`/`exit_archetype` at alert build; rename `_check_tidal_wave`→`fading_bounce`; add new momentum `tidal_wave` detector |
| `services/order_policy_registry.py` | order policy per **trade_style** (TIF/TP-ladder/trail/EOD) — the IB execution path | **safe** — keyed on style, not setup; unaffected as long as style resolves right |
| `agents/vocabulary.py` | NIA/agent shared vocabulary (static prompt block); says "keep in lock-step w/ SETUP_REGISTRY + tradeStyleMeta.js" | regenerate from SSOT (add strategy_family + exit_archetype + order-policy lines) |
| `frontend/src/utils/tradeStyleMeta.js` | UI SSOT for Command Center / journals / NIA panels | feed from an SSOT-emitted JSON (`/api/sentcom/taxonomy`) so it cannot drift |
| `services/ai_modules/setup_features.py` + `short_setup_features.py` | feature extractors keyed by **FAMILY** names: `MOMENTUM/BREAKOUT/RANGE/REVERSAL/TREND_CONTINUATION/MEAN_REVERSION/ORB/VWAP/GAP_AND_GO` (+ `SHORT_*`) | **align `strategy_family` to these keys** (see §3); DO NOT silently change model input (see §4) |

## 2. READER subsystems — how each stays consistent (and why it won't break)

- **NIA** (`frontend/src/components/NIA/*`, `services/ai_assistant_service`,
  `agents/vocabulary`): reads stamped `trade_style`/`setup_type`; speaks via the
  vocabulary block. → Regenerate `vocabulary.py` from SSOT. No code-path change.
- **Diagnostics** (`routers/diagnostic_router`, `routers/diagnostics`,
  `scripts/diag_*`): read stamped fields + roll up by setup. → Switch their
  roll-up key to `canonical_setup`; exclude `is_edge_excluded`. Probes already
  import `trade_style_classifier`, which now delegates to SSOT.
- **Trade Journals** (`routers/journal_router`, `services/trade_journal`,
  `ai_journal_generation_service`): render `setup_type` + `trade_style`. → Show
  `canonical_setup` as the grouping label, variant as a sub-tag. Read-only change.
- **Command Center / Mission Control** (`SentComV5View` + v5 panels): displays
  setup chips, lanes, grades. → Consumes `/api/sentcom/taxonomy` JSON; chips show
  canonical label + direction badge. bouncy_ball fix already landed here.
- **AI / bot / trade pipeline** (`opportunity_evaluator`, `trade_executor`,
  `bot_persistence`, `tqs_engine`, `ev_tracking_service`, `landscape_grading`):
  grade/score/EV by setup. → Roll up by `canonical_setup`, drill by direction,
  exclude artifacts. Feature pipeline handled per §4.

## 3. ALIGNMENT WIN — strategy_family ↔ AI feature families

The AI extractors already use family keys. Define `strategy_family` to map onto
them so the taxonomy and the model speak the same language:

| strategy_family | AI extractor family key(s) |
|---|---|
| continuation | TREND_CONTINUATION, MOMENTUM |
| breakout | BREAKOUT, ORB, GAP_AND_GO |
| reversion | MEAN_REVERSION, VWAP (fade) |
| reversal | REVERSAL |
| rotation | RANGE |
(+ SHORT_* mirror for short direction)

This means `strategy_family` can DRIVE the feature-extractor lookup — one mapping
instead of an implicit, undocumented one.

## 4. ⚠️ The AI-feature LANDMINE (must not silently break trained models)

`get_setup_features(setup_type)` selects the extractor by name → it is **model
input**. If we start passing canonicalized/family names where the trained models
expected something else, inference shifts silently. Rules:
  - The taxonomy refactor adds `canonical_setup`/`strategy_family`/`exit_archetype`
    as NEW stamped fields. It MUST NOT change what string is fed to
    `get_setup_features` for already-trained models without a retrain.
  - Step: audit the exact `setup_type` value currently passed into
    `get_setup_features` at inference (live) vs training. If they already use the
    family keys, we map via §3 and it's a no-op. If they use raw variants, we
    keep feeding the raw variant until the next retrain, then switch to family.
  - Treat any feature-input change as a **versioned retrain**, gated by
    `post_training_validator` — never a hot edit.

## 5. New stamped fields (write path) + collision note

Add to alert build (`enhanced_scanner`) → propagated by `opportunity_evaluator`
→ persisted by `bot_persistence`/`trade_executor`:
  - `canonical_setup`  = `canonicalize(setup_type)`
  - `strategy_family`  = `setup_taxonomy.strategy_family(setup_type)`
  - `exit_archetype`   = prior from family, later MFE/MAE-overridden (§6)
**Collision note:** `canonical` already exists for *trades/positions*
(`open_canonical*`, `position_consolidator._pick_canonical`) = the representative
OPEN position for dedup. Our field is `canonical_setup` (a setup NAME) — distinct;
keep the `_setup` suffix everywhere to avoid confusion.

## 6. exit_archetype: prior → data-driven
Default per `strategy_family` (continuation/breakout→runner, reversion/reversal→
target unless flagged, swing→swing_hold, position→position_hold), then OVERRIDE
from the canonical setup's MFE/MAE distribution once N≥threshold (reuses the
reconstruction we built). Only `runner` setups get `INTRADAY_BRACKET_V2`.

## 7. Migration sequence (safe, incremental, each gated by pytest; reversible)

- **m1 ✅ DONE (v268)** SSOT extend: `strategy_family()` + `exit_archetype_prior()`
  + `ai_feature_family()` (aligned to AI extractor keys, §3). Pure addition + tests.
- **m2 ✅ DONE (v268)** Delegate: `trade_style_classifier._strip_directional_suffix`
  → `canonicalize()`. Fixes `_confirmed`/`_scalp_long`/alias style misses; raw-first
  lookup protects explicit entries (breakdown_confirmed stays multi_day). 30 tests green.
  Applier: paste.rs/FWeV5. (smb/market_setup TRADE_ALIASES intentionally NOT collapsed —
  they carry matrix-context semantics + the tidal_wave alias is fixed in m8.)
- **m3** Write-path stamping of `canonical_setup`/`strategy_family`/`exit_archetype`
  (additive fields; nothing reads them destructively yet).
- **m3 ✅ DONE (v269)** Write-path stamping: `LiveAlert.__post_init__` stamps
  `canonical_setup`/`strategy_family`/`exit_archetype` on every alert; `to_dict()`
  serializes them → feed/NIA/Command Center/alert_outcomes. Additive; trades derive
  on-read in m5 (no backfill). Applier paste.rs/YJAP1; 5 tests green; patch verified
  byte-identical on unpatched copy.
- **m4** `/api/sentcom/taxonomy` JSON emitter + regenerate `vocabulary.py` +
  point `tradeStyleMeta.js` at it. NIA/Command Center/journals now SSOT-fed.
- **m5** Diagnostics/grading/EV roll-up by `canonical_setup` + artifact exclusion.
- **m6** AI-feature audit (§4) — map or defer-to-retrain; NO silent change.
- **m7** Horizon-aware Market-Setup lookback (30→252→504 by style).
- **m8** tidal_wave: rename detector→`fading_bounce`; build new momentum
  `tidal_wave` detector (researched triggers).
- **m9** exit_archetype data-override from MFE/MAE → then INTRADAY_BRACKET_V2 for
  `runner` class, validated against the full IB order/bracket/reconcile path.

Every step ships as an idempotent paste.rs applier + pytest; behavior-changing
steps (m5–m9) are env-flagged where they touch live execution.

## 8. "Why nothing breaks" summary
- Readers untouched (read same stamped fields; new fields additive).
- Owners delegate (same signatures/returns).
- order_policy_registry keyed on style → unaffected.
- AI model input frozen until an explicit versioned retrain.
- Frontend fed by emitted JSON (can't drift from backend).
