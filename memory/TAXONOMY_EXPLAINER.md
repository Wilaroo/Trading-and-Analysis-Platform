# How SentCom Categorizes, Scans & Evaluates Trades (v19.34.267+)

## 1. The mental model — 4 ORTHOGONAL dimensions

Every alert/trade is described by 4 independent dimensions. They don't compete;
they stack. This is the Bellafiore two-layer model + two execution dimensions.

```
        WHAT THE STOCK IS DOING            WHAT WE DO ABOUT IT
        (daily context)                     (intraday execution)
   ┌───────────────────────────┐     ┌───────────────────────────────┐
   │  ① MARKET SETUP            │     │  ② TRADE                       │
   │  (daily bars, 1×/cycle)    │     │  (intraday pattern detector)   │
   │                            │     │                                │
   │  Gap & Go                  │     │  squeeze, vwap_fade, orb,      │
   │  Range Break               │     │  bella_fade, bouncy_ball, ...  │
   │  Day 2                     │     │                                │
   │  Gap Down Into Support     │     └───────────────┬───────────────┘
   │  Gap Up Into Resistance    │                     │
   │  Overextension             │            ┌─────────┴─────────┐
   │  Volatility In Range       │            ▼                   ▼
   │  (+ Neutral)               │     ┌─────────────┐    ┌──────────────┐
   └────────────┬───────────────┘     │ ③ CLASS     │    │ ④ STYLE      │
                │                      │ (how to     │    │ (how long to │
                │                      │  manage)    │    │  hold)       │
                ▼                      │             │    │              │
        ┌───────────────┐             │ momentum    │    │ scalp        │
        │ MATRIX GATE   │◄────────────┤ fade        │    │ intraday     │
        │ with-trend?   │  ② in ① ?    │ swing       │    │ multi_day    │
        │ countertrend? │             │ position    │    │ swing        │
        │ out-of-ctx?   │             └─────────────┘    │ investment   │
        └───────────────┘                                 │ position     │
                                                          └──────────────┘
```

- **① Market Setup** = the daily-chart story. Classified once per scan cycle per
  symbol from ~30 daily bars (`market_setup_classifier`). 7 setups + Neutral.
- **② Trade** = the intraday entry pattern a detector fires (`enhanced_scanner`).
- **③ Class** *(NEW)* = the management archetype → decides the **bracket/exit logic**.
  `momentum` (tight stop + trail an EMA, ride a runner) vs `fade` (fixed two-wave
  mean-reversion, no runner) vs `swing`/`position` (held overnight, wide stop).
- **④ Style** = the holding horizon → decides sizing & EOD behavior.

**Direction (long/short)** is a 5th tag kept ON the trade for edge stats, but
**collapsed away** for every config lookup (so `vwap_fade_long` and
`vwap_fade_short` use the same stop rules but grade their edge separately).

---

## 2. The naming convention — ONE canonical name, many variants

Before, the same trade was written 4+ ways and the labels drifted into `unknown`.
Now there's a single normalizer: `setup_taxonomy.canonicalize()`.

```
  RAW STRING (whatever was stamped on the trade)
  e.g.  "Rubber Band Scalp" → stored as  rubber_band_scalp_long
                                          │
                  ┌──────────── canonicalize() ────────────┐
                  │ 1. lowercase / trim                     │
                  │ 2. strip LONGEST variant suffix:        │
                  │    _scalp_long _scalp_short _scalp       │
                  │    _long _short _buy _sell               │
                  │    _confirmed _intraday                  │
                  │ 3. apply alias table (true synonyms)     │
                  └──────────────────┬──────────────────────┘
                                     ▼
                       CANONICAL BASE = rubber_band
                                     │
            ┌────────────────────────┼─────────────────────────┐
            ▼                        ▼                          ▼
      style_of() = scalp     setup_class() = fade     is_edge_excluded() = no
```

Examples:
```
  vwap_fade_long      ─► vwap_fade      (fade,  scalp,   long)
  vwap_fade_short     ─► vwap_fade      (fade,  scalp,   short)
  mean_reversion_long ─► mean_reversion (fade,  scalp,   long)
  breakout_confirmed  ─► breakout       (momentum, intraday)
  range_break_confirmed ─► range_break  (momentum, intraday)
  big_dawg            ─► big_dog        (alias → momentum, intraday)
  reconciled_orphan   ─► (EXCLUDED from edge/grading — not a real setup)
  imported_from_ib    ─► (EXCLUDED)
```

The base name is `snake_case`, no suffix. The directional variant is what gets
stored on the BotTrade. Everything that needs *config* calls `canonicalize()`;
grading keeps the variant for direction-split edge.

---

## 3. How a single scan cycle works, end-to-end

```
 every scan cycle, per symbol in the in-play universe:

 STEP 1  CLASSIFY DAILY SETUP  ──────────────────────────────────────────
   market_setup_classifier.classify(SYM)  → e.g.  OVEREXTENSION (conf 0.71)

 STEP 2  RUN INTRADAY DETECTORS  ────────────────────────────────────────
   enhanced_scanner runs the enabled _check_* detectors on the live
   TechnicalSnapshot.  A detector fires →  setup_type = "vwap_fade_short"

 STEP 3  STAMP THE 4 DIMENSIONS  ────────────────────────────────────────
   alert.setup_type      = vwap_fade_short      (the Trade + direction)
   alert.canonical_setup = vwap_fade            (canonicalize)   ← a2
   alert.market_setup    = overextension        (the daily Setup)
   alert.class           = fade                 (setup_class)    ← a2
   alert.trade_style     = scalp                (style_of)
   alert.direction       = short

 STEP 4  MATRIX GATE  ───────────────────────────────────────────────────
   lookup_trade_context(vwap_fade, overextension)
     →  vwap_fade is a fade → COUNTERTREND is expected/with-grain here
   (soft mode today: tag is_countertrend / out_of_context_warning, adjust
    priority; does NOT block)

 STEP 5  HARD GATES (only 3, to keep ML data flowing)  ──────────────────
   • time-window valid?  (opening_drive can't fire midday)
   • in-play?            (ADV ≥ $2M, RVOL ≥ 0.8)
   • confidence gate     (predicted_R + win_prob)

 STEP 6  EXECUTE + BRACKET  ─────────────────────────────────────────────
   bracket geometry chosen by  CLASS × STYLE:
     fade  + scalp     → fixed two-wave, tight stop, NO runner   (today)
     momentum + intraday → INTRADAY_BRACKET_V2: 1.25×ATR stop,
                            1.5R first target, trail EMA, 40m time-stop  ← step c

 STEP 7  GRADE THE OUTCOME  ─────────────────────────────────────────────
   on close → roll up by CANONICAL setup:
     vwap_fade scoreboard  = vwap_fade_long + vwap_fade_short  (367 trades,
                              no longer 2 tiny buckets)
     …but edge can still drill to long vs short
   artifacts (reconciled_*, imported_from_ib) are EXCLUDED from the scoreboard
```

---

## 4. The full categorization (canonical names)

### Intraday Trades — CLASS = momentum (tight stop + EMA-trail runner)
| Trade (canonical) | SMB category | style | direction |
|---|---|---|---|
| opening_drive | trend_momentum | intraday | both |
| orb | trend_momentum | intraday | both |
| premarket_high_break | catalyst | intraday | long |
| back_through_open | catalyst | intraday | long |
| up_through_open | catalyst | intraday | long |
| vwap_continuation | trend_momentum | intraday | long |
| vwap_bounce | trend_momentum | intraday | long |
| hod_breakout | trend_momentum | intraday | long |
| breakout | trend_momentum | intraday | long |
| range_break | consolidation | intraday | both |
| squeeze | consolidation | intraday | both |
| big_dog | consolidation | intraday | both |
| chart_pattern | consolidation | intraday | both |
| bouncy_ball | reversal(breakdown) | intraday | short |
| the_3_30_trade | specialized | intraday | both |
| breaking_news | catalyst | intraday | both |
| first_vwap_pullback | catalyst | intraday | both |
| gap_give_go | trend_momentum | scalp | long |
| second_chance | pullback | scalp | both |
| hitchhiker | trend_momentum | scalp | long |
| spencer_scalp | consolidation | scalp | both |
| 9_ema_scalp | specialized | scalp | both |
| abc_scalp | specialized | scalp | both |
| fashionably_late | specialized | scalp | both |

### Intraday Trades — CLASS = fade (fixed two-wave mean-reversion, no runner)
| Trade (canonical) | SMB category | style | direction |
|---|---|---|---|
| bella_fade | reversal | scalp | both |
| first_move_up | reversal | scalp | short |
| first_move_down | reversal | scalp | long |
| backside | reversal | scalp | counter |
| rubber_band | reversal | scalp | both |
| off_sides | reversal | scalp | counter |
| vwap_fade | reversal | scalp | both |
| mean_reversion | reversal | scalp | both |
| gap_fade | reversal | scalp | counter |
| time_of_day_fade | reversal | scalp | counter |
| volume_capitulation | reversal | scalp | both |

### Higher-timeframe (second scanner) — CLASS = swing / position (held overnight)
| Trade | style | class |
|---|---|---|
| accumulation_entry, daily_breakout, daily_squeeze, day_2_continuation, gap_fill_open, trend_continuation, pocket_pivot, vcp_breakout, three_week_tight, *_flag_break, *_triangle_break, cup_with_high_handle, base_breakout | swing / multi_day | swing |
| rs_leader_break, weekly_breakout, multi_quarter_base_break, fifty_two_week_high_break, power_trend_stack | investment | position |
| stage_2_breakout, stage_1_to_2_transition, stage_3_to_4_breakdown, golden_cross_filtered, death_cross_filtered, two_hundred_day_reclaim/loss | position | position |

### Excluded from edge/grading (not real setups)
`reconciled_*`, `imported_from_ib`, `carry_forward_watch`, `approaching_*`

### ⚠️ Ambiguous — class pending your confirmation
- `puppy_dog` — "small-cap follow-the-leader" reads **momentum**, but alias of big_dog.
- `tidal_wave` — TRADING_TAXONOMY calls it "large-cap mean reversion" (**fade**) yet the matrix aliases it to bouncy_ball (**momentum**). Source docs disagree.
- `gap_pick_roll` — gap-reversal short; momentum-breakdown or fade?

---

## 5. The Trade × Setup matrix (with-trend 🟢 / countertrend 🔴)

This already exists (`TRADE_SETUP_MATRIX`, transcribed from your cheat-sheet grid).
It answers "does this Trade fit today's daily Setup?" Condensed:

```
                         Gap&Go  RangeBrk  Day2  GapDn↘  GapUp↗  Overext  VolRng
 momentum/breakout        🟢       🟢       🟢     ·       ·        ·        ·
 fades (bella/first/      ·        🟢       🟢    🔴      🔴       🔴       🔴
   rubber/off/backside)
```
🟢 with-trend = high conviction · 🔴 countertrend = deliberate fade (valid, but
fighting the daily grain) · blank = out-of-context (priority downgraded).

---

## 6. Before vs After

```
 BEFORE (5 drifting tables)                AFTER (one canonical point)
 ────────────────────────────             ────────────────────────────
 vwap_fade_long  ─► bucket A               vwap_fade_long ┐
 vwap_fade_short ─► bucket B                vwap_fade_short┼─► canonical: vwap_fade
 (367 trades split, neither significant)                  │   (1 scoreboard, 367t,
 bouncy_ball     ─► unknown style          bouncy_ball ────┘    drill to L/S edge)
 reconciled_*    ─► counted as "setup"     bouncy_ball ─► intraday ✓
 add a setup = edit 5 places               reconciled_* ─► EXCLUDED ✓
                                           add a setup = edit 1 place
```

**Net:** the *meaning* of your taxonomy didn't change — it already matched your
cheat sheets and Bellafiore. What changed is the *plumbing*: one normalizer, a
new `class` dimension for smarter brackets, and artifact exclusion so the
scoreboard reflects real edge.
