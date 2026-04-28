# Setups & Trades — Bellafiore Two-Layer Playbook

> **Auto-generated reference.** Source of truth lives in
> `/app/backend/services/market_setup_classifier.py` (constants
> `TRADE_SETUP_MATRIX`, `TRADE_ALIASES`, `EXPERIMENTAL_TRADES`).
> Re-generate this file by running:
>
> ```
> python -m backend.services.market_setup_classifier --emit-md > /app/memory/SETUPS_AND_TRADES.md
> ```
> *(emit-md utility shipping in the next phase; for now this file is
> hand-edited to mirror the constants.)*

## Mental model

In Mike Bellafiore's playbook (*One Good Trade*, *The Playbook*) every
trade idea has two orthogonal layers:

| Layer | What it answers | Cadence |
|---|---|---|
| **Setup** | "What is this stock doing on the daily?" — the multi-day context that 'set up' the opportunity | Classified once per scan cycle (5-min cache), per symbol, from daily bars |
| **Trade** | "What's the specific intraday entry?" — the execution pattern: 9-EMA Scalp, VWAP Continuation, Bella Fade, … | Detected each scan cycle from intraday `TechnicalSnapshot` |

A Trade in its **with-trend** Setup is high-conviction. A Trade in a
**countertrend** Setup is a deliberate fade — still valid but the
operator is fighting the daily-context grain. A Trade fired in a Setup
the matrix has *no opinion on* gets `out_of_context_warning=True` and
its priority is downgraded by one notch.

## The 7 Setups

| Setup | Description | Detection signal | Best Trade family |
|---|---|---|---|
| **Gap & Go** (`gap_and_go`) | Big gap candle on heavy volume, expecting immediate continuation | abs(gap) ≥1.5% + ≥2× avg vol + tight prior consolidation | Momentum, Trend Continuation |
| **Range Break** (`range_break`) | Multi-day consolidation resolves with decisive breakout | 10-day range <12% + decisive close outside range + vol ≥1.5× avg | Momentum, Trend Continuation, Pullbacks |
| **Day 2** (`day_2`) | Day 1 trended >1× ATR closing top-20% of range | Day 1 range ≥1× ATR(14) AND close ≥80% up day's range AND Day 2 opens within 3% of Day 1 close | Pullbacks, Trend Continuation |
| **Gap Down Into Support** (`gap_down_into_support`) | Negative-catalyst gap landing at multi-day support | gap_pct ≤−1% AND gap-low within 1× ATR of 20-day low | Reversals (long) |
| **Gap Up Into Resistance** (`gap_up_into_resistance`) | Positive-catalyst gap landing at multi-day resistance | gap_pct ≥+1% AND gap-high within 1× ATR of 20-day high | Reversals (short) |
| **Overextension** (`overextension`) | Parabolic same-direction move, RSI extreme, far from 20-EMA | 4+ consecutive same-color candles AND >1.5× ATR from 20-EMA AND RSI extreme | Reversals (counter-direction) |
| **Volatility In Range** (`volatility_in_range`) | Wide-ATR chop with defined upper/lower bounds, no decisive break | 15-day ATR ≥1.5% AND price within range AND ≥3 touches each band | Reversals (fade range extremes) |

Plus **`neutral`** — fallback when the top setup scores below the 0.5 confidence threshold. Trades fire uncontested, no context tag.

## The 22 wired Trades (matrix-gated)

Legend: 🟢 = with-trend · 🔴 = countertrend · — = matrix has no opinion (out-of-context warning fires)

| Trade (`setup_type`) | Gap&Go | RangeBrk | Day 2 | GapDn↘Sup | GapUp↗Res | Overext | VolRng |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `the_3_30_trade` | 🟢 | — | — | — | — | — | — |
| `second_chance` | 🟢 | 🟢 | — | — | — | — | — |
| `hitchhiker` | 🟢 | 🟢 | — | — | — | — | — |
| `9_ema_scalp` | 🟢 | 🟢 | — | — | — | — | — |
| `vwap_continuation` | 🟢 | 🟢 | — | — | — | — | — |
| `gap_give_go` | 🟢 | 🟢 | — | — | — | — | — |
| `first_vwap_pullback` | 🟢 | 🟢 | — | — | — | — | — |
| `big_dog` | 🟢 | 🟢 | — | — | — | — | — |
| `bouncy_ball` | 🟢 | 🟢 | — | — | — | 🔴 | — |
| `premarket_high_break` | 🟢 | 🟢 | 🟢 | — | — | — | — |
| `back_through_open` | 🟢 | 🟢 | 🟢 | 🔴 | 🔴 | — | — |
| `range_break` | 🟢 | 🟢 | 🟢 | 🔴 | 🔴 | 🔴 | — |
| `hod_breakout` | 🟢 | 🟢 | 🟢 | — | — | — | — |
| `spencer_scalp` | — | 🟢 | 🟢 | — | — | — | — |
| `first_move_up` | — | 🟢 | 🟢 | — | 🔴 | 🔴 | 🔴 |
| `first_move_down` | — | 🟢 | 🟢 | 🔴 | — | 🔴 | 🔴 |
| `bella_fade` | — | 🟢 | 🟢 | 🔴 | 🔴 | 🔴 | 🔴 |
| `fashionably_late` | — | — | 🟢 | 🔴 | 🔴 | 🔴 | 🔴 |
| `backside` | — | — | 🟢 | 🔴 | 🔴 | 🔴 | 🔴 |
| `rubber_band` | — | — | 🟢 | 🔴 | 🔴 | 🔴 | 🔴 |
| `off_sides` | — | — | — | 🔴 | 🔴 | 🔴 | 🔴 |

## Trade aliases (deprecated → canonical)

| Old name | Redirects to | Reason |
|---|---|---|
| `puppy_dog` | `big_dog` | Same trade family, just a shorter consolidation period |
| `tidal_wave` | `bouncy_ball` | Same fail-bounce-then-break short |
| `vwap_bounce` | `first_vwap_pullback` | Operator merged these (also covers `vwap_continuation` context) |

## Experimental Trades (matrix has no opinion, alert tagged `experimental=True`)

These continue to fire in all contexts; the matrix gate is bypassed.
The operator should later decide whether to consolidate them into
matrix entries or drop them entirely.

`vwap_fade`, `abc_scalp`, `breakout`, `gap_fade`, `chart_pattern`,
`squeeze`, `mean_reversion`, `relative_strength`, `volume_capitulation`,
`approaching_hod`, `approaching_range_break`, `range_break_confirmed`

## Gating policy

The scanner currently runs in **soft mode** (operator chose option B
during the 2026-04-29 evening planning):

- 🟢 with-trend → no-op, alert as usual
- 🔴 countertrend → tag `is_countertrend=True`, priority unchanged
- — out-of-context → tag `out_of_context_warning=True`, priority
  downgraded one notch (HIGH→MEDIUM, MEDIUM→LOW), reasoning bullet
  appended explaining the mismatch

After ~2 weeks of live data, the operator can flip to **strict mode**
which would block out-of-context alerts entirely.

## API endpoint

```
GET /api/scanner/setup-trade-matrix
```

Returns the full matrix + classifier-stats live, so the UI can render
a heat-grid showing the current daily Setup distribution across the
universe.
