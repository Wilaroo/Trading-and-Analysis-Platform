"""
test_verify_v19_29_harness.py — unit tests for the v19.29 RTH validation
script (`backend/scripts/verify_v19_29.py`).

We don't hit a live backend here — every check function is exercised
against monkey-patched HTTP fixtures so the harness can be regressed
without Spark / IB / RTH access.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "backend" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import verify_v19_29 as v  # noqa: E402


# ── tiny fake-http harness ──────────────────────────────────────────────
class _FakeHttp:
    """Holds a routing table mapping URL substrings → (status, payload)."""

    def __init__(self):
        self.routes: Dict[str, Tuple[int, Any]] = {}
        self.last_post_body: Dict[str, Any] | None = None

    def get(self, url: str, timeout: float = 6.0):
        for needle, (status, payload) in self.routes.items():
            if needle in url:
                return status, payload
        return 404, {"error": f"no fake route matches {url}"}

    def post(self, url: str, body: Dict[str, Any], timeout: float = 8.0):
        self.last_post_body = body
        for needle, (status, payload) in self.routes.items():
            if needle in url:
                return status, payload
        return 404, {"error": f"no fake route matches {url}"}


@pytest.fixture
def fake(monkeypatch):
    f = _FakeHttp()
    monkeypatch.setattr(v, "_http_get", f.get)
    monkeypatch.setattr(v, "_http_post", f.post)
    return f


# ── pipeline health smoke check (F) ─────────────────────────────────────
def test_pipeline_health_pass(fake):
    fake.routes = {
        "/api/sentcom/positions": (200, {"positions": []}),
        "/api/trading-bot/status": (
            200,
            {"risk_params": {"reconciled_default_stop_pct": 2.0, "reconciled_default_rr": 2.0}},
        ),
    }
    r = v.check_pipeline_health("http://x")
    assert r.verdict == v.PASS
    assert "stop=2.0" in r.detail


def test_pipeline_health_backend_down(fake):
    fake.routes = {"/api/sentcom/positions": (0, {"error": "connection refused"})}
    r = v.check_pipeline_health("http://x")
    assert r.verdict == v.FAIL
    assert "connection-error" in r.detail or "HTTP 0" in r.detail


def test_pipeline_health_missing_v19_24_defaults(fake):
    fake.routes = {
        "/api/sentcom/positions": (200, {"positions": []}),
        "/api/trading-bot/status": (200, {"risk_params": {}}),
    }
    r = v.check_pipeline_health("http://x")
    assert r.verdict == v.FAIL
    assert "reconciled_default_*" in r.detail


# ── A. intent dedup ─────────────────────────────────────────────────────
def test_intent_dedup_pass_when_blocks_recorded(fake):
    fake.routes = {
        "/api/diagnostic/trade-drops": (
            200,
            {
                "recent": [
                    {
                        "ts": "2026-05-01T19:32:00Z",
                        "gate": "safety_guardrail",
                        "symbol": "SOFI",
                        "direction": "long",
                        "reason": "intent_already_pending — same SOFI long pending",
                    }
                ]
            },
        )
    }
    r = v.check_intent_dedup("http://x")
    assert r.verdict == v.PASS
    assert "intent_already_pending" in r.detail


def test_intent_dedup_no_data_when_off_hours(fake, monkeypatch):
    monkeypatch.setattr(v, "_is_rth_now", lambda: False)
    fake.routes = {"/api/diagnostic/trade-drops": (200, {"recent": []})}
    r = v.check_intent_dedup("http://x")
    assert r.verdict == v.PENDING


def test_intent_dedup_no_data_during_rth(fake, monkeypatch):
    monkeypatch.setattr(v, "_is_rth_now", lambda: True)
    fake.routes = {"/api/diagnostic/trade-drops": (200, {"recent": []})}
    r = v.check_intent_dedup("http://x")
    assert r.verdict == v.NO_DATA


# ── B. direction stability ──────────────────────────────────────────────
def test_direction_stability_pass(fake):
    fake.routes = {
        "/api/sentcom/stream/history": (
            200,
            {
                "messages": [
                    {
                        "symbol": "SOFI",
                        "content": "🛑 Reconcile refused — direction_unstable < 30s",
                        "action_type": "reconcile_skip",
                    }
                ]
            },
        )
    }
    r = v.check_direction_stability("http://x")
    assert r.verdict == v.PASS
    assert "direction_unstable" in r.detail


def test_direction_stability_no_data(fake):
    fake.routes = {"/api/sentcom/stream/history": (200, {"messages": []})}
    r = v.check_direction_stability("http://x")
    assert r.verdict == v.NO_DATA


# ── C. phantom sweep ────────────────────────────────────────────────────
def test_phantom_sweep_pass(fake):
    fake.routes = {
        "/api/sentcom/stream/history": (
            200,
            {
                "messages": [
                    {
                        "symbol": "SOFI",
                        "content": "🧹 Auto-swept SOFI SHORT phantom (wrong_direction_phantom)",
                        "action_type": "wrong_direction_phantom_swept",
                    }
                ]
            },
        )
    }
    r = v.check_phantom_sweep("http://x")
    assert r.verdict == v.PASS


# ── D. EOD no-new-entries ───────────────────────────────────────────────
def test_eod_no_new_entries_pass_with_soft_and_hard(fake):
    fake.routes = {
        "/api/sentcom/stream/history": (
            200,
            {
                "messages": [
                    {"symbol": "BP", "content": "Late-day BP soft warn", "action_type": "eod_no_new_entries_soft"},
                    {"symbol": "HOOD", "content": "⏰ HOOD past 3:55pm hard cut", "action_type": "eod_no_new_entries_hard"},
                ]
            },
        )
    }
    r = v.check_eod_no_new_entries("http://x")
    assert r.verdict == v.PASS
    assert "soft" in r.detail and "hard" in r.detail


def test_eod_no_new_entries_pending_off_hours(fake, monkeypatch):
    monkeypatch.setattr(v, "_is_rth_now", lambda: False)
    fake.routes = {"/api/sentcom/stream/history": (200, {"messages": []})}
    r = v.check_eod_no_new_entries("http://x")
    assert r.verdict == v.PENDING


# ── E. EOD flatten alarm ────────────────────────────────────────────────
def test_eod_flatten_alarm_pass(fake):
    fake.routes = {
        "/api/sentcom/stream/history": (
            200,
            {
                "messages": [
                    {"symbol": "SOFI", "content": "🚨 [CRITICAL] EOD FLATTEN FAILED", "action_type": "eod_flatten_failed"}
                ]
            },
        )
    }
    r = v.check_eod_flatten_alarm("http://x")
    assert r.verdict == v.PASS


def test_eod_flatten_alarm_no_data(fake):
    fake.routes = {"/api/sentcom/stream/history": (200, {"messages": []})}
    r = v.check_eod_flatten_alarm("http://x")
    assert r.verdict == v.NO_DATA


# ── active reconcile probe ──────────────────────────────────────────────
def test_probe_reconcile_pass(fake):
    fake.routes = {
        "/api/trading-bot/reconcile": (
            200,
            {
                "reconciled": [],
                "skipped": [
                    {"symbol": "SBUX", "reason": "direction_unstable", "stability_required_seconds": 30}
                ],
            },
        )
    }
    r = v.probe_reconcile("http://x", "sbux")
    assert r.verdict == v.PASS
    assert fake.last_post_body == {"symbols": ["SBUX"]}
    assert "1 direction_unstable" in r.detail


def test_probe_reconcile_requires_symbol():
    r = v.probe_reconcile("http://x", "")
    assert r.verdict == v.ERROR


def test_probe_reconcile_endpoint_500(fake):
    fake.routes = {"/api/trading-bot/reconcile": (500, {"detail": "bot not initialized"})}
    r = v.probe_reconcile("http://x", "SBUX")
    assert r.verdict == v.FAIL
    assert "500" in r.detail


# ── overall exit code logic ─────────────────────────────────────────────
def test_overall_exit_code_zero_on_no_fail():
    results = [
        v.CheckResult(name="A", verdict=v.PASS),
        v.CheckResult(name="B", verdict=v.PENDING),
        v.CheckResult(name="C", verdict=v.NO_DATA),
    ]
    assert v.overall_exit_code(results) == 0


def test_overall_exit_code_nonzero_on_fail():
    results = [
        v.CheckResult(name="A", verdict=v.PASS),
        v.CheckResult(name="B", verdict=v.FAIL),
    ]
    assert v.overall_exit_code(results) == 1


def test_overall_exit_code_nonzero_on_error():
    results = [v.CheckResult(name="A", verdict=v.ERROR)]
    assert v.overall_exit_code(results) == 1


# ── render summary smoke ────────────────────────────────────────────────
def test_render_summary_includes_all_checks():
    results = [
        v.CheckResult(name="A. dedup", verdict=v.PASS, detail="3 blocks", evidence=["AAPL long"]),
        v.CheckResult(name="B. direction", verdict=v.NO_DATA, detail="empty", remediation="run probe"),
    ]
    text = v.render_summary(results, "http://x")
    assert "A. dedup" in text
    assert "B. direction" in text
    assert "AAPL long" in text
    assert "PASS=1" in text
    assert "NO_DATA=1" in text
    assert "fix: run probe" in text


# ── run_all wires every check + handles probe ──────────────────────────
def test_run_all_returns_six_checks(fake):
    fake.routes = {
        "/api/sentcom/positions": (200, {"positions": []}),
        "/api/trading-bot/status": (200, {"risk_params": {"reconciled_default_stop_pct": 2.0, "reconciled_default_rr": 2.0}}),
        "/api/diagnostic/trade-drops": (200, {"recent": []}),
        "/api/sentcom/stream/history": (200, {"messages": []}),
    }
    results = v.run_all("http://x", history_minutes=240)
    assert len(results) == 6
    names = [r.name for r in results]
    assert any("Pipeline health" in n for n in names)
    assert any("intent dedup" in n for n in names)
    assert any("Direction-stable" in n for n in names)
    assert any("phantom sweep" in n for n in names)
    assert any("EOD no-new-entries" in n for n in names)
    assert any("EOD flatten" in n for n in names)
