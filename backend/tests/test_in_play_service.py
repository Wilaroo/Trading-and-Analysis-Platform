"""Tests for the unified InPlayService.

Covers:
  - Default config loaded from `DEFAULT_CONFIG` when no DB.
  - `_score` rubric — every band fires correctly:
      • Exceptional / High / Modest / Sub-min RVOL
      • Big / Modest / No-gap branches
      • Big / Decent / Tight ATR branches
      • Spread disqualifier when spread_pct exceeds threshold
      • Catalyst / short-interest / low-float bonuses
  - `is_in_play` true only when score ≥ min AND disqualifiers < max
  - `score_from_snapshot` reads `rvol`, `gap_pct`, `atr_percent` off
    a TechnicalSnapshot-like object
  - `score_from_market_data` accepts a dict (legacy AI-assistant shape)
  - `update_config` persists to bot_state, drops unknown keys, coerces
    types from string for the API surface
  - `is_strict_gate` reflects current config
  - LiveAlert exposes `in_play_score`, `in_play_reasons`,
    `in_play_disqualifiers` with the right defaults
  - Source-level guards: scanner calls `score_from_snapshot`, stamps
    fields on alert, gates only in strict mode
  - Alert system's `check_in_play` shim delegates to the unified
    service and returns the legacy dataclass shape unchanged
"""

from __future__ import annotations

import asyncio
import sys
from typing import Dict, List

sys.path.insert(0, "/app/backend")

import pytest  # noqa: E402

from services.in_play_service import (  # noqa: E402
    InPlayService,
    InPlayQualification,
    get_in_play_service,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ──────────────────────────── In-memory fake Mongo ────────────────────────────


class _FakeColl:
    def __init__(self):
        self.docs: List[Dict] = []

    def create_index(self, *a, **kw):
        return None

    def update_one(self, filter_, update, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                d.update(update.get("$set", {}))
                return type("UR", (), {"matched_count": 1})()
        if upsert:
            new = {}
            new.update(filter_)
            new.update(update.get("$set", {}))
            self.docs.append(new)
            return type("UR", (), {"upserted_id": "fake"})()
        return type("UR", (), {"matched_count": 0})()

    def find_one(self, filter_):
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                return dict(d)
        return None


class _FakeDB:
    def __init__(self):
        self._cols: Dict[str, _FakeColl] = {}

    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = _FakeColl()
        return self._cols[name]


# ──────────────────────────── Snapshot fake ────────────────────────────


class _Snap:
    """Minimal TechnicalSnapshot stand-in for `score_from_snapshot`."""

    def __init__(self, rvol=1.0, gap_pct=0.0, atr_percent=1.0):
        self.rvol = rvol
        self.gap_pct = gap_pct
        self.atr_percent = atr_percent


# ──────────────────────────── Default config ────────────────────────────


def test_default_config_loaded_when_no_db():
    svc = InPlayService()
    cfg = svc.get_config()
    assert cfg["min_rvol"] == 2.0
    assert cfg["min_gap_pct"] == 3.0
    assert cfg["min_atr_pct"] == 1.5
    assert cfg["max_spread_pct"] == 0.3
    assert cfg["min_qualifying_score"] == 30
    assert cfg["max_disqualifiers"] == 2
    assert cfg["strict_gate"] is False


def test_loads_persisted_config_from_bot_state():
    db = _FakeDB()
    db["bot_state"].docs.append({
        "_id": "in_play_config",
        "min_rvol": 1.5,
        "strict_gate": True,
    })
    svc = InPlayService(db=db)
    cfg = svc.get_config()
    assert cfg["min_rvol"] == 1.5
    assert cfg["strict_gate"] is True
    # Unspecified keys keep defaults
    assert cfg["min_gap_pct"] == 3.0


# ──────────────────────────── Scoring rubric ────────────────────────────


def test_exceptional_rvol_earns_big_score():
    svc = InPlayService()
    q = svc.score_from_market_data({"rvol": 6.0, "gap_pct": 0, "atr_pct": 2.0})
    assert q.score >= 35  # exceptional RVOL alone earns +35
    assert any("Exceptional volume" in r for r in q.reasons)


def test_low_rvol_disqualifier():
    svc = InPlayService()
    q = svc.score_from_market_data({"rvol": 1.0, "gap_pct": 0, "atr_pct": 2.0})
    assert any("Low relative volume" in d for d in q.disqualifiers)


def test_big_gap_earns_25():
    svc = InPlayService()
    q = svc.score_from_market_data({"rvol": 2.5, "gap_pct": 9.0, "atr_pct": 2.0})
    assert any("Large gap" in r for r in q.reasons)
    # Score should include +15 (modest RVOL) + +25 (big gap)
    assert q.score >= 40


def test_modest_gap_earns_15():
    svc = InPlayService()
    q = svc.score_from_market_data({"rvol": 2.5, "gap_pct": -4.0, "atr_pct": 2.0})
    assert any("Gapping down" in r for r in q.reasons)
    assert any("-4.0%" in r for r in q.reasons)


def test_tight_atr_disqualifier():
    svc = InPlayService()
    q = svc.score_from_market_data({"rvol": 2.5, "gap_pct": 4.0, "atr_pct": 0.5})
    assert any("Tight range" in d for d in q.disqualifiers)


def test_wide_spread_disqualifier_penalises_score():
    svc = InPlayService()
    q_no = svc.score_from_market_data({"rvol": 2.5, "gap_pct": 4.0, "atr_pct": 2.0,
                                        "spread_pct": 0.05})
    q_wide = svc.score_from_market_data({"rvol": 2.5, "gap_pct": 4.0, "atr_pct": 2.0,
                                          "spread_pct": 0.5})
    assert q_wide.score < q_no.score
    assert any("Wide spread" in d for d in q_wide.disqualifiers)


def test_catalyst_and_short_and_float_bonuses():
    svc = InPlayService()
    base = svc.score_from_market_data({"rvol": 2.5, "gap_pct": 4.0, "atr_pct": 2.0})
    rich = svc.score_from_market_data({
        "rvol": 2.5, "gap_pct": 4.0, "atr_pct": 2.0,
        "has_catalyst": True, "short_interest": 25.0,
        "float_shares": 10_000_000,
    })
    assert rich.score == base.score + 15 + 10 + 5  # catalyst + short + low-float
    assert any("Has news/catalyst" in r for r in rich.reasons)
    assert any("squeeze potential" in r for r in rich.reasons)
    assert any("Low float" in r for r in rich.reasons)


def test_is_in_play_true_when_score_high_and_few_disqualifiers():
    svc = InPlayService()
    q = svc.score_from_market_data({"rvol": 4.0, "gap_pct": 5.0, "atr_pct": 2.0})
    assert q.is_in_play
    assert q.score >= 30


def test_is_in_play_false_with_many_disqualifiers():
    svc = InPlayService()
    q = svc.score_from_market_data({
        "rvol": 1.0,        # disqualifier #1
        "gap_pct": 1.0,
        "atr_pct": 0.5,     # disqualifier #2
        "spread_pct": 0.6,  # disqualifier #3
    })
    assert not q.is_in_play
    assert len(q.disqualifiers) >= 2


def test_is_in_play_false_when_score_below_threshold():
    svc = InPlayService()
    q = svc.score_from_market_data({"rvol": 2.5, "gap_pct": 1.0, "atr_pct": 1.5,
                                     "spread_pct": 0.05})
    # Score = 15 (modest RVOL) + 8 (decent ATR) = 23, below 30
    assert q.score == 23
    assert not q.is_in_play


def test_score_clamped_to_0_100():
    svc = InPlayService()
    q = svc.score_from_market_data({
        "rvol": 10.0, "gap_pct": 15.0, "atr_pct": 5.0,
        "has_catalyst": True, "short_interest": 50.0,
        "float_shares": 5_000_000,
    })
    assert q.score <= 100


# ──────────────────────────── score_from_snapshot ────────────────────────────


def test_score_from_snapshot_reads_correct_fields():
    svc = InPlayService()
    snap = _Snap(rvol=3.0, gap_pct=4.0, atr_percent=2.0)
    q = svc.score_from_snapshot(snap, spread_pct=0.05)
    assert q.rvol == 3.0
    assert q.gap_pct == 4.0
    assert q.atr_pct == 2.0
    assert q.is_in_play


def test_score_from_snapshot_default_spread_zero():
    svc = InPlayService()
    snap = _Snap(rvol=3.0, gap_pct=4.0, atr_percent=2.0)
    q = svc.score_from_snapshot(snap)
    assert q.spread_pct == 0.0
    assert not any("Wide spread" in d for d in q.disqualifiers)


# ──────────────────────────── update_config ────────────────────────────


def test_update_config_persists_to_bot_state():
    db = _FakeDB()
    svc = InPlayService(db=db)
    new_cfg = svc.update_config({"strict_gate": True, "min_rvol": 1.0})
    assert new_cfg["strict_gate"] is True
    assert new_cfg["min_rvol"] == 1.0
    # Persisted to the collection
    doc = db["bot_state"].find_one({"_id": "in_play_config"})
    assert doc is not None
    assert doc["strict_gate"] is True


def test_update_config_drops_unknown_keys():
    db = _FakeDB()
    svc = InPlayService(db=db)
    new_cfg = svc.update_config({"strict_gate": True, "fake_key": "fake_value"})
    assert "fake_key" not in new_cfg


def test_update_config_coerces_string_bool():
    """API can pass string 'true' for strict_gate; service should coerce."""
    db = _FakeDB()
    svc = InPlayService(db=db)
    svc.update_config({"strict_gate": "true"})
    assert svc.is_strict_gate() is True
    svc.update_config({"strict_gate": "false"})
    assert svc.is_strict_gate() is False


def test_update_config_coerces_string_numeric():
    db = _FakeDB()
    svc = InPlayService(db=db)
    new_cfg = svc.update_config({"min_rvol": "1.5"})
    assert new_cfg["min_rvol"] == 1.5


def test_is_strict_gate_default_false():
    svc = InPlayService()
    assert svc.is_strict_gate() is False


# ──────────────────────────── Singleton ────────────────────────────


def test_singleton():
    a = get_in_play_service()
    b = get_in_play_service()
    assert a is b


# ──────────────────────────── LiveAlert ────────────────────────────


def test_live_alert_has_in_play_fields():
    from services.enhanced_scanner import LiveAlert
    fields = LiveAlert.__dataclass_fields__
    assert "in_play_score" in fields
    assert fields["in_play_score"].default == 0
    assert "in_play_reasons" in fields
    assert "in_play_disqualifiers" in fields


# ──────────────────────────── Source-level guards ────────────────────────────


def test_scanner_uses_unified_in_play_service():
    from pathlib import Path
    src = Path("/app/backend/services/enhanced_scanner.py").read_text("utf-8")
    assert "get_in_play_service" in src
    assert "score_from_snapshot" in src
    assert "_symbols_skipped_in_play" in src
    assert "is_strict_gate" in src
    assert "alert.in_play_score" in src
    assert "alert.in_play_reasons" in src


def test_alert_system_check_in_play_is_a_shim():
    """The legacy `AlertSystem.check_in_play` should now delegate to
    `InPlayService.score_from_market_data` instead of duplicating the
    rubric inline."""
    from pathlib import Path
    src = Path("/app/backend/services/alert_system.py").read_text("utf-8")
    # The shim imports + calls the unified service
    assert "from services.in_play_service import" in src
    assert "score_from_market_data" in src
    # The old inline rubric is gone (it had this distinctive line)
    assert "Above average volume (RVOL: " not in src


def test_legacy_shim_returns_local_inplayqualification_dataclass():
    """The shim must preserve the legacy dataclass shape so existing
    callers (alerts router, AI market intelligence) work unchanged."""
    from services.alert_system import AdvancedAlertSystem
    from services.alert_system import InPlayQualification as LegacyQual
    sys_a = AdvancedAlertSystem.__new__(AdvancedAlertSystem)  # bypass __init__'s DB call
    market_data = {"rvol": 4.0, "gap_pct": 5.0, "atr_pct": 2.0}
    result = _run(sys_a.check_in_play("AAPL", market_data))
    assert isinstance(result, LegacyQual)
    assert result.is_in_play is True
    assert result.score >= 30


# ──────────────────────────── Config endpoint structure ────────────────────────────


def test_config_endpoint_referenced_in_router():
    from pathlib import Path
    src = Path("/app/backend/routers/scanner.py").read_text("utf-8")
    assert "/in-play-config" in src
    assert "get_in_play_config" in src
    assert "update_in_play_config" in src
