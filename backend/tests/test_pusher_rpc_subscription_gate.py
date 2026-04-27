"""
Regression tests for the pusher RPC subscription gate (added 2026-04-28).

Goal: prevent regressions to the noisy `Read timed out` warnings that
plagued the Windows pusher whenever the DGX backend asked for
/rpc/latest-bars on symbols the pusher wasn't streaming. The fix gates
those calls behind a TTL-cached snapshot of /rpc/subscriptions.
"""

from unittest.mock import MagicMock, patch

import os
import pytest


@pytest.fixture(autouse=True)
def _reset_singleton():
    os.environ["IB_PUSHER_RPC_URL"] = "http://fake-pusher:8765"
    os.environ["ENABLE_LIVE_BAR_RPC"] = "true"
    from services import ib_pusher_rpc

    ib_pusher_rpc._client_instance = None
    yield
    ib_pusher_rpc._client_instance = None


def _mock_resp(payload, status=200):
    m = MagicMock(status_code=status)
    m.json.return_value = payload
    m.text = str(payload)
    return m


def test_subscriptions_returns_set_and_caches():
    from services import ib_pusher_rpc

    client = ib_pusher_rpc.get_pusher_rpc_client()
    payload = {"success": True, "symbols": ["SPY", "QQQ", "IWM"], "total": 3}
    with patch.object(
        client._session, "request", return_value=_mock_resp(payload)
    ) as mock_req:
        s1 = client.subscriptions()
        s2 = client.subscriptions()
    assert s1 == {"SPY", "QQQ", "IWM"}
    # Second call should be served from cache, not network.
    assert mock_req.call_count == 1
    assert s2 == s1


def test_is_pusher_subscribed_tri_state():
    from services import ib_pusher_rpc

    client = ib_pusher_rpc.get_pusher_rpc_client()
    payload = {"success": True, "symbols": ["SPY"], "total": 1}
    with patch.object(client._session, "request", return_value=_mock_resp(payload)):
        assert client.is_pusher_subscribed("SPY") is True
        assert client.is_pusher_subscribed("HD") is False

    # Pusher unreachable → tri-state None (caller must NOT gate, preserves
    # backward-compat with older pushers that don't have /rpc/subscriptions).
    client._subs_cache = None
    client._subs_cache_ts = 0.0
    fail = MagicMock(status_code=500)
    fail.text = "boom"
    with patch.object(client._session, "request", return_value=fail):
        assert client.is_pusher_subscribed("HD") is None


def test_latest_bars_skips_unsubscribed_symbol():
    """Core regression: latest_bars must NOT POST /rpc/latest-bars for a
    symbol the pusher isn't tracking — that's what causes the
    `Read timed out` warning storm."""
    from services import ib_pusher_rpc

    client = ib_pusher_rpc.get_pusher_rpc_client()
    sub_payload = {"success": True, "symbols": ["SPY"], "total": 1}
    with patch.object(
        client._session, "request", return_value=_mock_resp(sub_payload)
    ) as mock_req:
        bars = client.latest_bars("HD", "5 mins")
    assert bars is None
    # Only ONE request — the /rpc/subscriptions call — no /rpc/latest-bars.
    assert mock_req.call_count == 1
    called_url = mock_req.call_args.kwargs.get(
        "url", mock_req.call_args.args[1] if len(mock_req.call_args.args) > 1 else ""
    )
    assert "/rpc/subscriptions" in called_url


def test_latest_bars_proceeds_for_subscribed_symbol():
    from services import ib_pusher_rpc

    client = ib_pusher_rpc.get_pusher_rpc_client()

    def side_effect(method=None, url=None, **kwargs):
        if "/rpc/subscriptions" in url:
            return _mock_resp({"success": True, "symbols": ["SPY"]})
        if "/rpc/latest-bars" in url:
            return _mock_resp({"success": True, "bars": [{"o": 100, "c": 101}]})
        raise AssertionError(f"Unexpected url: {url}")

    with patch.object(client._session, "request", side_effect=side_effect):
        bars = client.latest_bars("SPY", "5 mins")
    assert bars == [{"o": 100, "c": 101}]


def test_latest_bars_batch_filters_unsubscribed_symbols():
    from services import ib_pusher_rpc

    client = ib_pusher_rpc.get_pusher_rpc_client()
    posted_bodies = []

    def side_effect(method=None, url=None, **kwargs):
        if "/rpc/subscriptions" in url:
            return _mock_resp({"success": True, "symbols": ["SPY", "QQQ"]})
        if "/rpc/latest-bars-batch" in url:
            posted_bodies.append(kwargs.get("json"))
            return _mock_resp(
                {
                    "success": True,
                    "results": [
                        {"symbol": "SPY", "success": True, "bars": [{"o": 1}]},
                        {"symbol": "QQQ", "success": True, "bars": [{"o": 2}]},
                    ],
                }
            )
        raise AssertionError(f"Unexpected url: {url}")

    with patch.object(client._session, "request", side_effect=side_effect):
        out = client.latest_bars_batch(
            ["SPY", "QQQ", "HD", "ARKK", "COP"], "5 mins"
        )

    assert set(out.keys()) == {"SPY", "QQQ"}
    # Only SPY/QQQ should have made it into the outgoing batch — the IB
    # pacing storm avoided.
    assert len(posted_bodies) == 1
    assert sorted(posted_bodies[0]["symbols"]) == ["QQQ", "SPY"]


def test_subs_cache_busted_on_subscribe_call():
    """If the backend triggers /rpc/subscribe, the subscription-set cache
    must be invalidated immediately so the next latest_bars sees the
    fresh set (instead of waiting up to TTL seconds)."""
    from services import ib_pusher_rpc

    client = ib_pusher_rpc.get_pusher_rpc_client()
    client._subs_cache = {"SPY"}
    # Future timestamp so it would otherwise be valid forever.
    client._subs_cache_ts = 9_999_999_999.0

    with patch.object(
        client._session,
        "request",
        return_value=_mock_resp({"success": True, "added": ["NVDA"]}),
    ):
        client._request("POST", "/rpc/subscribe", json_body={"symbols": ["NVDA"]})

    assert client._subs_cache is None
    assert client._subs_cache_ts == 0.0


def test_subs_cache_unaffected_by_unrelated_calls():
    from services import ib_pusher_rpc

    client = ib_pusher_rpc.get_pusher_rpc_client()
    client._subs_cache = {"SPY"}
    client._subs_cache_ts = 1234.0

    with patch.object(
        client._session,
        "request",
        return_value=_mock_resp({"success": True, "ok": True}),
    ):
        client._request("GET", "/rpc/health")

    # Health check must not bust the subscription cache.
    assert client._subs_cache == {"SPY"}
    assert client._subs_cache_ts == 1234.0
