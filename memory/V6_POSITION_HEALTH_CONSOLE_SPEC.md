# Position Health Console — V6 Panel Spec

**Status:** SPEC ONLY · queued alongside Safety Activity Stream for V6 phase
**Authored:** 2026-05-12 (operator-suggested during v19.34.80 wrap-up)
**Owner:** TBD (V6 phase)
**Effort estimate:** ~250 LOC frontend, **0 LOC new backend** (all endpoints already shipped)

---

## 1. Why this panel exists

Today's session shipped **four operator endpoints** that each diagnose or remediate a different state-integrity problem:

| Endpoint | Version | What it does |
|---|---|---|
| `GET /api/trading-bot/bracket-stacking-audit` | v19.34.77 | Surfaces symbols where pending stop/target qty exceeds tracked position qty |
| `POST /api/trading-bot/cancel-excess-bracket-legs` | v19.34.80 | Cancels redundant brackets, keeps one canonical pair |
| `POST /api/trading-bot/attach-brackets-to-unprotected` | v19.34.76 | Re-arms missing stop/target on naked positions |
| `POST /api/trading-bot/clear-stale-pending-trades` | v19.34.78 | Drops zombie `_pending_trades` entries |

They were built fast because each one was an emergency. They work, they're tested, and they live on the curl command line. That's fine for the post-mortem flow we ran today — operator notices something weird, runs the audit, runs the remediation.

The next step is to make this **proactive**: surface the problems the moment they appear, not 70 minutes (or one trading day) later.

This panel does that. It polls the audit endpoint every 30s, renders one row per tracked symbol with traffic-light state, and exposes the three remediation buttons inline. Today's full unwind sequence — audit, cancel-excess on three symbols, attach-brackets on BMNR — collapses to four clicks.

**Goal:** the operator never again sees "naked BMNR" or "320sh stops on 80sh ADBE" by reading TWS three hours later. The panel screams the moment it happens.

---

## 2. Visual concept

V6 right sidebar, sibling of `BotBrainPanel` and `SafetyActivityStream`. Single scrollable table:

```
─────────────────────────────────────────────────────────────────────
  Position Health · 6 tracked · 1 unprotected · 2 stacked   ⟳ 14s
─────────────────────────────────────────────────────────────────────
  SYMBOL    BOT     IB     STOP COVER   TARGET COVER   STATE
─────────────────────────────────────────────────────────────────────
  🔴 BMNR    658    658    0            0              UNPROTECTED
                                                       [Arm brackets →]
─────────────────────────────────────────────────────────────────────
  🟠 ADBE    80     80     320  (4x)    240  (3x)     STACKED
                                                       [Cancel excess →]
─────────────────────────────────────────────────────────────────────
  🟠 EFA     963    963    2,888 (3x)   1,925 (2x)    STACKED
                                                       [Cancel excess →]
─────────────────────────────────────────────────────────────────────
  🟡 GM      109    109    1,282 (12x)  1,282 (12x)   STACKED-HIGH
                                                       [Cancel excess →]
─────────────────────────────────────────────────────────────────────
  🟢 PEP     323    323    323          323           CLEAN
─────────────────────────────────────────────────────────────────────
  🟢 EBAY    540    540    540          540           CLEAN
─────────────────────────────────────────────────────────────────────
  🔵 NBIS    —      —      —            —             ZOMBIE PENDING
                                                       [Clear pending →]
─────────────────────────────────────────────────────────────────────
```

### State machine per row

| Icon | State | Trigger | Action |
|---|---|---|---|
| 🟢 | CLEAN | `pending_stop_qty == bot_qty == ib_qty` and bot has `stop_order_id` | (none) |
| 🔴 | UNPROTECTED | `pending_stop_qty == 0` and `bot_qty > 0` | `Arm brackets →` (calls `attach-brackets-to-unprotected` with `symbols: [sym]`) |
| 🟠 | STACKED | `pending_stop_qty > bot_qty` and ratio ≤ 4x | `Cancel excess →` (calls `cancel-excess-bracket-legs`) |
| 🟡 | STACKED-HIGH | `pending_stop_qty > bot_qty` and ratio > 4x | `Cancel excess →` (same), warning toast |
| ⚪ | DRIFT-BOT-OVER | `bot_qty > ib_qty + threshold` (bot tracks phantom) | Info only — v19.34.71 two-tick gate handles |
| ⚫ | DRIFT-IB-OVER | `ib_qty > bot_qty + threshold` (untracked IB shares) | Info only — reconciler will adopt |
| 🔵 | ZOMBIE PENDING | Symbol in `_pending_trades` but no IB position | `Clear pending →` (calls `clear-stale-pending-trades` with `symbols: [sym]`) |

### Header summary chip row

```
 6 tracked · 1 unprotected · 2 stacked · 1 zombie pending · 0 drift
```

Each chip clickable → filters table to that state. Re-click clears filter.

### Empty state

```
  All clean — every tracked position is properly bracketed,
  no drift, no zombies.  ⟳ next check in 28s
```

### Confirm dialog before destructive action

`Cancel excess →` opens a one-step confirm modal showing the diff:

```
  ┌────────────────────────────────────────────────────────┐
  │  Cancel excess bracket legs for ADBE                   │
  │                                                        │
  │  KEEP   stop #1683095197  80sh @ 237.05  (OCA-B)      │
  │         target #1683095198 80sh @ 270.75 (OCA-B)      │
  │                                                        │
  │  CANCEL stop #1683095174  40sh @ 237.29  (OCA-A)      │
  │         target #1683095173 40sh @ 271.00 (OCA-A)      │
  │         stop #1683095153  40sh @ 237.05  (OCA-C)      │
  │         target #1683095152 40sh @ 270.75 (OCA-C)      │
  │                                                        │
  │            [Cancel]                  [Apply ↩︎]         │
  └────────────────────────────────────────────────────────┘
```

The modal body is the dry-run output of `cancel-excess-bracket-legs`. `Apply` re-fires the same call with `dry_run: false`.

---

## 3. Backend — already shipped, no new code

Frontend will consume:

| Method/Path | Used for |
|---|---|
| `GET /api/trading-bot/bracket-stacking-audit` | Primary 30s poll — produces every row |
| `POST /api/trading-bot/attach-brackets-to-unprotected` | `Arm brackets →` button |
| `POST /api/trading-bot/cancel-excess-bracket-legs` | `Cancel excess →` button (dry-run for confirm modal, apply on confirm) |
| `POST /api/trading-bot/clear-stale-pending-trades` | `Clear pending →` button |
| `GET /api/trading-bot/status` (for `_pending_trades` view) | ZOMBIE PENDING rows |

Zero new endpoints. The audit's existing `symbols[].severity` field (`high`/`medium`/`info`) drives the orange-vs-yellow distinction; the audit's `recommendation` field becomes the modal subtitle.

If the audit endpoint needs anything added later, the most useful single field would be:
```json
"pending_pending_trades": [
  {"trade_id": "...", "symbol": "NBIS", "age_s": 3892}
]
```
…so the panel doesn't need a separate `/api/trading-bot/status` poll for the ZOMBIE rows. ~10 LOC backend if you want it; the panel works without.

---

## 4. Frontend — V6 component

New file: `frontend/src/components/sentcom/v6/PositionHealthConsole.jsx`.

### Component skeleton (~250 LOC)

```jsx
import { useState, useEffect, useMemo } from 'react';
import { Button } from '../../ui/button';
import { Badge } from '../../ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogFooter } from '../../ui/dialog';
import { toast } from 'sonner';

const POLL_MS = 30_000;
const API = process.env.REACT_APP_BACKEND_URL;

const STATE_META = {
  CLEAN:           { icon: '🟢', cls: 'text-emerald-400', label: 'Clean' },
  UNPROTECTED:     { icon: '🔴', cls: 'text-rose-400',    label: 'Unprotected' },
  STACKED:         { icon: '🟠', cls: 'text-orange-400',  label: 'Stacked' },
  'STACKED-HIGH':  { icon: '🟡', cls: 'text-amber-300',   label: 'Stacked High' },
  'DRIFT-BOT-OVER':{ icon: '⚪', cls: 'text-zinc-300',    label: 'Phantom drift' },
  'DRIFT-IB-OVER': { icon: '⚫', cls: 'text-zinc-500',    label: 'Untracked' },
  ZOMBIE_PENDING:  { icon: '🔵', cls: 'text-sky-400',     label: 'Zombie pending' },
};

const classify = (row) => {
  const { bot_position_qty, ib_position_qty, pending_stop_qty_total } = row;
  const botQ = Math.abs(bot_position_qty);
  const ibQ = Math.abs(ib_position_qty);
  if (botQ === 0 && ibQ === 0) return 'ZOMBIE_PENDING'; // pending only
  if (botQ > 0 && pending_stop_qty_total === 0) return 'UNPROTECTED';
  const ratio = pending_stop_qty_total / Math.max(botQ, 1);
  if (ratio > 4) return 'STACKED-HIGH';
  if (ratio > 1.05) return 'STACKED';
  if (Math.abs(botQ - ibQ) > 0.5) return botQ > ibQ ? 'DRIFT-BOT-OVER' : 'DRIFT-IB-OVER';
  return 'CLEAN';
};

export const PositionHealthConsole = () => {
  const [data, setData] = useState({ symbols: [], clean_symbols: [] });
  const [filter, setFilter] = useState(null);
  const [confirm, setConfirm] = useState(null); // {symbol, dryRunResult}
  const [tickSec, setTickSec] = useState(0);

  useEffect(() => {
    let cancel = false;
    const fetchOnce = async () => {
      try {
        const r = await fetch(`${API}/api/trading-bot/bracket-stacking-audit`);
        const j = await r.json();
        if (!cancel) { setData(j); setTickSec(0); }
      } catch (e) {
        if (!cancel) toast.error('Position health poll failed', { description: String(e) });
      }
    };
    fetchOnce();
    const id = setInterval(fetchOnce, POLL_MS);
    const tick = setInterval(() => setTickSec((s) => s + 1), 1000);
    return () => { cancel = true; clearInterval(id); clearInterval(tick); };
  }, []);

  const rows = useMemo(() => {
    const items = [
      ...data.symbols.map((s) => ({ ...s, _state: classify(s) })),
      ...data.clean_symbols.map((sym) => ({
        symbol: sym, bot_position_qty: 0, ib_position_qty: 0,
        pending_stop_qty_total: 0, pending_target_qty_total: 0, _state: 'CLEAN',
      })),
    ];
    return filter ? items.filter((r) => r._state === filter) : items;
  }, [data, filter]);

  const counts = useMemo(() => {
    const c = {};
    for (const r of data.symbols) { const s = classify(r); c[s] = (c[s] || 0) + 1; }
    c.CLEAN = (c.CLEAN || 0) + (data.clean_symbols || []).length;
    return c;
  }, [data]);

  const openCancelConfirm = async (symbol) => {
    const r = await fetch(`${API}/api/trading-bot/cancel-excess-bracket-legs`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol, dry_run: true }),
    });
    const j = await r.json();
    setConfirm({ symbol, dryRunResult: j });
  };

  const applyCancel = async () => {
    if (!confirm) return;
    const r = await fetch(`${API}/api/trading-bot/cancel-excess-bracket-legs`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: confirm.symbol, dry_run: false }),
    });
    const j = await r.json();
    toast.success(`${confirm.symbol}: cancelled ${j.cancelled.length} excess legs`);
    setConfirm(null);
  };

  const armBrackets = async (symbol) => {
    const r = await fetch(`${API}/api/trading-bot/attach-brackets-to-unprotected`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbols: [symbol], dry_run: false }),
    });
    const j = await r.json();
    toast.success(`${symbol}: bracket attached`, { description: `stop=${j.candidates[0]?.computed?.stop}` });
  };

  const clearPending = async (symbol) => {
    await fetch(`${API}/api/trading-bot/clear-stale-pending-trades`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbols: [symbol], older_than_s: 0, dry_run: false }),
    });
    toast.success(`${symbol}: zombie pending cleared`);
  };

  // ... header chips, table, action buttons, confirm dialog ...
};
```

### Polling

- Primary audit: 30s.
- Visual countdown in header (`⟳ 14s`) refreshes the operator's sense of "this is current."
- Optional later: WebSocket fast-path so a STACKED state surfaces within 1s of the v19.34.79 sibling sweep failing or a manual position adjustment in TWS.

### Accessibility

- `data-testid="position-health-console"`
- `data-testid="position-health-row-{symbol}"` per row
- `data-testid="position-health-action-{symbol}-{action}"` per button (arm-brackets, cancel-excess, clear-pending)
- `data-testid="position-health-confirm-dialog"`
- ARIA-live polite around the table so a screen-reader announces state transitions.

### Color and spacing

Inherits the V6 cohesive aesthetic (locked at `/app/memory/V6_NEXT_LOCKED_SPEC.md`). State icons use FontAwesome circles colored via Tailwind utility classes (`text-emerald-400`, `text-rose-400`, etc.) — no inline gradients or emoji icons in production. Row dividers `border-zinc-800/40`.

---

## 5. Acceptance criteria

### Backend
No new code. Spec-compliant if the existing `bracket-stacking-audit` shape stays stable.

### Frontend
1. Panel renders within 1s of mount; polls audit every 30s; countdown header updates every 1s.
2. Each row has a `data-testid="position-health-row-{symbol}"` and one of seven `_state` classes.
3. `Arm brackets →` button visible iff state is UNPROTECTED; on click, fires `attach-brackets-to-unprotected` with the row's symbol; success toast.
4. `Cancel excess →` button visible iff state is STACKED or STACKED-HIGH; on click, opens confirm modal pre-loaded with dry-run result; `Apply` fires the non-dry-run version.
5. `Clear pending →` button visible iff state is ZOMBIE_PENDING; on click, fires `clear-stale-pending-trades` with the row's symbol; success toast.
6. Filter chips in the header narrow the table; second click clears.
7. Empty state copy renders when `data.symbols.length === 0` and `data.clean_symbols.length > 0`.
8. Screen reader announces state transitions on the live region.
9. Visual: matches the V6 aesthetic, no AI-slop gradients, sharp accents.

---

## 6. Edge cases / decisions

- **`bot.symbol` showing in audit's `symbols[]` but with `bot_position_qty=0` and `pending_stop_qty=0`** — this is the ZOMBIE PENDING fingerprint (symbol is in `_pending_trades` but no real position anywhere). Surface it as ZOMBIE PENDING.
- **`bot_position_qty < 0` (short positions)** — display `qty` as positive in the table with a `S` badge after the number. Stacking math is computed on absolute values.
- **`pending_stop_qty_total != pending_target_qty_total`** — surface BOTH ratios so operator sees the asymmetry. The status pill uses whichever ratio is higher.
- **Race during cancel-apply** — if the audit poll arrives between confirm-dialog open and Apply, the dryRunResult in the modal might be stale (e.g., bracket already cancelled by sibling-sweep elsewhere). Apply path handles this gracefully via existing `cancel_returned_false` error reporting in v19.34.80. Modal shows the errors banner.
- **Network failure on poll** — toast (rate-limited to one per minute via a `lastErrorAt` timestamp), keep showing last good data with a `STALE` watermark in the header.

---

## 7. Phasing

- **Phase 1 (1 day):** Component skeleton + polling + read-only render. No buttons. Lets operator SEE the state live.
- **Phase 2 (0.5 day):** Add the three action buttons + confirm modal. Wire to existing endpoints.
- **Phase 3 (post-V6 ship):** WebSocket fast-path, persistent history (7-day TTL `position_health_snapshots` collection) so the panel survives backend restarts with the last good state, sparkline column showing the per-symbol stacking ratio over the last 60 minutes.

---

## 8. Dependencies

- ✅ `bracket-stacking-audit` endpoint (v19.34.77)
- ✅ `cancel-excess-bracket-legs` endpoint (v19.34.80)
- ✅ `attach-brackets-to-unprotected` endpoint (v19.34.76)
- ✅ `clear-stale-pending-trades` endpoint (v19.34.78)
- ⏳ V6 right-sidebar slot — depends on Plan A panel extraction landing first
- Optional: `audit` endpoint enrichment with `pending_trades[]` block (~10 LOC backend) for cleaner ZOMBIE rendering

No new third-party dependencies, no DB schema changes.

---

## 9. Why this is the right next V6 panel (not the Safety Activity Stream)

Both panels are queued. Build order matters:

- **Position Health Console** = current state, finite rows (1 per tracked symbol), action-oriented.
- **Safety Activity Stream** = event history, append-only feed, log-oriented.

The Position Health Console answers **"Am I safe right now?"** in one glance. The Safety Activity Stream answers **"How did I get here?"** as a post-mortem. The first is more frequently consulted, has higher operator value per minute of build effort, and reuses 100% of the backend you shipped today.

Recommend: ship Position Health Console first (Phase 1+2 = 1.5 days), then Safety Activity Stream (3 days end-to-end per its own spec).

---

## 10. v110–v114 Integration (added 2026-02-12)

Cross-reference: `/app/memory/V6_INTEGRATION_v110_v114.md`.

### v112 — New row state: `STOP-WIDE-FOR-STYLE`

Scalp positions opened BEFORE v112 deployed are running with
1.5–2.0×ATR stops where v112 expects 0.4–0.5×ATR. Surface them:

| Icon | State | Trigger | Action |
|---|---|---|---|
| 🟣 | STOP-WIDE-FOR-STYLE | `trade.trade_style == 'scalp'` AND `abs(entry_price - stop_price) / atr > 1.0` | `Tighten stop →` (calls new `POST /api/trading-bot/retune-stop`) |

Backend dependency: `POST /api/trading-bot/retune-stop` (~30 LOC,
NOT YET BUILT). Reads `trade.trade_style`, computes the v112-correct
stop via `OpportunityEvaluator.calculate_atr_based_stop`, moves the
existing STP via `attach_oca_stop_target` (which respects v111
cooldown).

Header summary chip row gains `wide-stop` count:

```
6 tracked · 1 unprotected · 2 stacked · 1 zombie · 1 wide-stop
```

### v113 — New GRADE column

Add a column between TARGET COVER and STATE showing the rolling
30-day grade for the position's `setup_type` (sourced from
`/api/setup-grades/{setup_type}`). F-graded + UNPROTECTED is a
double-red-flag pattern the operator must see together.

```
SYMBOL  BOT   IB   STOP   TARGET   GRADE  STATE
NBIS    658   658  0      0        F      🔴 UNPROTECTED
```

Grade lookup uses the same session cache as `SetupGradeChip` — one
HTTP request per page load fans every row.

### Invariants

1. Scalp with stop-distance > 1×ATR MUST render STOP-WIDE-FOR-STYLE
2. GRADE column fed from the SHARED `useSetupGrades()` cache — no
   per-row fetches
