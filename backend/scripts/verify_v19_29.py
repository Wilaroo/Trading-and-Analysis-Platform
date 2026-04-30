"""
verify_v19_29.py — Spark RTH validation harness for v19.29 hardening pass.

Operator runs this on Spark before/during the next RTH session to confirm
that all 5 v19.29 fixes are wired and observable end-to-end. Each check
queries a real backend surface (no mocks, no log greps) and renders a
colored PASS / FAIL / PENDING / NO_DATA verdict with a remediation hint.

USAGE
    # Single run — prints a summary table and exits.
    python -m backend.scripts.verify_v19_29

    # Watch mode — re-runs every 30s during RTH.
    python -m backend.scripts.verify_v19_29 --watch

    # Active reconcile probe (will POST /api/trading-bot/reconcile).
    python -m backend.scripts.verify_v19_29 --probe-reconcile SBUX

    # Custom backend URL (default: http://localhost:8001).
    BACKEND_URL=http://192.168.50.2:8001 python -m backend.scripts.verify_v19_29

WHAT IT VALIDATES (1 per v19.29 fix)
    A. Order intent dedup       → /api/diagnostic/trade-drops gate=safety_guardrail
                                   reason=intent_already_pending
    B. Direction-stable reconcile → /api/trading-bot/reconcile responds with
                                   skipped[].reason=direction_unstable when gate fires
    C. Wrong-direction phantom sweep → /api/sentcom/stream/history
                                   q=wrong_direction_phantom
    D. EOD no-new-entries gate   → /api/sentcom/stream/history
                                   q=eod_no_new_entries
    E. EOD flatten escalation    → /api/sentcom/stream/history
                                   q=eod_flatten_failed
    F. Bonus: pipeline health    → /api/sentcom/positions + /api/trading-bot/status
                                   smoke checks (HTTP 200, no exceptions, defaults sane)

The harness is READ-ONLY by default. The `--probe-reconcile` flag is the
ONLY active path and requires an explicit symbol argument.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib import request as _urlreq
from urllib.error import HTTPError, URLError

# ── ANSI colour codes (no external deps) ────────────────────────────────
_RESET = "\033[0m"
_BOLD = "\033[1m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_DIM = "\033[2m"

DEFAULT_BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8001")


# ── verdict types ───────────────────────────────────────────────────────
PASS = "PASS"
FAIL = "FAIL"
PENDING = "PENDING_RTH"
NO_DATA = "NO_DATA"
ERROR = "ERROR"


@dataclass
class CheckResult:
    name: str
    verdict: str
    detail: str = ""
    evidence: List[str] = field(default_factory=list)
    remediation: str = ""

    def color(self) -> str:
        if self.verdict == PASS:
            return _GREEN
        if self.verdict == FAIL or self.verdict == ERROR:
            return _RED
        if self.verdict == PENDING:
            return _YELLOW
        return _CYAN

    def render_row(self, name_w: int = 38) -> str:
        verd = f"{self.color()}{self.verdict:<11}{_RESET}"
        return f"  {self.name:<{name_w}} {verd}  {self.detail}"


# ── http helpers (stdlib only) ──────────────────────────────────────────
def _http_get(url: str, timeout: float = 6.0) -> Tuple[int, Any]:
    try:
        req = _urlreq.Request(url, method="GET")
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, {"raw": body}
    except HTTPError as e:
        try:
            body = e.read().decode("utf-8")
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {}
        return e.code, payload
    except URLError as e:
        return 0, {"error": f"{type(e).__name__}: {e.reason}"}
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


def _http_post(url: str, body: Dict[str, Any], timeout: float = 8.0) -> Tuple[int, Any]:
    try:
        data = json.dumps(body or {}).encode("utf-8")
        req = _urlreq.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            body_b = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(body_b)
            except json.JSONDecodeError:
                return resp.status, {"raw": body_b}
    except HTTPError as e:
        try:
            body_b = e.read().decode("utf-8")
            payload = json.loads(body_b) if body_b else {}
        except Exception:
            payload = {}
        return e.code, payload
    except URLError as e:
        return 0, {"error": f"{type(e).__name__}: {e.reason}"}
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


# ── time helpers ────────────────────────────────────────────────────────
def _is_rth_now() -> bool:
    """Best-effort RTH guess (US/Eastern 9:30-16:00 weekdays).

    Runs without pytz — converts UTC to ET using the static -5 (or -4 DST)
    offset best-effort. False positives are fine; the harness only uses
    this to soften PENDING verdicts during off-hours.
    """
    now_utc = datetime.now(timezone.utc)
    if now_utc.weekday() >= 5:
        return False
    # Naive DST: Mar-Nov use -4, else -5. Misses the exact transition
    # weekends but never misclassifies a full RTH session.
    et_offset_h = -4 if 3 <= now_utc.month <= 11 else -5
    et_hour = (now_utc.hour + et_offset_h) % 24
    et_minute = now_utc.minute
    et_minutes = et_hour * 60 + et_minute
    return 9 * 60 + 30 <= et_minutes <= 16 * 60


# ── the 6 checks ────────────────────────────────────────────────────────
def check_pipeline_health(backend: str) -> CheckResult:
    """Smoke check: backend up, positions endpoint serves, bot status readable."""
    status_code, _ = _http_get(f"{backend}/api/sentcom/positions")
    if status_code != 200:
        return CheckResult(
            name="F. Pipeline health smoke",
            verdict=FAIL,
            detail=f"/api/sentcom/positions returned HTTP {status_code or 'connection-error'}",
            remediation="Verify backend is running on Spark. `tail -n 100 /tmp/backend.log`",
        )

    status_code, status_payload = _http_get(f"{backend}/api/trading-bot/status")
    if status_code != 200:
        return CheckResult(
            name="F. Pipeline health smoke",
            verdict=FAIL,
            detail=f"/api/trading-bot/status returned HTTP {status_code}",
            remediation="Trading bot service may not be initialized. Check supervisor / nohup logs.",
        )

    risk = (status_payload or {}).get("risk_params") or {}
    rec_stop = risk.get("reconciled_default_stop_pct")
    rec_rr = risk.get("reconciled_default_rr")
    evidence = [
        f"reconciled_default_stop_pct={rec_stop}",
        f"reconciled_default_rr={rec_rr}",
    ]
    if rec_stop is None or rec_rr is None:
        return CheckResult(
            name="F. Pipeline health smoke",
            verdict=FAIL,
            detail="risk_params missing v19.24 reconciled_default_* fields",
            evidence=evidence,
            remediation="Backend pre-v19.24. Pull + restart.",
        )
    return CheckResult(
        name="F. Pipeline health smoke",
        verdict=PASS,
        detail=f"backend live · reconciled_default_stop={rec_stop}% rr={rec_rr}",
        evidence=evidence,
    )


def check_intent_dedup(backend: str, minutes: int = 240) -> CheckResult:
    """A. Order intent dedup — confirm the gate fired at least once OR
    confirm the wiring is in place via instrumentation.

    During RTH, fires when a duplicate order intent is blocked. Outside
    RTH, returns PENDING_RTH (no order traffic).
    """
    url = f"{backend}/api/diagnostic/trade-drops?minutes={minutes}&limit=200"
    status_code, payload = _http_get(url)
    if status_code != 200:
        return CheckResult(
            name="A. Order intent dedup",
            verdict=ERROR,
            detail=f"/trade-drops returned HTTP {status_code}",
            remediation="Diagnostic endpoint unreachable. Check trade_drop_recorder service.",
        )

    recent = (payload or {}).get("recent") or []
    matches = [r for r in recent if (r.get("reason") or "").lower().find("intent_already_pending") >= 0]

    if matches:
        return CheckResult(
            name="A. Order intent dedup",
            verdict=PASS,
            detail=f"{len(matches)} intent_already_pending block(s) in last {minutes}min",
            evidence=[f"{m.get('symbol')} {m.get('direction')} @ ts={m.get('ts')}" for m in matches[:3]],
        )

    if not _is_rth_now():
        return CheckResult(
            name="A. Order intent dedup",
            verdict=PENDING,
            detail="0 dedup blocks recorded (off-hours — no order traffic)",
            remediation="Re-run during RTH. Expect blocks on busy scanner cycles.",
        )

    # During RTH but no blocks: could be legitimately healthy (no dups
    # happened) OR the wiring is silently broken. Surface as NO_DATA so
    # operator interprets contextually.
    return CheckResult(
        name="A. Order intent dedup",
        verdict=NO_DATA,
        detail=f"0 intent_already_pending in last {minutes}min during RTH",
        remediation="If you saw duplicate cancellations in IB today, the gate may not be firing. Inspect /trade-drops and intent dedup logs.",
    )


def check_direction_stability(backend: str, minutes: int = 1440) -> CheckResult:
    """B. Direction-stable reconcile gate — search stream history for
    direction_unstable events OR confirm reconcile endpoint refuses to
    claim during instability.

    A direct active probe is risky in a live account (would materialize
    a real bot trade), so we look for evidence of the gate firing in
    historical events instead.
    """
    url = f"{backend}/api/sentcom/stream/history?minutes={minutes}&q=direction_unstable&limit=50"
    status_code, payload = _http_get(url)
    if status_code != 200:
        return CheckResult(
            name="B. Direction-stable reconcile",
            verdict=ERROR,
            detail=f"/stream/history returned HTTP {status_code}",
        )
    msgs = (payload or {}).get("messages") or []

    if msgs:
        return CheckResult(
            name="B. Direction-stable reconcile",
            verdict=PASS,
            detail=f"{len(msgs)} direction_unstable observation(s) in last {minutes}min",
            evidence=[f"{m.get('symbol') or '-'} · {(m.get('content') or '')[:80]}" for m in msgs[:3]],
        )

    # No direction-unstable events seen — could be healthy (no reconciles
    # attempted) or the gate isn't surfacing. Surface NO_DATA for operator
    # context.
    return CheckResult(
        name="B. Direction-stable reconcile",
        verdict=NO_DATA,
        detail=f"0 direction_unstable events in last {minutes}min",
        remediation="If you've not clicked 'Reconcile N' since the v19.29 deploy, this is expected. Click reconcile on a real orphan to fire the gate, or run --probe-reconcile SYMBOL.",
    )


def check_phantom_sweep(backend: str, minutes: int = 1440) -> CheckResult:
    """C. Wrong-direction phantom sweep — search stream history for
    auto-sweep events.
    """
    url = f"{backend}/api/sentcom/stream/history?minutes={minutes}&q=wrong_direction_phantom&limit=50"
    status_code, payload = _http_get(url)
    if status_code != 200:
        return CheckResult(
            name="C. Wrong-direction phantom sweep",
            verdict=ERROR,
            detail=f"/stream/history returned HTTP {status_code}",
        )
    msgs = (payload or {}).get("messages") or []

    if msgs:
        return CheckResult(
            name="C. Wrong-direction phantom sweep",
            verdict=PASS,
            detail=f"{len(msgs)} phantom-sweep event(s) in last {minutes}min",
            evidence=[f"{m.get('symbol') or '-'} · {(m.get('content') or '')[:80]}" for m in msgs[:3]],
        )
    return CheckResult(
        name="C. Wrong-direction phantom sweep",
        verdict=NO_DATA,
        detail=f"0 sweep events in last {minutes}min",
        remediation="Healthy state if no direction-mismatched bot trades exist. The handoff predicted SOFI SHORT 2014sh would auto-sweep at startup post-pull — verify it cleared from /api/sentcom/positions.",
    )


def check_eod_no_new_entries(backend: str, minutes: int = 240) -> CheckResult:
    """D. EOD no-new-entries gate — soft 3:45pm + hard 3:55pm cuts."""
    url = f"{backend}/api/sentcom/stream/history?minutes={minutes}&q=eod_no_new_entries&limit=50"
    status_code, payload = _http_get(url)
    if status_code != 200:
        return CheckResult(
            name="D. EOD no-new-entries gate",
            verdict=ERROR,
            detail=f"/stream/history returned HTTP {status_code}",
        )
    msgs = (payload or {}).get("messages") or []
    soft = [m for m in msgs if "soft" in (m.get("content") or "").lower() or m.get("action_type") == "eod_no_new_entries_soft"]
    hard = [m for m in msgs if "hard" in (m.get("content") or "").lower() or m.get("action_type") == "eod_no_new_entries_hard"]

    if soft or hard:
        return CheckResult(
            name="D. EOD no-new-entries gate",
            verdict=PASS,
            detail=f"{len(soft)} soft(3:45-3:55pm) · {len(hard)} hard(post-3:55pm) in {minutes}min",
            evidence=[f"{m.get('symbol') or '-'} · {(m.get('content') or '')[:80]}" for m in (soft + hard)[:3]],
        )
    if not _is_rth_now():
        return CheckResult(
            name="D. EOD no-new-entries gate",
            verdict=PENDING,
            detail="off-hours — gate only fires 3:45-3:55pm ET on weekdays",
            remediation="Re-run between 3:45-3:55pm ET to validate.",
        )
    return CheckResult(
        name="D. EOD no-new-entries gate",
        verdict=NO_DATA,
        detail=f"0 EOD entry-gate events in last {minutes}min",
        remediation="Will fire only between 3:45-3:55pm ET. Re-run during that window.",
    )


def check_eod_flatten_alarm(backend: str, minutes: int = 1440) -> CheckResult:
    """E. EOD flatten escalation alarm — fires only when EOD flatten fails."""
    url = f"{backend}/api/sentcom/stream/history?minutes={minutes}&q=eod_flatten_failed&limit=20"
    status_code, payload = _http_get(url)
    if status_code != 200:
        return CheckResult(
            name="E. EOD flatten escalation alarm",
            verdict=ERROR,
            detail=f"/stream/history returned HTTP {status_code}",
        )
    msgs = (payload or {}).get("messages") or []

    if msgs:
        return CheckResult(
            name="E. EOD flatten escalation alarm",
            verdict=PASS,
            detail=f"{len(msgs)} flatten-fail alarm(s) recorded — operator visibility working",
            evidence=[f"{m.get('symbol') or '-'} · {(m.get('content') or '')[:80]}" for m in msgs[:3]],
        )
    return CheckResult(
        name="E. EOD flatten escalation alarm",
        verdict=NO_DATA,
        detail=f"0 flatten-fail alarms in last {minutes}min — healthy if EOD flatten fully succeeded",
        remediation="The alarm only fires when ≥1 close fails. Confirm /api/trading-bot/eod-status shows last EOD as 'complete' rather than 'alarm'.",
    )


# ── optional active probe ───────────────────────────────────────────────
def probe_reconcile(backend: str, symbol: str) -> CheckResult:
    """Active probe — POST /api/trading-bot/reconcile on a single symbol.

    This is a side-effect call; only run with operator intent.
    """
    if not symbol:
        return CheckResult(
            name="↪ Active reconcile probe",
            verdict=ERROR,
            detail="--probe-reconcile requires a symbol",
        )
    url = f"{backend}/api/trading-bot/reconcile"
    status_code, payload = _http_post(url, {"symbols": [symbol.upper()]})
    if status_code != 200:
        return CheckResult(
            name="↪ Active reconcile probe",
            verdict=FAIL,
            detail=f"HTTP {status_code} — {(payload or {}).get('detail') or (payload or {}).get('error') or '?'}",
        )
    rec = (payload or {}).get("reconciled") or []
    skipped = (payload or {}).get("skipped") or []
    direction_unstable = [s for s in skipped if s.get("reason") == "direction_unstable"]
    detail_parts = [f"{len(rec)} reconciled · {len(skipped)} skipped"]
    if direction_unstable:
        detail_parts.append(f"{len(direction_unstable)} direction_unstable")
    return CheckResult(
        name=f"↪ Reconcile probe: {symbol.upper()}",
        verdict=PASS,
        detail=" · ".join(detail_parts),
        evidence=[json.dumps(s, default=str)[:120] for s in (skipped + rec)[:3]],
    )


# ── orchestration ───────────────────────────────────────────────────────
def run_all(backend: str, history_minutes: int) -> List[CheckResult]:
    return [
        check_pipeline_health(backend),
        check_intent_dedup(backend, minutes=min(history_minutes, 360)),
        check_direction_stability(backend, minutes=history_minutes),
        check_phantom_sweep(backend, minutes=history_minutes),
        check_eod_no_new_entries(backend, minutes=min(history_minutes, 480)),
        check_eod_flatten_alarm(backend, minutes=history_minutes),
    ]


def render_summary(results: List[CheckResult], backend: str) -> str:
    lines = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rth_tag = "RTH" if _is_rth_now() else "off-hours"
    lines.append("")
    lines.append(f"{_BOLD}v19.29 verification — {now} ({rth_tag}) — backend={backend}{_RESET}")
    lines.append(f"{_DIM}{'─' * 78}{_RESET}")
    for r in results:
        lines.append(r.render_row())
        if r.evidence:
            for ev in r.evidence:
                lines.append(f"      {_DIM}↳ {ev}{_RESET}")
        if r.remediation and r.verdict in (FAIL, NO_DATA, PENDING, ERROR):
            lines.append(f"      {_DIM}fix: {r.remediation}{_RESET}")
    lines.append(f"{_DIM}{'─' * 78}{_RESET}")

    counts = {PASS: 0, FAIL: 0, PENDING: 0, NO_DATA: 0, ERROR: 0}
    for r in results:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    summary = (
        f"  {_GREEN}PASS={counts[PASS]}{_RESET} · "
        f"{_RED}FAIL={counts[FAIL]}{_RESET} · "
        f"{_YELLOW}PENDING={counts[PENDING]}{_RESET} · "
        f"{_CYAN}NO_DATA={counts[NO_DATA]}{_RESET} · "
        f"{_RED}ERROR={counts[ERROR]}{_RESET}"
    )
    lines.append(summary)
    lines.append("")
    return "\n".join(lines)


def overall_exit_code(results: List[CheckResult]) -> int:
    """exit 0 if no FAIL/ERROR, else 1."""
    if any(r.verdict in (FAIL, ERROR) for r in results):
        return 1
    return 0


# ── CLI entrypoint ──────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="v19.29 hardening pass validator")
    parser.add_argument("--backend", default=DEFAULT_BACKEND, help=f"Backend URL (default {DEFAULT_BACKEND})")
    parser.add_argument("--watch", action="store_true", help="Re-run every 30s until Ctrl-C")
    parser.add_argument("--watch-interval", type=int, default=30, help="Watch interval seconds (default 30)")
    parser.add_argument("--history-minutes", type=int, default=1440, help="History window for stream queries (default 1440 = 24h)")
    parser.add_argument("--probe-reconcile", type=str, default=None, help="Active POST to /api/trading-bot/reconcile for a single symbol — USE WITH CARE")
    parser.add_argument("--json", action="store_true", help="Render results as JSON")
    args = parser.parse_args(argv)

    def _once() -> int:
        results = run_all(args.backend, args.history_minutes)
        if args.probe_reconcile:
            results.append(probe_reconcile(args.backend, args.probe_reconcile))
        if args.json:
            print(json.dumps([r.__dict__ for r in results], indent=2, default=str))
        else:
            print(render_summary(results, args.backend))
        return overall_exit_code(results)

    if not args.watch:
        return _once()

    print(f"{_DIM}watching every {args.watch_interval}s — Ctrl-C to stop{_RESET}")
    try:
        while True:
            _once()
            time.sleep(args.watch_interval)
    except KeyboardInterrupt:
        print(f"\n{_DIM}stopped.{_RESET}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
