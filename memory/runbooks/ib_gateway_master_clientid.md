# Runbook — IB Gateway "Master API client ID" must = 11

**Status:** REQUIRED configuration. Set 2026-05-29. Owner: operator (Windows box).

## Why this matters
IB only lets a client cancel an order if that client **owns** the order
(placed it in the *same* session) — *or* if the client's id equals the IB
Gateway's **Master API client ID**, which grants authority to view and cancel
**all** orders across every client session (including orphaned/prior-session
GTC brackets and manual TWS orders).

Without the master setting, every backend restart creates a *new* clientId-11
session that **cannot cancel the GTC brackets placed by the previous process**.
Symptom (observed 2026-05-29 on CF/BAP):

- Clicking **Close** aborts with `bracket_cancel_timeout_race_risk`.
- Logs show `IB Error 10147: OrderId <id> that needs to be cancelled is not found`
  while IB simultaneously reports the order as `Submitted`/`PreSubmitted`.
- The cancel **flaps**: `PendingCancel → Submitted` (accepted then reverted).

Setting **Master API client ID = 11** (matching the bot's `IB_DIRECT_CLIENT_ID`)
fixed it: clientId-11 reconnects as master, IB binds all open orders to it, and
`cancelOrder` is honored.

## The two values that MUST stay in sync
| Where | Setting | Value |
|---|---|---|
| IB Gateway (Windows) | Configure → Settings → API → Settings → **Master API client ID** | `11` |
| Bot (`backend/.env`) | `IB_DIRECT_CLIENT_ID` (default 11) | `11` |
| Bot (optional guard) | `IB_EXPECTED_MASTER_CLIENT_ID` (default 11) | `11` |

If you ever change the bot's clientId, change the Gateway master to match (and
vice-versa). The bot logs a loud WARN at connect if `clientId != IB_EXPECTED_
MASTER_CLIENT_ID` (v19.34.190).

## ⚠️ The durable risk
The Gateway setting lives in the Gateway's own config (`jts.ini` on the Windows
box), **NOT in this repo**. It survives Gateway *restarts*, but is **LOST on a
Gateway reinstall or settings reset**. After any Gateway reinstall:
1. Configure → Settings → API → Settings → set **Master API client ID = 11**.
2. Restart the Gateway, then restart the bot.
3. Verify: in `/tmp/backend.log`, the connect line shows
   `clientId=11 matches documented master — cross-session/orphaned-order cancels enabled`.

## Quick verification after any restart
```bash
grep -iE "v19.34.190|clientId=" /tmp/backend.log | tail -5
```
Expect: `clientId=11 matches documented master …` (INFO), not the WARN.

## Related
- v19.34.189 — close guard uses authoritative `reqAllOpenOrders` (not the stale
  `_ib.trades()` cache) — handles externally-cancelled/dead orders.
- v19.34.190 — startup config guard (this runbook's WARN).
