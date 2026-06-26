"""
V6 §3 app-state — _compute_app_state pure logic (2026-06-26).

Key nuance: in ib-direct, the pusher RPC-pull path can go yellow/red while
push-only data keeps flowing (`push_fresh=True`). That must stay CYAN, not
amber/rose. Only ACTUALLY-stale pushes escalate.
"""
from routers.system_router import _compute_app_state


def _health(overall="green", pusher_status="green", push_fresh=True,
            ib_status="green", extra_yellow=None):
    subs = [
        {"name": "mongo", "status": "green", "detail": "ok"},
        {"name": "pusher_rpc", "status": pusher_status, "detail": "pusher detail",
         "metrics": {"push_fresh": push_fresh}},
        {"name": "ib_gateway", "status": ib_status, "detail": "ib detail"},
    ]
    if extra_yellow:
        subs.append({"name": extra_yellow, "status": "yellow", "detail": "degraded"})
    counts = {"green": 0, "yellow": 0, "red": 0}
    for s in subs:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    return {"overall": overall, "counts": counts, "subsystems": subs}


SAFE = {"kill_switch_active": False, "scanner_paused": False, "flatten_in_progress": False}


def test_all_green_is_cyan():
    v = _compute_app_state(_health(), SAFE)
    assert v["state"] == "cyan"


def test_pusher_yellow_but_push_fresh_stays_cyan():
    # THE ib-direct case: RPC-pull 503 (yellow) but data flowing → cyan.
    v = _compute_app_state(_health(pusher_status="yellow", push_fresh=True), SAFE)
    assert v["state"] == "cyan", v
    assert v["signals"]["pusher_push_fresh"] is True


def test_pusher_yellow_and_stale_is_amber():
    v = _compute_app_state(_health(pusher_status="yellow", push_fresh=False), SAFE)
    assert v["state"] == "amber", v


def test_pusher_red_but_push_fresh_is_not_rose():
    # red pull path but data flowing → benign → cyan (not rose).
    v = _compute_app_state(_health(pusher_status="red", push_fresh=True), SAFE)
    assert v["state"] == "cyan", v


def test_pusher_red_and_stale_is_rose():
    v = _compute_app_state(_health(pusher_status="red", push_fresh=False), SAFE)
    assert v["state"] == "rose", v


def test_ib_gateway_red_is_rose():
    v = _compute_app_state(_health(ib_status="red"), SAFE)
    assert v["state"] == "rose", v


def test_kill_switch_is_rose():
    v = _compute_app_state(_health(), {**SAFE, "kill_switch_active": True,
                                       "kill_switch_reason": "manual halt"})
    assert v["state"] == "rose"
    assert any("kill-switch" in r for r in v["reasons"])


def test_scanner_paused_is_amber():
    v = _compute_app_state(_health(), {**SAFE, "scanner_paused": True})
    assert v["state"] == "amber"


def test_other_yellow_subsystem_is_amber():
    # a non-pusher yellow subsystem still escalates to amber.
    v = _compute_app_state(_health(extra_yellow="historical_queue"), SAFE)
    assert v["state"] == "amber", v


def test_pusher_yellow_pushfresh_with_other_yellow_is_amber():
    # benign pusher ignored, but the real yellow subsystem drives amber.
    v = _compute_app_state(
        _health(pusher_status="yellow", push_fresh=True, extra_yellow="live_bar_cache"),
        SAFE)
    assert v["state"] == "amber", v
    # the amber reason should be the real subsystem, not the benign pusher.
    assert any("live_bar_cache" in r for r in v["reasons"])
