# V6.next++ — Locked UI Specification
**Locked:** 2026-02-09
**Source mockup:** `/app/frontend/src/pages/V6NextMockup.jsx` at `?preview=v6mock`
**Concept explainers:** `?preview=v6concepts`
**Status:** ✅ User-approved — ready for Plan A migration

---

## 1. Locked Concepts (from V6.next brainstorm)

| # | Concept | Status | Notes |
|---|---|---|---|
| ① | Heartbeat pulse bar (top 5px) | **SHIP** | Tied to halo state: cyan=2s, amber=1.2s, rose=0.7s |
| ② | Risk meter rail (left 22px) | **SHIP** | DLP%: emerald <50%, amber 50–80%, rose >80% |
| ③ | Sparklines on counters | **SHIP** | Conditional — see I |
| ④ | Glass-morphism + ambient halo | **SHIP** | Thinking pane only. State source = see §3 |
| ⑤ | Symbol vibe tints | **SHIP** | Per-row gradient + mood label |
| ⑥ | Pipeline data-flow particles | **SKIP** | Distracting in peripheral vision |
| ⑦ | Time scrubber (full UI rewind) | **SHIP — scope deferred** | Phase 1: scrubber UI + chart-only rewind. Full state rewind = V6.3 |
| ⑧ | Provenance ring (decision donut) | **SHIP** | Full ring on Verdict block + mini-arc on scanner rows (C) |

## 2. Locked Enhancements

| # | Enhancement | Status | Notes |
|---|---|---|---|
| A | Trigger condition micro progress-bars in Thinking pane | **SHIP** | `next eval Xs` countdown in top-right of Watching block |
| B | SL→Entry→PT proximity strip on position rows | **SHIP** | Replaces per-row sparkline. SL/now/PT label row below |
| C | Scanner mini-provenance arc (14px) | **SHIP** | Single-segment arc next to confidence % |
| D | CRITICAL-state sticky action bar | **SHIP** | Auto-show on rose; buttons: FLATTEN ALL, CANCEL ORPH-GTC, RECONNECT PUSHER, dismiss |
| E | Day narrative strip above scrubber | **SHIP** | Click phrase = scrubber jumps to that event time |
| F | Contextual AI chat drawer (⌘K, right-side) | **SHIP** | Context-bound to focused pane. Overlay-style (does not push content) |
| G | Aggregate Open P&L sparkline at top of positions panel | **SHIP** | Wider than per-row sparklines. Last hour. |
| H | "CHANGED" amber-outline on rows that updated during away-time | **SHIP** | Tied to mouse-leave/return detector |
| I | Conditional sparklines (suppress if variance < threshold) | **SHIP** | Show inline `stable` label when suppressed |
| J | Colorblind icon redundancy (✓/⚠/✕) on state pills | **SHIP** | Apply to ALL color-coded state indicators |

## 3. State machine — what drives ④ Halo, ① Heartbeat, ② Rail color, D Action Bar

```python
def compute_app_state():
    """Returns one of: 'cyan' | 'amber' | 'rose'"""
    if (kill_switch_active or orphan_gtc_count > 0
        or pusher_disconnected or pusher_rpc_ms > 400
        or eod_alarm_open_positions > 0):
        return "rose"      # CRITICAL → halo rose, heartbeat fast, action bar shown
    if (throttle_hits_5min > 0 or partial_coverage_pct < 60
        or share_drift_recent_60s or any_focused_symbol_gate_failing):
        return "amber"     # ELEVATED → halo amber, heartbeat medium
    return "cyan"          # NORMAL → halo cyan, heartbeat slow
```

**Halo color affects only:** Thinking pane border + glow + state-chip icon/label
**Heartbeat:** color + pulse speed
**Risk rail color:** driven by DLP% (independent of app state — keeps trader risk visible regardless of system noise)

## 4. Layout grid (left → right)

```
┌─① Heartbeat (5px, full width) ─────────────────────────────────────┐
├─ TopStrip: SENTCOM | pipeline pills | … | PAPER | state-pill | AI ─┤
├─ KPI ribbon (5 cols: P&L · Equity · Open Risk · Throttle · RPC) ──┤
├─ [D Action Bar — only when state=rose] ────────────────────────────┤
│ ②  │ Scanner   │  Chart + Verdict     │ Thinking  │ Open Positions │
│Rail│ (vibe     │  ↳ Provenance ring   │ (Glass+   │ (Aggregate +   │
│22px│  tints +  │     +5-input grid    │  Halo +   │  proximity     │
│    │  mini-arc)│                       │  Trigger  │  bars + H)     │
│    │ 230px     │  flex-1              │ progress) │ 280px          │
│    │           │                       │ 340px     │                │
├─ E Day narrative strip ────────────────────────────────────────────┤
├─ ⑦ Time scrubber ──────────────────────────────────────────────────┤
└─ Footer ───────────────────────────────────────────────────────────┘

[F Chat drawer — slides in from right, 360px overlay, ⌘K toggle]
```

## 5. Deferred to V6.3

- ⑦ **Full-UI rewind** (snapshot bot state every 5s, replay on scrub) — V6.3 backend work
- ⑥ Pipeline data-flow particles — skipped permanently
- Custom cursor / selection styling — V6.3 polish

## 6. Plan A — Migration Phases

### Phase A — Extract V5 panels into reusable components (1–2 days)
Goal: zero behavior change, just decompose `App.js`/`v5/*.jsx` into stand-alone components that can be re-composed for V6.

1. `<TopStrip>` (already exists in V6 mockup — port real data)  ✅ 2026-06-25 — built real pure composite at `v6/TopStrip.jsx` (SENTCOM | pipeline pills [ORDER reuses `orderPipelineSplit`] | PAPER | state-pill ✓/⚠/✕ | AI). Prop-driven `appState`; Phase-B `useAppState()` will feed it. Also `v6/Heartbeat.jsx` (§4 ① 5px state bar). Shell skeleton composing Heartbeat+TopStrip+KpiRibbon+5-col grid at `?preview=v6shell` (`pages/V6ShellPreview.jsx`).
2. `<KpiRibbon>` — extract from `MetricsTopRow.jsx` (or wherever in V5)  ✅ 2026-06-25 — built additively at `v6/KpiRibbon.jsx` (composes `KpiMetric` + `formatMoney/formatEquity` + the §v110 `OrderPipelineMicroBar`). Underlying primitives lifted verbatim from `PipelineHUDV5`: `v6/PipelineStageTile.jsx` (+`STAGE_COLOR`) and `v6/KpiMetric.jsx`. Preview: `?preview=v6kpis`. Pure (props in); Phase-B shell feeds it data.
3. `<ScannerPanel>` — extract from scanner column
4. `<ChartPanel>` — already isolated TradingView wrapper
5. `<VerdictBlock>` — extract from sentcom intelligence
6. `<ThinkingPane>` — extract per-symbol eval card
7. `<OpenPositionsPanel>` — extract from existing positions list
8. `<StatusStrip>` — bottom drawer extraction
9. `<TimelinePanel>` — UnifiedStream + Stream Deep Feed merged

**Acceptance:** V5 still renders unchanged; new components are pure (props in, JSX out).

### Phase B — Build V6 shell + the two most-used panes (2–3 days)
1. New route `/v6` (behind feature flag, V5 still default)
2. 5-column grid shell with resizable splits
3. `<OpenPositionsPanel>` v6 — adds **G** aggregate sparkline + **B** proximity bars + **H** changed-detector
4. `<ThinkingPane>` v6 — wraps in `<GlassHaloPane>` + adds **A** trigger progress + ④ halo state binding
5. Wire ⑩ `compute_app_state()` to backend `/api/safety/system-state` (new endpoint)
6. Heartbeat ① + Risk rail ② + state pill J — all driven by same `useAppState()` hook

**Acceptance:** `/v6` route shows new layout with live data; V5 unchanged.

### Phase C — Migrate remainder + chat drawer + retire V5 (3–5 days)
1. `<ScannerPanel>` v6 — add ⑤ vibe tints + C mini-arc
2. `<VerdictBlock>` v6 — add ⑧ provenance ring
3. ⑦ Time scrubber + E narrative strip (chart-only rewind for now)
4. D action bar — wire FLATTEN ALL / CANCEL ORPH-GTC / RECONNECT PUSHER to existing safety endpoints
5. F AI chat drawer — wire to existing Ollama endpoint, pass context object
6. Flip default route from V5 → V6
7. Delete V5 components after 1 week of stable V6 use

## 7. New backend endpoints required

| Endpoint | Purpose | Phase |
|---|---|---|
| `GET /api/safety/system-state` | Returns `{state: 'cyan'\|'amber'\|'rose', reasons: [...]}` | B |
| `GET /api/positions/aggregate-pnl-history?window=1h` | For G sparkline | B |
| `GET /api/positions/{sym}/proximity` | `{sl, entry, pt, current}` for B | B |
| `GET /api/scanner/conviction/{sym}` | Single number 0–100 for C arc | C |
| `GET /api/timeline/narrative?date=today` | Pre-summarized phrases for E | C |
| `GET /api/trigger-progress/{sym}` | Live progress per watch condition for A | B |

## 8. Frontend hooks required

- `useAppState()` → polls `/api/safety/system-state` every 2s, returns `{state, reasons}`
- `useTriggerProgress(symbol)` → SSE or 1s poll on `/api/trigger-progress/{sym}`
- `useChangeDetector(rowKey)` → tracks mouse-leave/return; returns boolean for H outline
- `useChatContext()` → exposes `{paneId, symbol}` for F drawer context-binding

## 9. Out of scope (locked NO)

- ⑥ pipeline particles
- More tabs in Thinking pane (use chat drawer instead)
- Bigger fonts / lower density
- Full-UI rewind (V6.3)

---

## 10. v110–v114 Integration (added 2026-02-12)

See `/app/memory/V6_INTEGRATION_v110_v114.md` for the full cross-cut
contract. Quick summary of additions Plan A must honor:

**§4 Layout grid** — TopStrip ORDER pill MUST render the v110 split
`5q + 3@ib` when `order_pipeline.ib_pending > 0`. The KPI ribbon's
"Open Risk" column gains a micro-bar showing
`pending / ib_pending / executing` segments. Helper
`utils/orderPipelineSplit.js` lifted from V5 in Phase A so both V5
and V6 share one implementation.

**§3 State machine** — optional v113 amber trigger:
"any open position whose setup_type has graded F for 5+ consecutive
days." Default OFF until operator confirms after a week of v113 data.

**Phase A** adds two extractions: `orderPipelineSplit.js` helper and
the shared `<RowMetaChips>` component (wraps TradeStyleChip +
SetupGradeChip).

✅ **2026-06-25 — BOTH extracted** (zero behavior change): `utils/orderPipelineSplit.js`
(lifted verbatim from `SentComV5View.derivePipelineCounts`; byte-identical; smoke 9/9) +
`components/sentcom/v6/RowMetaChips.jsx` (children-based inline wrapper; single child ==
bare chip so V5 is identical). V5 `OpenPositionsV5` + `ScannerCardsV5` now route
TradeStyleChip through `<RowMetaChips>`. SetupGradeChip stays in the TQS drawer on V5;
V6 panes pass the full duo.

**Phase B** wires `useAppState()` to honor the new amber trigger and
TopStrip + KPI ribbon to the new split helper.

**Phase C** mounts the new V6 `SetupGradeBoard` panel in the right
sidebar, adds GRADE column to Position Health Console, the
`bracket_attach_cooldown` event kind to Safety Activity Stream, the
yesterday-recap row to Day Narrative, and `yesterday_grade_recap` to
the Chat Drawer system context. Ships
`POST /api/trading-bot/retune-stop` for the Tighten-stop action.

Five non-negotiable invariants codified in the integration doc — any
PR touching pipeline pills, position health, safety stream, grade
chips, or briefing narrative must satisfy them.
