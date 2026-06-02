"""
test_v19_34_221_l2_slots.py

Validates v19.34.221 L2-router changes:
  - _MAX_L2_SLOTS is env-configurable via MAX_L2_SLOTS (default 3).
  - status() surfaces the IB-309 / pusher-cap watch fields.
"""
import importlib
import os


def test_max_slots_env_default():
    os.environ.pop("MAX_L2_SLOTS", None)
    mod = importlib.reload(importlib.import_module("services.l2_router"))
    assert mod._MAX_L2_SLOTS == 3


def test_max_slots_env_override():
    os.environ["MAX_L2_SLOTS"] = "6"
    try:
        mod = importlib.reload(importlib.import_module("services.l2_router"))
        assert mod._MAX_L2_SLOTS == 6
    finally:
        os.environ.pop("MAX_L2_SLOTS", None)
        importlib.reload(importlib.import_module("services.l2_router"))


def test_status_has_cap_watch_fields():
    mod = importlib.reload(importlib.import_module("services.l2_router"))
    r = mod.L2DynamicRouter()
    st = r.status()
    assert "cap_rejections" in st and st["cap_rejections"] == 0
    assert "last_cap_skipped" in st and st["last_cap_skipped"] == []
    assert "max_l2_slots" in st
