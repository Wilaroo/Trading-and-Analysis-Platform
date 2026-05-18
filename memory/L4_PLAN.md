# Patch L4 — Pusher Cleanup Plan

**Created**: 2026-05-18, immediately post-L3 soft-pass.
**Status**: 🟢 READY TO START (waiting for ≥1hr L3 soak + ideally 1 real fired bracket).
**Owner**: operator + main agent.

---

## Context

L3 deployed `BOT_ORDER_PATH=direct` and validated it under live-paper
conditions. Three event-loop wedges were caught and patched (see
`CHANGELOG.md` 2026-05-18 entry). The migration-status endpoint now
reports `verdict: ready, order_path: direct, drops: 0`.

**Consequence:** the Windows pusher's order-write surface is now dead
weight. It still ticks but nothing routes through it. Several side
effects are now operator-visible:

- Orange UI banner: *"Spark→pusher RPC blocked — 82 consecutive
  RPC failures"* (constantly displayed, scares the operator)
- `/rpc/account-snapshot` calls fail every ~5s and used to wedge
  the event loop (fixed by L3-hotfix3, but the underlying RPC
  failure persists and is noise)
- Operators have no clear UI signal that ib-direct is the active
  write path

L4 cleans up. **Pusher remains a pure data publisher** (push channel
for quotes/positions/account stays — that's the data lifeline). The
write/RPC channels go.

---

## L4a — Strip `queue_order` from the Windows pusher

**File:** `ib_data_pusher.py` (Windows side, NOT in this repo)
**Owner:** operator (manual edit on Windows box + restart pusher)

### Changes

1. Remove the `/rpc/queue-order` HTTP handler entirely.
2. Remove the `/rpc/cancel-order` HTTP handler.
3. Remove the `/rpc/attach-oca-stop-target` HTTP handler.
4. Keep `/rpc/account-snapshot` ONLY IF needed for a non-direct
   read fallback (it's not — `ib_direct.managedAccounts()` already
   provides this). Recommend removing too.
5. Keep ALL push-out endpoints (quotes, positions, account events,
   bracket lifecycle events). The bot still relies on these.

### Acceptance
- Pusher restart → bot's `/api/system/health` still green
- Pusher `/rpc/*` returns 404 for the removed paths
- No order-write attempts from Spark hit the pusher (verify via
  Windows pusher access log)
- `BOT_ORDER_PATH=pusher` mode is now permanently broken (acceptable —
  document this in the boot banner)

### Risk
If we ever need to revert from `direct` → `pusher`, this commits us
to ib-direct. **Mitigation**: tag the pre-L4a pusher binary so it
can be restored if catastrophic ib-direct failure forces a rollback.

---

## L4b — UI: "BRACKETS ROUTE" status pill

**File:** `frontend/src/components/sentcom/v5/...` or wherever the
status strip lives (look near the existing PAPER · DUN615665 / IB-LIVE /
Safety ARMED pills).

### Changes

Add a new status pill driven by `/api/system/ib-direct/migration-status`:

| `order_path` | pill text | colour |
|---|---|---|
| `direct` (verdict=ready) | `BRACKETS · ib-direct ✅` | green |
| `direct` (verdict≠ready) | `BRACKETS · ib-direct ⚠️ <reason>` | yellow |
| `pusher` | `BRACKETS · pusher ⚠️ LEGACY` | yellow |
| `simulated` / fallback | `BRACKETS · SIM 🔴` | red |

### Wiring
- Poll `/api/system/ib-direct/migration-status` on the same cadence as
  the other status pills (~5s).
- Use existing pill primitives (don't invent a new component style).

### Acceptance
- New pill renders on V5 status strip.
- Tooltip on hover shows the full migration-status JSON.
- `data-testid="status-pill-brackets-route"` for testability.

---

## L4c — Suppress the "Spark→pusher RPC blocked" banner under direct mode

**File:**
- Backend: `backend/services/health.py` (the subsystem reporter for
  `pusher_rpc`)
- Frontend: wherever the orange banner is rendered (top of dashboard;
  uses the system-banner endpoint)

### Backend change
When `BOT_ORDER_PATH=direct`, the `pusher_rpc` subsystem reporter
should:
- Return `status: "green"` (not yellow/red) if push channel is healthy,
  regardless of RPC failure count.
- Set `detail: "RPC channel deprecated (direct mode) — push channel
  healthy"`.
- Add a new field `rpc_channel_expected: "offline"` so frontend can
  show a calmer message.

### Frontend change
- When `rpc_channel_expected: "offline"`, don't render the orange
  full-width banner. Instead, show a small chip in the UI status strip:
  `RPC · deprecated (direct)` with neutral grey.

### Acceptance
- Orange banner disappears under direct mode (after L4c deploy).
- A pusher restart still triggers the push-channel-loss alert
  (that's a real outage, not a deprecated channel).
- All existing health-page tests still green.

---

## L4d — New endpoint: `/api/system/pusher-rpc/expected-state`

**File:** `backend/routers/health.py` (or `system.py`, wherever the
system-state endpoints already live)

### Endpoint
```
GET /api/system/pusher-rpc/expected-state
→ {
    "order_path": "direct",
    "rpc_channel_expected": "offline",
    "push_channel_expected": "online",
    "reason": "BOT_ORDER_PATH=direct — order writes go via ib_direct;
               pusher RPC is intentionally deprecated. push channel
               still required for quote/position fan-out."
  }
```

### Why
Gives operators (and any external monitoring like a Grafana watchdog)
an authoritative truth-source on what the pusher SHOULD be doing
without scraping logs.

### Acceptance
- Endpoint returns 200 with the schema above when `BOT_ORDER_PATH=direct`.
- When `BOT_ORDER_PATH=pusher` (legacy), returns `rpc_channel_expected:
  "online"`.

---

## Order of operations (recommended)

1. **L4c FIRST** (backend health + banner suppression) — operator UX
   improvement, zero risk, no removal of code paths.
2. **L4b** (status pill) — gives operator confidence visual that
   ib-direct is active before we strip the pusher write paths.
3. **L4d** (expected-state endpoint) — observability before strip.
4. **L4a LAST** (pusher write-path strip on Windows side) — the
   actual removal. Only after #1-#3 are in place and stable for ≥1
   trading session.

---

## Rollback plan

If L4a turns out to break something:
1. Restore previous pusher binary on Windows.
2. Set `BOT_ORDER_PATH=pusher` in `.env`.
3. Restart backend. L2a + L2b code paths auto-disable; bot uses the
   pusher RPC path as before.

---

## Open questions

- Should the pusher's `/rpc/account-snapshot` stay for legacy tooling?
  Leaning **no** (every L3 wedge so far has involved it).
- Are there any operator scripts that poke the pusher's `/rpc/*`
  outside the bot? Check `~/Trading-and-Analysis-Platform/scripts/`
  before stripping.

---

## Pre-L4 sign-off checklist (must all be ✅ before L4a)

- [ ] L3 has soaked for ≥1 hour without wedges
- [ ] At least 1 real bracket has fired via `place_bracket_order via
      ib_direct` AND been managed cleanly through stop-or-target exit
      (full OCA lifecycle observed)
- [ ] `/api/system/ib-direct/migration-status` consistently reports
      `verdict: ready, drops: 0`
- [ ] No silent kill-switch re-trips observed
- [ ] All hotfix1+2+3 tests green
- [ ] CHANGELOG + ROADMAP updated (this commit ✅)
