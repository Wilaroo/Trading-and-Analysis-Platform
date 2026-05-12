# V6 Integration Index — v110 → v114
**Authored:** 2026-02-12
**Status:** Locked. Read this BEFORE starting any V6 Plan A panel extraction.

This document is the single source of truth for how the v19.34.110 →
v19.34.114 changes plug into the existing V6 specs. Every V6 panel
that touches order state, position state, or operator-facing
intelligence MUST honor the contracts in this file.

The three V6 specs already shipped — `V6_NEXT_LOCKED_SPEC.md`,
`V6_POSITION_HEALTH_CONSOLE_SPEC.md`, `V6_SAFETY_ACTIVITY_STREAM_SPEC.md`
— are appended with cross-reference sections that point back here for
the integration details. Update both this file and the corresponding
spec section if either is touched.

---

## Quick map: which version touches which V6 panel

| Version | Theme | V6 panel(s) affected | Integration depth |
|---|---|---|---|
| **v110** | Pipeline tile split (`ib_pending`) | KPI ribbon · Pipeline pills (TopStrip) | Cosmetic + data |
| **v111** | Queue idempotency + reconciler attach cooldown | Safety Activity Stream | New event kind |
| **v112** | Scalp SL/TP fix (tight ATR + style-aware ladder) | Position Health Console | New row state |
| **v113** | Setup Grading subsystem | NEW right-sidebar panel + chip per row | Net-new panel |
| **v114** | Yesterday's grade in morning briefing | Day narrative strip (E) · Briefing card | Existing endpoint |

---

## v110 — Pipeline tile split in V6 KPI ribbon + TopStrip

### What v110 shipped
- `SentComStatus.order_pipeline.ib_pending` — new top-level field
  alongside `pending` / `executing` / `filled`.
- V5 HUD ORDER tile renders `5q + 3@ib` split when `ib_pending > 0`.

### V6 contract
**TopStrip pipeline pills** (`V6_NEXT_LOCKED_SPEC.md §4`):

The pill `ORDER · N` in the V6 TopStrip MUST behave identically to
the V5 HUD ORDER tile. When `order_pipeline.ib_pending > 0`:

```
ORDER · 5q + 3@ib
```

When `ib_pending == 0`:

```
ORDER · 5
```

Both branches consume the same `order_pipeline` payload from
`/api/sentcom/status`. The frontend split logic already exists in
`SentComV5View.jsx :: derivePipelineCounts` — Phase A panel
extraction should lift this helper into
`frontend/src/utils/orderPipelineSplit.js` so both V5 and V6 import
it without duplication.

**KPI ribbon** (`V6_NEXT_LOCKED_SPEC.md §4`, 5-col KPI row):

The "Open Risk" column is currently spec'd to show the per-trade
risk budget. v110 introduces a useful adjunct: a thin micro-bar
underneath showing `pending / ib_pending / executing` as stacked
segments. Operator-visible signal that lets you read order pipeline
health WITHOUT clicking into the ORDER tile.

**Acceptance**
- V6 ORDER pill matches V5 ORDER tile state for any
  `(pending, ib_pending, executing, filled)` tuple
- The split helper lives at `utils/orderPipelineSplit.js`, imported
  by V5 + V6 — never reimplemented

---

## v111 — Reconciler attach cooldown surfaces in Safety Activity Stream

### What v111 shipped
- `order_queue_service.queue_order()` — trade_id-keyed idempotency
  (returns existing in-flight `order_id`).
- `PositionReconciler._bracket_attach_in_cooldown(trade_id)` +
  `_stamp_bracket_attach(trade_id)` — per-trade 60s cooldown
  wrapping all three `attach_oca_stop_target` call sites.
- New diagnostic counter `_bracket_attach_cooldown_skips` (incremented
  on every cooldown-blocked attach attempt).

### V6 contract
**New event kind in `/api/safety/activity-stream`**
(`V6_SAFETY_ACTIVITY_STREAM_SPEC.md §3`):

Add to the `kinds` enum:

| Icon | Kind | Tone | Operator action |
|---|---|---|---|
| 🧯 | `bracket_attach_cooldown` | slate | View (info-only — bot is throttling itself by design) |

Aggregator must read from `PositionReconciler` skip counter and
expose recent (last 60min) cooldown-blocked attempts:

```json
{
  "ts": "2026-02-12T14:31:52Z",
  "kind": "bracket_attach_cooldown",
  "symbol": "SBUX",
  "headline": "bracket attach skipped — cooldown",
  "detail": "Reconciler attempted to attach OCA bracket for trade tr-9a1 47s after the previous attempt. 13s remaining in 60s cooldown window.",
  "metadata": {
    "trade_id": "tr-9a1",
    "cooldown_remaining_s": 13.2,
    "cooldown_window_s": 60.0
  },
  "actions": []
}
```

**Why expose this**: a cooldown skip is healthy under normal
circumstances (the cooldown exists to prevent the v109 bounce
loop). But a sustained pattern of cooldown skips for the SAME
symbol means something upstream is repeatedly trying to re-arm —
operator wants to see that and investigate.

**Counts panel** (`V6_SAFETY_ACTIVITY_STREAM_SPEC.md §2 header`):

Add a 5th counter:

```
🛑 2 flatten-suppressed · 🧊 1 cooldown · ⚠️ 4 drift-skips ·
🛡️ 0 kill refusals · 🧯 7 attach-cooldown skips today
```

**Backend work needed for V6**: the aggregator skeleton already
loops over `position_reconciler.get_guard_stats()`. Add a parallel
read of `position_reconciler._bracket_attach_cooldown_skips` —
~5 LOC. Counter is currently a single int; consider promoting to a
recent-skips deque (mirror of `_guard_recent_skips`) so per-event
metadata flows.

**Acceptance**
- New `kind: "bracket_attach_cooldown"` events flow from the
  aggregator
- Counts header includes the new bucket
- Filter chip works

---

## v112 — Scalp SL/TP shows up as new row state in Position Health Console

### What v112 shipped
- `OpportunityEvaluator.calculate_atr_based_stop` adds scalp
  multipliers (0.4-0.5×) with min-clamp bypass.
- Trade-style-aware target ladder: scalp `[1R, 1.5R]`, intraday
  `[1.5R, 2.5R]`, swing `[1.5R, 2.5R, 4R]`, position `[2R, 4R, 8R]`.
- Target-snap skipped for scalp trades.

### V6 contract
**New row state in Position Health Console**
(`V6_POSITION_HEALTH_CONSOLE_SPEC.md §2`):

Existing scalp positions opened **BEFORE** v112 deployed are
running with the old wide stops. The Position Health Console
should surface them so the operator can manually retune or close
+ re-enter.

Add to the state machine:

| Icon | State | Trigger | Action |
|---|---|---|---|
| 🟣 | `STOP-WIDE-FOR-STYLE` | `trade.trade_style == 'scalp'` AND `abs(entry - stop) / atr > 1.0` | `Tighten stop →` (POST `/api/trading-bot/retune-stop` — NOT YET BUILT, see V6 follow-up) |

Detection logic (frontend, drives off existing audit + position
rows):

```jsx
const isScalpWithWideStop = (row) => {
  if (row.trade_style !== 'scalp') return false;
  const dist = Math.abs(row.entry_price - row.stop_price);
  // Pull ATR from the same `/api/portfolio` row or fall back to the
  // scanner's last-known ATR. If neither is available, suppress.
  const atr = row.atr || row.scanner_atr;
  if (!atr) return false;
  return dist / atr > 1.0;
};
```

The `Tighten stop →` action requires a new backend endpoint:

```
POST /api/trading-bot/retune-stop
Body: { "trade_id": "tr-9a1", "policy": "scalp_v112_default" }
```

**STATUS: ✅ SHIPPED v19.34.116** — endpoint live; reuses v112's
`OpportunityEvaluator.calculate_atr_based_stop` table and v111's
cooldown guard. Dry-run mode supported via `dry_run: true`. See
`tests/test_v19_34_116_retune_stop.py` for the contract.

**Header summary chip row** — add wide-stop count:

```
6 tracked · 1 unprotected · 2 stacked · 1 zombie · 1 wide-stop
```

**Acceptance**
- Scalp positions with stop-distance > 1×ATR render as
  STOP-WIDE-FOR-STYLE
- `Tighten stop →` button visible only on that state
- Backend `/api/trading-bot/retune-stop` shipped

---

## v113 — Setup Grading dashboard panel in V6 right sidebar

### What v113 shipped
- `services/setup_grading_service.py` — daily EOD aggregation +
  rolling 30-day rollup with sample-weighted averages.
- `routers/setup_grades.py` — full read/write API at
  `/api/setup-grades`.
- `SetupGradeChip` rendered next to TradeStyleChip on
  `OpenPositionsV5` + `ScannerCardsV5`.
- EOD scheduler tick at 16:10 ET on weekdays.

### V6 contract

**New right-sidebar panel** — sibling of `BotBrainPanel`,
`PositionHealthConsole`, `SafetyActivityStream`:

`frontend/src/components/sentcom/v6/SetupGradeBoard.jsx`

Visual concept:

```
─────────────────────────────────────────────────────────
  Setup Grades · last 30 days · refreshed 16:12 ET
─────────────────────────────────────────────────────────
  SETUP              GRADE  WR    AVG R   TRADES  TREND
─────────────────────────────────────────────────────────
  vwap_bounce        A+    66%   +1.20R   42      ▁▃▆█▇▆▅
  nine_ema_scalp     A     61%   +0.78R   28      ▂▄▅▆▆▇█
  rubber_band        B+    54%   +0.62R   33      ▃▄▅▅▅▆▅
  breakout           B     48%   +0.34R   21      ▅▄▃▃▄▄▃
  orb                C     43%   +0.05R   18      ▄▄▃▃▃▂▃
  gap_fade           F     32%   -0.42R   24      ▆▅▄▃▂▂▁
                                                  [Review →]
─────────────────────────────────────────────────────────
  + 3 setups with INSUFFICIENT_DATA (<5 trades)  [Show]
─────────────────────────────────────────────────────────
```

- Rows sorted by `avg_r` desc (matches `get_all_rolling_grades`
  ordering).
- Sparkline column shows the daily `avg_r` from
  `/api/setup-grades/history/{setup_type}?days=30` — one fetch per
  row (lazy-loaded as the row scrolls into view).
- F-graded row has a `Review →` action that opens the chat drawer
  (F) with context preloaded:
  *"Why is gap_fade grading F? Show me the last 5 closed trades."*
- "Show" expander for INSUFFICIENT_DATA setups reveals a muted
  table — runway visible but de-emphasized.

**SetupGradeChip on V6 row components**:

The `OpenPositionsPanel` (V6) and `ScannerPanel` (V6) must keep
rendering `SetupGradeChip` next to `TradeStyleChip` — same as V5.
Phase A extraction lifts both chips into a shared
`<RowMetaChips row={...} />` component so the chip set stays
consistent across panels:

```jsx
<RowMetaChips row={position}>
  <TradeStyleChip row={position} compact size="xs" />
  <SetupGradeChip setupType={position.setup_type} compact size="xs" />
</RowMetaChips>
```

**Position Health Console grade column**
(`V6_POSITION_HEALTH_CONSOLE_SPEC.md §2`):

Add a `GRADE` column to the existing health table — quick visual
correlation between a stacked / unprotected position and the
setup's rolling track record. F-graded + UNPROTECTED is a
double-red-flag the operator should see together.

```
SYMBOL  BOT   IB   STOP   TARGET   GRADE  STATE
NBIS    658   658  0      0        F      🔴 UNPROTECTED
```

**State machine source-of-truth update**
(`V6_NEXT_LOCKED_SPEC.md §3 compute_app_state`):

The current state machine triggers `rose` on kill-switch,
orphan-GTC, pusher-disconnected, RPC slow, EOD-alarm. Consider
adding an `amber` trigger:

```python
if any_open_position_setup_graded_f_for_5_consecutive_days:
    return "amber"   # the bot is shipping setups its own scoreboard says don't work
```

This wires the v113 scoreboard into the V6 halo so the operator
sees the warning at the system-state level, not just inside one
panel. (Observe-only — does NOT block trade entry. Per v113
design.)

**Acceptance**
- `SetupGradeBoard.jsx` mounted in V6 right sidebar
- Rows sorted by avg_r desc, sparklines lazy-load
- F-row action opens chat drawer with preloaded context
- `RowMetaChips` shared component lifted from V5 panels
- Position Health Console gains a GRADE column
- `compute_app_state` optionally extended (gated on operator
  decision)

---

## v114 — Yesterday's grade in V6 morning briefing + Day Narrative

### What v114 shipped
- `SetupGradingService.get_yesterday_recap()` — walks back 7 days,
  returns winners/losers/`summary_line`.
- `GET /api/setup-grades/yesterday-recap` (declared before
  `/{setup_type}` to avoid path-param shadowing).
- `useMorningBriefing` fans out the new endpoint; result lives at
  `data.grade_recap`.
- `MorningPrepCard` (V5) renders winners/losers in expanded section.

### V6 contract

**MorningPrepCard equivalent in V6** —
the V6 spec doesn't have an explicit MorningPrep card (the
operator gets briefing context from the chat drawer + day
narrative strip). The integration is two-fold:

**1. Day Narrative Strip (E)** (`V6_NEXT_LOCKED_SPEC.md §1`):

The narrative strip is spec'd as `GET /api/timeline/narrative?date=today`.
The first row of today's narrative MUST cite yesterday's grade
recap when `has_data === true`:

```
09:25 ET — Yesterday (2026-02-11): vwap_bounce A+ (66%, +1.2R, 6t).
           Watch: breakout F (33%, -0.4R, 9t) — consider widening.
09:31 ET — RTH open · scanner armed · 12 tier-1 candidates
...
```

The narrative endpoint already aggregates events for the day. Add
a "yesterday recap" event at `09:25 ET` (5 minutes before RTH
open) sourced from `/api/setup-grades/yesterday-recap`. The
narrative string is the recap's `summary_line` verbatim — no
re-formatting.

**Backend work**: in whatever service builds
`/api/timeline/narrative`, prepend a synthetic event:

```python
if grade_recap := svc.get_yesterday_recap():
    if grade_recap.get("has_data"):
        narrative.insert(0, {
            "ts": "...09:25:00 ET",
            "kind": "yesterday_recap",
            "text": grade_recap["summary_line"],
            "metadata": grade_recap,
        })
```

**2. Chat drawer (F) context binding**
(`V6_NEXT_LOCKED_SPEC.md §1`):

When the chat drawer opens via ⌘K with no focused pane, the
default system context fed to the LLM MUST include the recap:

```python
system_context = {
    "today": today_iso,
    "open_positions_count": ...,
    "app_state": "cyan|amber|rose",
    # v114 — yesterday's receipt the LLM should quote when asked
    # "how did we do yesterday" without needing tool calls.
    "yesterday_grade_recap": recap.summary_line if recap.has_data else None,
}
```

This is one extra field. ~3 LOC in whatever module builds the chat
drawer's system prompt.

**Acceptance**
- Day narrative strip's 09:25 ET slot cites the recap verbatim
  when data exists
- Chat drawer system context includes the recap summary line
- Asking the chat drawer "how did we do yesterday?" returns the
  same wording as the V5 MorningPrepCard expanded section

---

## Migration ordering — adjusted Plan A phases

The phases in `V6_NEXT_LOCKED_SPEC.md §6` stay broadly correct.
Insert these touch-points:

**Phase A (panel extraction)** — additionally:
- Lift `derivePipelineCounts` from `SentComV5View.jsx` into
  `frontend/src/utils/orderPipelineSplit.js`
- Lift the chip duo (`TradeStyleChip` + `SetupGradeChip`) into a
  shared `<RowMetaChips>` component
- No new tests required — V5 must render identically after the lift

**Phase B (shell + most-used panes)** — additionally:
- Wire `useAppState()` → include the v113 "any F-graded open
  position" amber trigger (optional, gated on operator decision —
  default OFF)
- V6 TopStrip pipeline pills consume the new
  `orderPipelineSplit.js` helper
- KPI ribbon "Open Risk" column adds micro-bar showing
  `pending / ib_pending / executing` segments

**Phase C (migrate remainder + chat drawer + retire V5)** —
additionally:
- Mount `SetupGradeBoard.jsx` in right sidebar
- Position Health Console adds the GRADE column + `STOP-WIDE-FOR-STYLE` row state
- Safety Activity Stream adds the `bracket_attach_cooldown` event kind + counter
- Day narrative strip prepends the yesterday-recap row
- Chat drawer system context includes `yesterday_grade_recap`
- Ship the `POST /api/trading-bot/retune-stop` endpoint for the
  Tighten-stop action — ✅ SHIPPED v19.34.116

**Phase D (post-V6, follow-up)** — new:
- Wire `get_grade_warning(setup_type)` into alert pipeline as a
  HARD filter (currently observe-only). Requires a week of
  v113/v114 production data first to sanity-check the formula.
- Promote `_bracket_attach_cooldown_skips` from int counter to
  deque so Safety Activity Stream can show per-event metadata, not
  just totals.
- Mid-day intraday addendum to MorningPrepCard equivalent
  ("Today vs your 30-day grade") — see v114 finish summary.

---

## Single-line invariants for V6 implementation

Every V6 PR touching the following areas MUST satisfy these:

1. **Pipeline pill / KPI ribbon**: when `ib_pending > 0`, the
   ORDER pill renders the split — never collapses to a flat count.
2. **Position Health Console**: a scalp position with stop-distance
   `> 1×ATR` MUST surface as STOP-WIDE-FOR-STYLE. Never silently
   accept a legacy-wide stop on a scalp.
3. **Safety Activity Stream**: every bracket-attach cooldown skip
   MUST land as a `bracket_attach_cooldown` event in the feed.
   Never let the cooldown go invisible — that's how the operator
   spots upstream loops.
4. **SetupGradeBoard + chips**: the V6 SetupGradeChip MUST share
   its cache with the V5 chip (single session cache). One
   `/api/setup-grades?days=30` request per page load fans every
   chip on every panel.
5. **Day narrative + chat drawer**: yesterday's `summary_line` is
   the **verbatim** source. Never rephrase, never summarize. The
   human operator and the LLM read identical text.

These five invariants are the integration contract. Test cases
should lock them, the same way v113's
`TestSchedulerWiring` source-grep tests lock the EOD tick wiring.
