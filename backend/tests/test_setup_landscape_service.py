"""Tests for SetupLandscapeService — the universe-wide Setup snapshot
that powers the 1st-person Setup-aware narrative line in morning,
midday, EOD and weekend briefings."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")

import pytest

from services.setup_landscape_service import (  # noqa: E402
    SetupLandscapeService, SetupGroup, get_setup_landscape_service,
    _SETUP_TRADE_FAMILY,
)
from services.market_setup_classifier import (  # noqa: E402
    MarketSetup, ClassificationResult, get_market_setup_classifier,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _stub_classifier_with(symbol_to_setup: dict) -> None:
    """Force-cache classifier results so the service can run without a DB."""
    cls = get_market_setup_classifier()
    cls.invalidate()
    now = datetime.now(timezone.utc)
    for sym, setup in symbol_to_setup.items():
        cls._cache[sym] = (
            ClassificationResult(setup=setup, confidence=0.85),
            now,
        )


def _service_with_symbols(symbols: list) -> SetupLandscapeService:
    """Build a SetupLandscapeService that returns a fixed symbol list."""
    svc = SetupLandscapeService(db=None)

    async def _stub_pull(_n: int):
        return symbols
    svc._pull_top_symbols = _stub_pull   # type: ignore
    return svc


# ──────────────────────────── VOICE / NARRATIVE ────────────────────────────


def test_morning_narrative_uses_first_person_voice():
    """Operator's voice rule: morning briefing must be in 1st-person."""
    _stub_classifier_with({
        "AAPL":  MarketSetup.GAP_AND_GO,
        "ORCL":  MarketSetup.GAP_AND_GO,
        "MSFT":  MarketSetup.GAP_AND_GO,
        "NVDA":  MarketSetup.OVEREXTENSION,
        "COIN":  MarketSetup.OVEREXTENSION,
    })
    svc = _service_with_symbols(["AAPL", "ORCL", "MSFT", "NVDA", "COIN"])
    snap = _run(svc.get_snapshot(context="morning"))
    text = snap.narrative
    # 1st-person markers
    assert "I screened" in text
    assert "I'm favoring" in text
    assert "I'll be looking to avoid" in text
    # No third-person bot references
    forbidden = ("the bot", "SentCom is", "the system found", "the scanner found")
    for f in forbidden:
        assert f not in text, f"Forbidden 3rd-person phrase in morning narrative: {f!r}"


def test_eod_narrative_uses_retrospective_voice():
    _stub_classifier_with({
        "TSLA": MarketSetup.RANGE_BREAK,
        "AMD":  MarketSetup.RANGE_BREAK,
        "META": MarketSetup.RANGE_BREAK,
    })
    svc = _service_with_symbols(["TSLA", "AMD", "META"])
    snap = _run(svc.get_snapshot(context="eod"))
    assert "today shaped up as" in snap.narrative
    assert "The day favored" in snap.narrative


def test_weekend_narrative_uses_forward_looking_voice():
    _stub_classifier_with({"AAPL": MarketSetup.DAY_2, "MSFT": MarketSetup.DAY_2})
    svc = _service_with_symbols(["AAPL", "MSFT"])
    snap = _run(svc.get_snapshot(context="weekend"))
    assert "over the weekend" in snap.narrative.lower() or "weekend prep" in snap.narrative.lower()
    assert "heading into next week" in snap.narrative.lower()


def test_midday_narrative_uses_present_tense():
    _stub_classifier_with({"AMD": MarketSetup.RANGE_BREAK})
    svc = _service_with_symbols(["AMD"])
    snap = _run(svc.get_snapshot(context="midday"))
    assert "Mid-session" in snap.narrative
    assert "I'm staying patient" in snap.narrative


# ──────────────────────────── GROUPING ────────────────────────────


def test_landscape_groups_sorted_by_count_desc():
    _stub_classifier_with({
        "AAPL":  MarketSetup.GAP_AND_GO,    # 4 in gap_and_go
        "MSFT":  MarketSetup.GAP_AND_GO,
        "ORCL":  MarketSetup.GAP_AND_GO,
        "GOOGL": MarketSetup.GAP_AND_GO,
        "NVDA":  MarketSetup.OVEREXTENSION, # 2 in overextension
        "COIN":  MarketSetup.OVEREXTENSION,
        "AMD":   MarketSetup.DAY_2,         # 1 in day_2
    })
    svc = _service_with_symbols(["AAPL", "MSFT", "ORCL", "GOOGL", "NVDA", "COIN", "AMD"])
    snap = _run(svc.get_snapshot(context="morning"))
    # Setups ordered by count desc
    counts = [g.count for g in snap.groups if g.setup != "neutral"]
    assert counts == sorted(counts, reverse=True), f"Groups not sorted desc: {counts}"
    # Top group is gap_and_go with 4
    assert snap.groups[0].setup == "gap_and_go"
    assert snap.groups[0].count == 4


def test_landscape_caches_for_60_seconds():
    _stub_classifier_with({"AAPL": MarketSetup.GAP_AND_GO})
    svc = _service_with_symbols(["AAPL"])
    snap1 = _run(svc.get_snapshot(context="morning"))
    snap2 = _run(svc.get_snapshot(context="morning"))
    assert snap1 is snap2  # same object → cache hit


def test_landscape_invalidate_drops_cache():
    _stub_classifier_with({"AAPL": MarketSetup.GAP_AND_GO})
    svc = _service_with_symbols(["AAPL"])
    _run(svc.get_snapshot(context="morning"))
    svc.invalidate()
    assert svc._snapshot is None


def test_landscape_examples_capped_at_5():
    """Even with 20 names in one Setup, examples list maxes at 5."""
    setups = {f"SYM{i}": MarketSetup.GAP_AND_GO for i in range(20)}
    _stub_classifier_with(setups)
    svc = _service_with_symbols(list(setups.keys()))
    snap = _run(svc.get_snapshot(context="morning"))
    top = snap.groups[0]
    assert top.count == 20
    assert len(top.examples) == 5


def test_landscape_fallback_when_all_neutral():
    """If nothing classified, fallback narrative still speaks 1st-person."""
    _stub_classifier_with({f"SYM{i}": MarketSetup.NEUTRAL for i in range(5)})
    svc = _service_with_symbols([f"SYM{i}" for i in range(5)])
    snap = _run(svc.get_snapshot(context="morning"))
    assert "no clear Bellafiore Setup" in snap.narrative or "couldn't pin" in snap.narrative
    # Still 1st-person
    assert "I screened" in snap.narrative or "I'll let" in snap.narrative


def test_landscape_singleton():
    a = get_setup_landscape_service()
    b = get_setup_landscape_service()
    assert a is b


# ──────────────────────────── TRADE-FAMILY MAPPING ────────────────────────────


def test_setup_trade_family_covers_all_seven_setups():
    """Every non-NEUTRAL Setup must have a (family, favoring, avoiding) entry."""
    expected = {s.value for s in MarketSetup if s != MarketSetup.NEUTRAL}
    assert set(_SETUP_TRADE_FAMILY.keys()) == expected


def test_setup_trade_family_action_clauses_are_first_person_friendly():
    """Each entry's `favoring` phrase should chain into 'I'm favoring …'
    naturally — i.e. start with a noun phrase, not a verb."""
    bad_starters = ("favor ", "avoid ", "trade ", "take ", "do ")
    for setup, (family, favoring, avoiding) in _SETUP_TRADE_FAMILY.items():
        for label, phrase in (("favoring", favoring), ("avoiding", avoiding)):
            first_word = phrase.split()[0].lower()
            assert not first_word.startswith(bad_starters), (
                f"{setup} {label!r} starts with imperative verb: {phrase!r}"
            )


# ──────────────────────────── HEADLINE ────────────────────────────


def test_headline_includes_top_setup_and_examples():
    _stub_classifier_with({
        "AAPL": MarketSetup.GAP_AND_GO,
        "ORCL": MarketSetup.GAP_AND_GO,
        "MSFT": MarketSetup.GAP_AND_GO,
    })
    svc = _service_with_symbols(["AAPL", "ORCL", "MSFT"])
    snap = _run(svc.get_snapshot(context="morning"))
    assert "Gap & Go" in snap.headline
    # At least one example ticker should appear
    assert any(t in snap.headline for t in ("AAPL", "ORCL", "MSFT"))
    assert "I'm seeing" in snap.headline  # 1st-person
