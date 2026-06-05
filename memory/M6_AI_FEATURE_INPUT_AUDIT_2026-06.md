# m6 — AI Feature-Input Audit (setup_type → trained-model surface)

**Purpose:** before any setup rename/split (m8) or retrain, enumerate every place a
`setup_type` string crosses into a TRAINED-MODEL input or a gate that changes
sizing/blocking, so we never silently corrupt model inputs. Read-only audit.

Date: 2026-06 · Scope: `tidal_wave` split + general guardrail.

---

## 1. The setup_type → model-input chain (THE critical path)

`enhanced_scanner` stamps `LiveAlert.setup_type` (raw, e.g. `tidal_wave`,
`vwap_fade_long`). Downstream:

| Stage | File | How setup_type is used | Model input? |
|------|------|------------------------|--------------|
| Ensemble routing | `ai_modules/ensemble_live_inference.py` `SCANNER_TO_ENSEMBLE_KEY` (L88) + `predict_meta_label_p_win` (L192) | `base = upper().strip(_LONG/_SHORT)` → maps to ONE ensemble config key (VWAP/BREAKOUT/MOMENTUM/MEAN_REVERSION/…). Decides **which trained ensemble head** is queried; result feeds `extract_ensemble_features` → meta-labeler XGB. | **YES — routes to a trained head + becomes a feature** |
| Model consensus gate | `ai_modules/confidence_gate.py` `_query_model_consensus` (L1012, L1035 `SETUP_TO_MODEL`) | `base` → allowed model families (e.g. `TIDAL_WAVE → [MOMENTUM, BREAKOUT]`). Filters which model votes count. | **YES — gates model votes (sizing/score)** |
| Learning feedback | `confidence_gate._get_learning_feedback` (L1189) → `learning_loop.get_contextual_win_rate(base)` | base key lookup into the **corrected canonical store** (m5). | Indirect (score pillar) |
| CNN / live pred | `confidence_gate._get_cnn_signal`, `_get_live_prediction` | symbol+setup_type+direction passed; direction derived partly from `"SHORT" in setup_type.upper()` (L1013). | Direction inference |
| TQS setup pillar | `tqs/setup_quality._canonical_base_setup` (m5) | canonical base → win_rate/EV from corrected store. | Score pillar |

**`feature_engine.py` does NOT one-hot setup_type** (only a docstring mention). The
only categorical model exposure is the **family routing** above — a coarse bucket,
not a per-setup one-hot. That is the saving grace: an unknown/new setup name
degrades gracefully to a default/pass-through head; it does not crash inference.

## 2. SSOT already models all of this (services/setup_taxonomy.py)

- `setup_class(raw)` → momentum | fade | swing | position
- `strategy_family(raw)` → continuation | breakout | reversion | reversal
- `exit_archetype_prior(raw)` → runner | target | swing_hold | position_hold  ← drives Issue 2 INTRADAY_BRACKET_V2
- `_FAMILY_TO_AI_KEY` → family → ensemble key (reversion→MEAN_REVERSION, …)

`tidal_wave` is currently in `_FADE_CLASS` + `_REVERSION_FAMILY` with an explicit
in-code note: *"standard-usage 'tidal wave' is a momentum surge — see m8 split."*
i.e. the SSOT was pre-staged for this exact change.

## 3. Mismatch m8 fixes

Today: detector `_check_tidal_wave` fires **reversion shorts** (downtrend, below
VWAP, near support) BUT `SCANNER_TO_ENSEMBLE_KEY["TIDAL_WAVE"] = "MOMENTUM"` and
`confidence_gate` gates it as MOMENTUM/BREAKOUT. → reversion trades scored by the
**wrong (momentum) ensemble head**, and grades/EV/learning historically bucketed
fade trades under a "momentum" label.

## 4. m8 required edits (derived from this audit — safe surface)

1. **Rename reversion detector** `_check_tidal_wave`→`_check_fading_bounce`,
   `setup_type "tidal_wave"→"fading_bounce"`. Add `fading_bounce` everywhere
   `tidal_wave` lived as the *reversion* concept (taxonomy `_FADE_CLASS` /
   `_REVERSION_FAMILY`, smb_integration SetupConfig, scanner registries L152/216/
   963/987/3399/3476/3518, trade_style_classifier, ev_tracking list, bot_service,
   trading_intelligence, market_setup_classifier, server.py L1233).
2. **Reassign `tidal_wave` → momentum**: move it to a momentum class/continuation
   family in the SSOT so `_FAMILY_TO_AI_KEY`/`SCANNER_TO_ENSEMBLE_KEY` MOMENTUM
   routing becomes CORRECT (the existing `"TIDAL_WAVE":"MOMENTUM"` entry now
   matches reality — no AI-map edit needed for tidal_wave).
3. **Add ensemble routing for the new label**:
   `SCANNER_TO_ENSEMBLE_KEY["FADING_BOUNCE"] = "MEAN_REVERSION"` and
   `confidence_gate SETUP_TO_MODEL["FADING_BOUNCE"] = ["MEAN_REVERSION","REVERSAL"]`
   so the renamed reversion trades route to the RIGHT head.
4. **Build the true `tidal_wave` momentum detector**: extended move + RVOL spike +
   volume expanding INTO the move + range break (long bias on up-surge).
5. **DATA MIGRATION (must)**: historical `bot_trades` / `alert_outcomes` /
   `setup_grade_records` / `ev_tracking` / `learning_stats` rows with
   `setup_type == "tidal_wave"` are actually FADES → migrate to `fading_bounce`
   so the new momentum bucket starts clean. (One-shot backfill, dry-run first.)

## 5. Retrain implication (defer, non-blocking)

The trained ensembles were fit with the OLD labeling. After m8, `fading_bounce`
routes to MEAN_REVERSION and the new `tidal_wave` to MOMENTUM — correct going
forward, but the heads won't have learned the *new* tidal_wave momentum
distribution until a **retrain**. System keeps running (graceful). Flag a retrain
once enough new-label samples accrue. NEVER feed canonical/family names as a
NEW one-hot feature without a retrain.

## 6. Guardrail rule (for all future setup edits)

Before renaming/adding a setup: (a) add it to `setup_taxonomy` class+family+
archetype, (b) add `SCANNER_TO_ENSEMBLE_KEY` + `confidence_gate SETUP_TO_MODEL`
routing, (c) migrate historical rows if semantics changed, (d) note retrain if the
return distribution of an existing label changed.
