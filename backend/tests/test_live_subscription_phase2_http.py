"""
Phase 2 Live Subscription Layer — live HTTP smoke tests.

Exercises the running backend (via REACT_APP_BACKEND_URL or APP_URL, falling
back to http://localhost:8001) and verifies the ref-counted watchlist
endpoints and Phase 1 regression endpoints behave per spec in a preview env
with NO Windows pusher reachable (pusher_ok:false is EXPECTED).
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("APP_URL")
    or "http://localhost:8001"
).rstrip("/")

# Unique symbols per test-run so leftover state doesn't poison tests
RUN_TAG = uuid.uuid4().hex[:4].upper()
SYM_A = f"T{RUN_TAG}A"[:6]
SYM_B = f"T{RUN_TAG}B"[:6]
SYM_C = f"T{RUN_TAG}C"[:6]
SYM_D = f"T{RUN_TAG}D"[:6]


@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _cleanup(http, sym):
    # Best effort — drain any ref_count we may have left
    for _ in range(10):
        r = http.post(f"{BASE_URL}/api/live/unsubscribe/{sym}", timeout=10)
        if r.status_code != 200:
            break
        body = r.json()
        if not body.get("accepted") or body.get("fully_unsubscribed"):
            break


# ---------- Phase 1 regression -----------------------------------------

class TestPhase1Regression:
    def test_pusher_rpc_health_reachable_false(self, http):
        r = http.get(f"{BASE_URL}/api/live/pusher-rpc-health", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert "reachable" in body
        assert body["reachable"] is False, f"Expected reachable:false in preview env, got {body}"
        assert "client" in body
        assert "market_state" in body

    def test_ttl_plan(self, http):
        r = http.get(f"{BASE_URL}/api/live/ttl-plan", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert "ttl_by_state" in body
        assert body["ttl_by_state"]["rth"] == 30
        assert body["ttl_by_state"]["extended"] == 120
        assert body["ttl_by_state"]["overnight"] == 900
        assert body["ttl_by_state"]["weekend"] == 3600

    def test_cache_invalidate_spy(self, http):
        r = http.post(f"{BASE_URL}/api/live/cache-invalidate?symbol=SPY", timeout=10)
        assert r.status_code == 200
        body = r.json()
        # Either succeeded (deleted>=0) or returned cache_not_initialised, both OK
        assert "success" in body
        assert "deleted" in body or "error" in body

    def test_sentcom_chart_no_crash(self, http):
        r = http.get(
            f"{BASE_URL}/api/sentcom/chart?symbol=SPY&timeframe=5min&days=5",
            timeout=30,
        )
        # success=false tolerated but status code must NOT be 5xx
        assert r.status_code < 500, f"Chart endpoint crashed: {r.status_code} {r.text[:300]}"


# ---------- Phase 2: subscribe / unsubscribe ---------------------------

class TestSubscribeUnsubscribe:
    def test_subscribe_first_call_newly_subscribed_true(self, http):
        _cleanup(http, SYM_A)
        r = http.post(f"{BASE_URL}/api/live/subscribe/{SYM_A}", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["accepted"] is True
        assert body["newly_subscribed"] is True
        assert body["ref_count"] == 1
        assert body["symbol"] == SYM_A
        # pusher not running → pusher_ok must be false, not a crash
        assert body["pusher_ok"] is False, f"Expected pusher_ok:false, got {body}"
        assert "active_subscriptions" in body

    def test_subscribe_second_call_newly_subscribed_false(self, http):
        r = http.post(f"{BASE_URL}/api/live/subscribe/{SYM_A}", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["accepted"] is True
        assert body["newly_subscribed"] is False
        assert body["ref_count"] == 2

    def test_unsubscribe_decrements_refcount(self, http):
        r = http.post(f"{BASE_URL}/api/live/unsubscribe/{SYM_A}", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["accepted"] is True
        assert body["fully_unsubscribed"] is False
        assert body["ref_count"] == 1

    def test_unsubscribe_to_zero_fully_unsubscribed(self, http):
        r = http.post(f"{BASE_URL}/api/live/unsubscribe/{SYM_A}", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["accepted"] is True
        assert body["fully_unsubscribed"] is True
        assert body["ref_count"] == 0

    def test_unsubscribe_unknown_symbol_rejected(self, http):
        r = http.post(f"{BASE_URL}/api/live/unsubscribe/ZZUNKNOWNZZ", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["accepted"] is False
        assert body.get("reason") == "not_subscribed"


# ---------- Phase 2: heartbeat -----------------------------------------

class TestHeartbeat:
    def test_heartbeat_refreshes_active_sub(self, http):
        _cleanup(http, SYM_B)
        sub = http.post(f"{BASE_URL}/api/live/subscribe/{SYM_B}", timeout=10).json()
        assert sub["accepted"] is True

        # Grab initial idle/age from list
        ls1 = http.get(f"{BASE_URL}/api/live/subscriptions", timeout=10).json()
        row1 = next((s for s in ls1["subscriptions"] if s["symbol"] == SYM_B), None)
        assert row1 is not None
        first_hb = row1["last_heartbeat_at"]

        time.sleep(1.2)
        hb = http.post(f"{BASE_URL}/api/live/heartbeat/{SYM_B}", timeout=10)
        assert hb.status_code == 200
        hb_body = hb.json()
        assert hb_body["accepted"] is True
        assert hb_body["ref_count"] >= 1

        ls2 = http.get(f"{BASE_URL}/api/live/subscriptions", timeout=10).json()
        row2 = next((s for s in ls2["subscriptions"] if s["symbol"] == SYM_B), None)
        assert row2 is not None
        assert row2["last_heartbeat_at"] >= first_hb

        _cleanup(http, SYM_B)

    def test_heartbeat_unknown_symbol_rejected(self, http):
        r = http.post(f"{BASE_URL}/api/live/heartbeat/ZZNOPEZZ", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["accepted"] is False
        assert body.get("reason") == "not_subscribed"


# ---------- Phase 2: list subscriptions --------------------------------

class TestListSubscriptions:
    def test_list_shape(self, http):
        _cleanup(http, SYM_C)
        http.post(f"{BASE_URL}/api/live/subscribe/{SYM_C}", timeout=10)

        r = http.get(f"{BASE_URL}/api/live/subscriptions", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert "active_count" in body and isinstance(body["active_count"], int)
        assert body["max_subscriptions"] == 60
        assert body["heartbeat_ttl_seconds"] == 300
        assert isinstance(body["subscriptions"], list)

        row = next((s for s in body["subscriptions"] if s["symbol"] == SYM_C), None)
        assert row is not None, f"{SYM_C} missing from list: {body}"
        for key in (
            "symbol", "ref_count", "first_subscribed_at",
            "last_heartbeat_at", "age_seconds", "idle_seconds",
        ):
            assert key in row, f"Missing key {key} in row {row}"
        assert row["ref_count"] >= 1
        assert row["age_seconds"] >= 0
        assert row["idle_seconds"] >= 0
        # Timestamps are ISO Z strings
        assert row["first_subscribed_at"].endswith("Z")
        assert row["last_heartbeat_at"].endswith("Z")

        _cleanup(http, SYM_C)

    def test_active_count_never_exceeds_cap(self, http):
        r = http.get(f"{BASE_URL}/api/live/subscriptions", timeout=10).json()
        assert r["active_count"] <= r["max_subscriptions"]


# ---------- Phase 2: ref-count correctness -----------------------------

class TestRefCountCorrectness:
    def test_triple_sub_double_unsub_leaves_refcount_one(self, http):
        _cleanup(http, SYM_D)
        for i in range(3):
            r = http.post(f"{BASE_URL}/api/live/subscribe/{SYM_D}", timeout=10).json()
            assert r["accepted"] is True
            assert r["ref_count"] == i + 1

        r = http.post(f"{BASE_URL}/api/live/unsubscribe/{SYM_D}", timeout=10).json()
        assert r["fully_unsubscribed"] is False
        assert r["ref_count"] == 2

        r = http.post(f"{BASE_URL}/api/live/unsubscribe/{SYM_D}", timeout=10).json()
        assert r["fully_unsubscribed"] is False
        assert r["ref_count"] == 1

        # Verify via list — should still be present with ref_count 1
        ls = http.get(f"{BASE_URL}/api/live/subscriptions", timeout=10).json()
        row = next((s for s in ls["subscriptions"] if s["symbol"] == SYM_D), None)
        assert row is not None
        assert row["ref_count"] == 1

        # Final unsubscribe → fully removed
        r = http.post(f"{BASE_URL}/api/live/unsubscribe/{SYM_D}", timeout=10).json()
        assert r["fully_unsubscribed"] is True
        assert r["ref_count"] == 0

        ls = http.get(f"{BASE_URL}/api/live/subscriptions", timeout=10).json()
        row = next((s for s in ls["subscriptions"] if s["symbol"] == SYM_D), None)
        assert row is None, f"{SYM_D} still present after full unsubscribe"


# ---------- Phase 2: empty-symbol rejection ----------------------------

class TestEmptySymbolRejection:
    @pytest.mark.parametrize("sym", ["%20", "%20%20"])
    def test_empty_whitespace_symbol_rejected_subscribe(self, http, sym):
        # URL-encoded whitespace. FastAPI strips path segments so truly empty
        # is a 404 from the router — whitespace hits the handler.
        r = http.post(f"{BASE_URL}/api/live/subscribe/{sym}", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["accepted"] is False
        assert body.get("reason") == "empty_symbol"

    def test_empty_whitespace_symbol_rejected_unsubscribe(self, http):
        r = http.post(f"{BASE_URL}/api/live/unsubscribe/%20", timeout=10)
        assert r.status_code == 200
        assert r.json()["accepted"] is False

    def test_empty_whitespace_symbol_rejected_heartbeat(self, http):
        r = http.post(f"{BASE_URL}/api/live/heartbeat/%20", timeout=10)
        assert r.status_code == 200
        assert r.json()["accepted"] is False


# ---------- Phase 2: manual sweep --------------------------------------

class TestSweep:
    def test_sweep_returns_shape(self, http):
        r = http.post(f"{BASE_URL}/api/live/subscriptions/sweep", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert "expired_count" in body
        assert "expired" in body
        assert isinstance(body["expired"], list)
        assert body["expired_count"] == len(body["expired"])
