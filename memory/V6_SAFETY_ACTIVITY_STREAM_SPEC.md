# Safety Activity Stream — V6 Panel Spec

**Status:** SPEC ONLY · queued behind V6 Plan A panel extraction
**Authored:** 2026-05-11 (operator-suggested during v19.34.69–.75 wrap-up)
**Owner:** TBD (V6 phase)
**Effort estimate:** ~200 LOC frontend, ~50 LOC backend aggregator

---

## 1. Why this panel exists

After the v19.34.69–.75 patch series, the bot now maintains **three independent safety ledgers**:

| Ledger | Source of truth | Surfaces what |
|---|---|---|
| **Rejection cooldowns** | `services/rejection_cooldown_service.py` | Per-`(symbol, setup_type)` cooldowns triggered by structural rejections (cap-saturation, max-positions-hit, kill-switch-tripped, buying-power, etc.). v19.34.8 + v19.34.70. |
| **Operator-flatten suppression** | `services/operator_flatten_suppression.py` | Per-symbol session suppressions after a confirmed external close. v19.34.72. |
| **Drift-guard skips** | `PositionReconciler._guard_recent_skips` | Per-symbol reconciler skips: pusher/direct disagreements, pending two-tick confirmations, unconfirmed zero/partial. v19.34.52, v19.34.55, v19.34.71. |

Each ledger has its own endpoint and (in the V5 layout) lives in a separate corner of the UI. The operator has to mentally fuse three streams to answer a single question:

> "Why did the bot not trade NBIS just now?"

Today's NBIS thrashing ran for 70+ minutes before someone noticed. Five minutes of unified visibility would have caught it within one scan cycle.

**Goal:** one panel, chronological feed, every gate event in one place, with enough metadata to answer "why" without leaving the panel.

---

## 2. Visual concept

A vertically-stacked feed in the V6 right sidebar (sibling of the existing "Bot's Brain" thoughts panel). Each row is a single event:

```
─────────────────────────────────────────────────────────
  🛑  14:32:18  NBIS  operator-flatten suppressed         
                 "Bot closed 3 trades, IB confirmed flat   
                  across 2 ticks. Skipping re-entries      
                  until UTC midnight."                     
                 ⤷ Clear suppression                       
─────────────────────────────────────────────────────────
  🧊  14:31:52  AMD/breakout  cooldown 4:08 left          
                 "Symbol exposure saturated ($14,800 of    
                  $15,000 cap). 5-min cooldown active."    
                 ⤷ Clear cooldown                          
─────────────────────────────────────────────────────────
  ⚠️  14:31:14  TSLA  drift-skip                          
                 "Pusher saw 0 shares, direct IB saw 100.  
                  Refused to mutate state."                
─────────────────────────────────────────────────────────
  🛡️  14:30:47  BMNR  kill-switch-gate refusal             
                 "Order refused at service layer           
                  (BMNR P-1 bypass closed v19.34.69)."     
─────────────────────────────────────────────────────────
```

### Color/iconography per event kind

| Icon | Kind | Tone | Operator action |
|---|---|---|---|
| 🛑 | operator-flatten-suppression | rose | Clear button |
| 🧊 | rejection-cooldown | sky | Clear button |
| ⚠️ | drift-guard-skip | amber | View detail |
| 🛡️ | kill-switch-gate-refusal | violet | View metadata |
| 🚫 | guardrail-veto (safety_guardrails) | rose | View context |
| 💤 | flatten-in-progress refusal | zinc | (info-only) |

### Header summary

Above the feed, a compact 4-up counter row:

```
  🛑 2 flatten-suppressed   🧊 1 cooldown   ⚠️ 4 drift-skips today   🛡️ 0 kill refusals
```

Numbers update on the same 5-30s poll as the feed. Clicking a counter filters the feed to that event kind.

### Empty state

```
  All clear — no gate events in the last 60 minutes.
  The bot is free to evaluate every setup it sees.
```

---

## 3. Backend — unified aggregator

### New endpoint

`GET /api/safety/activity-stream?limit=50&since=<iso8601>&kinds=...`

Query params:
- `limit` — max events to return (default 50, max 200)
- `since` — ISO timestamp; only return events strictly after this
- `kinds` — CSV filter, e.g. `?kinds=cooldown,flatten` (defaults to all)

Response:
```json
{
  "success": true,
  "as_of": "2026-05-11T14:35:00Z",
  "counts": {
    "flatten_suppression": 2,
    "rejection_cooldown": 1,
    "drift_skip": 4,
    "kill_switch_refusal": 0,
    "guardrail_veto": 7,
    "flatten_in_progress": 0
  },
  "events": [
    {
      "ts": "2026-05-11T14:32:18Z",
      "kind": "flatten_suppression",
      "symbol": "NBIS",
      "headline": "operator-flatten suppressed",
      "detail": "Bot closed 3 trades, IB confirmed flat across 2 ticks. Skipping re-entries until UTC midnight.",
      "metadata": {
        "trade_ids": ["t-9a1", "t-9a2", "t-9a3"],
        "added_at": "2026-05-11T14:32:18Z",
        "reason": "operator_external_flatten"
      },
      "actions": [
        { "label": "Clear suppression", "method": "POST",
          "endpoint": "/api/safety/clear-operator-flatten-suppression",
          "body": {"symbol": "NBIS"} }
      ]
    },
    {
      "ts": "2026-05-11T14:31:52Z",
      "kind": "rejection_cooldown",
      "symbol": "AMD",
      "setup_type": "breakout",
      "headline": "cooldown 4:08 left",
      "detail": "Symbol exposure saturated ($14,800 of $15,000 cap). 5-min cooldown active.",
      "metadata": {
        "rejection_count": 1,
        "reason": "symbol_exposure_saturated",
        "expires_at": "2026-05-11T14:36:00Z"
      },
      "actions": [
        { "label": "Clear cooldown", "method": "POST",
          "endpoint": "/api/trading-bot/clear-rejection-cooldown",
          "body": {"symbol": "AMD", "setup_type": "breakout"} }
      ]
    }
    // ... etc
  ]
}
```

### Aggregator implementation sketch

New module `services/safety_activity_aggregator.py`:

```python
def build_activity_stream(limit=50, since=None, kinds=None) -> dict:
    events = []

    # 1. Operator-flatten suppression (in-memory singleton)
    from services.operator_flatten_suppression import get_operator_flatten_suppression
    for sym, entry in get_operator_flatten_suppression().list_all().items():
        events.append({
            "ts": entry["added_at"],
            "kind": "flatten_suppression",
            "symbol": sym,
            "headline": "operator-flatten suppressed",
            "detail": f"{len(entry.get('trade_ids', []))} trade(s) closed; "
                      f"re-entries blocked until UTC midnight or operator clears.",
            "metadata": entry,
            "actions": [...],
        })

    # 2. Rejection cooldowns
    from services.rejection_cooldown_service import get_rejection_cooldown
    for (sym, setup), cd in get_rejection_cooldown().all_active().items():
        events.append({...})

    # 3. Drift-guard recent skips (already a deque on the reconciler)
    from services.position_reconciler import get_position_reconciler
    for skip in get_position_reconciler().get_guard_stats()["recent_skips"]:
        events.append({...})

    # 4. Kill-switch-gate refusals (from order_queue rejected rows)
    db = get_database()
    for row in db.order_queue.find(
        {"rejected_by": {"$regex": "_kill_switch_gate_"}},
        {"_id": 0, "symbol": 1, "rejected_by": 1, "completed_at": 1, "reason": 1}
    ).sort("completed_at", -1).limit(50):
        events.append({...})

    # 5. Safety-guardrail vetoes (from trade_drops collection, gate=safety_guardrail)
    for drop in db.trade_drops.find(
        {"gate": {"$in": ["safety_guardrail", "rejection_cooldown",
                          "operator_flatten_suppression"]}},
        {"_id": 0}
    ).sort("created_at", -1).limit(50):
        events.append({...})

    # Sort by ts desc, filter by since/kinds, slice to limit.
    events.sort(key=lambda e: e["ts"], reverse=True)
    if since:
        events = [e for e in events if e["ts"] > since]
    if kinds:
        events = [e for e in events if e["kind"] in kinds]
    return {"events": events[:limit], "counts": _bucket_counts(events)}
```

### Counts endpoint

`GET /api/safety/activity-stream/counts` — same data, just the `counts` block. For the 4-up header chip row. Cheaper to poll at 5s cadence vs full feed at 30s.

### Backend testing

- `tests/test_safety_activity_stream_aggregator.py` — pin each source's translation into the unified event shape. Mock the three ledgers + two collections; assert merge order, filter semantics, count bucket math.

---

## 4. Frontend — V6 component

New component `frontend/src/components/sentcom/v6/SafetyActivityStream.jsx`. Sits in the V6 right-sidebar zone (sibling of `BotBrainPanel`).

### Polling

- Counts (header row): `GET /api/safety/activity-stream/counts` every 5s.
- Feed (full): `GET /api/safety/activity-stream?limit=50` every 15s.
- WebSocket fast-path (optional, phase 2): subscribe to `safety_activity` stream so high-priority events (kill-switch refusals, P-1 events) appear within 1s.

### Interaction

- Click row → expand drawer showing `metadata` table + raw JSON.
- Click action button (`Clear suppression`, `Clear cooldown`) → confirm toast → fire the action's POST → optimistic UI removes the row → refetch.
- Filter chips in the header row → set `kinds=` query param → refetch.
- "Pause feed" toggle → freezes polling (operator wants to read a row without scroll jitter).

### Accessibility

- `data-testid="safety-activity-stream"`
- `data-testid="safety-activity-event-{kind}-{symbol}"` per row
- `data-testid="safety-activity-counter-{kind}"` per header chip
- All action buttons keyboard-focusable, Enter / Space triggers
- ARIA-live polite region around the feed so a screenreader announces new events without spamming

---

## 5. Acceptance criteria

### Backend
1. `GET /api/safety/activity-stream` returns merged events from all five sources, sorted ts desc.
2. `since=` filter strictly excludes events at or before the timestamp.
3. `kinds=` filter is set-membership; missing param = all kinds.
4. `counts` block sums to no more than total events returned across all pages.
5. Empty ledgers → `{"events": [], "counts": {...zeros}}` (never 500).
6. Each event has a stable `kind` and a non-empty `headline`.
7. Endpoint completes in <200ms on a populated set (load test 500 events across all sources).

### Frontend
1. Panel renders the 4-up counter row + scrollable feed below it.
2. New events appear within one poll cycle (≤15s) of being emitted.
3. Clicking a counter filters the feed to that kind; clicking again clears the filter.
4. Action buttons fire the correct POST; on success the row disappears within one poll.
5. Empty state renders the "All clear" copy when counts are all zero.
6. Screenshot test: panel matches the visual mockup at ±2% pixel diff.

---

## 6. Edge cases / decisions

- **Suppression set rolls at UTC midnight** — the aggregator must not emit yesterday's flatten-suppressions after the roll. Operator-flatten-suppression module already auto-clears; the aggregator just reflects what's there.
- **Cooldowns can be deduped to one event per (symbol, setup_type)**. Don't emit one event per `mark_rejection` call — that floods the feed during real thrashing. Show "rejection_count: N" in metadata instead.
- **High-frequency events** (e.g., during a kill-switch storm) — debounce to ≤1 event per (kind, symbol) per 5s. Aggregator should bucket and merge same-key events that fall within the window.
- **Empty/`None` symbol** — events with no symbol (e.g., a system-level kill-switch trip) render with `SYSTEM` as the symbol label.

---

## 7. Phasing

- **Phase 1 (1-2 days):** backend aggregator + endpoint + 6-test pytest suite. Returns merged events; no debounce yet.
- **Phase 2 (1-2 days):** frontend `SafetyActivityStream` component with polling, counter row, action buttons. Lives in V6 right sidebar.
- **Phase 3 (post-V6 ship):** WebSocket fast-path for P-1 events, debounce/merge logic, persist a 7-day TTL `safety_activity_events` collection so the panel survives backend restarts with history.

---

## 8. Dependencies

- ✅ `services/operator_flatten_suppression.py` (v19.34.72)
- ✅ `services/rejection_cooldown_service.py` (v19.34.8 + .70)
- ✅ `PositionReconciler.get_guard_stats()` (v19.34.55)
- ✅ `routers/ib.py::_kill_switch_gate` rejection rows (v19.34.48/.69)
- ✅ `services/trade_drop_recorder.py` (existing)
- ⏳ V6 right-sidebar slot — depends on Plan A panel extraction landing first

No new third-party dependencies. No DB schema changes (uses existing collections + in-memory singletons).
