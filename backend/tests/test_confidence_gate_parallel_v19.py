"""
v19 — Confidence gate parallelism tests (2026-04-30)

Pre-v19 the gate awaited 8 independent model calls sequentially (~1.1-
1.5s per alert). Post-v19 they fan-out via asyncio.gather → ~250-
300ms (slowest call wins).

Properties tested:
  ★ All 8 model calls execute concurrently (verified by timing).
  ★ A single slow/timing-out model does NOT drag total time.
  ★ A crashing model does NOT crash the gather (return_exceptions
    + per-coro try/except in _safe).
  ★ All 8 results land in the prefetch dict with the correct keys
    so downstream scoring blocks read identical values to pre-v19.
  ★ Per-call timeout (3s default) protects the gather from a stuck
    model.
  ★ Source-level guard: no inline `await self._query_model_consensus
    / _get_live_prediction / etc.` remain in evaluate() — they must
    all be replaced with `signals_pre[...]` reads.

Source-level regression guard is the most important — without it,
a contributor "cleaning up" the parallelism could inadvertently
re-introduce sequential awaits and silently undo the speedup.
"""
from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.ai_modules import confidence_gate as cg_mod
from services.ai_modules.confidence_gate import ConfidenceGate


ROOT = Path(__file__).resolve().parents[1]
GATE_SRC = (ROOT / "services" / "ai_modules" / "confidence_gate.py").read_text()


# --------------------------------------------------------------------------
# Fixture — a minimally-constructed ConfidenceGate instance with the
# 8 model methods mocked. Constructor is bypassed via __new__ so we
# don't need calibration / threshold loaders.
# --------------------------------------------------------------------------

def _make_gate(*, latencies_ms: dict = None, raise_on: set = None,
               timeout_on: set = None) -> ConfidenceGate:
    """Build a gate whose 8 model methods sleep for `latencies_ms[name]`
    seconds, raise on `raise_on`, or hang past timeout for `timeout_on`."""
    latencies_ms = latencies_ms or {}
    raise_on = raise_on or set()
    timeout_on = timeout_on or set()

    gate = ConfidenceGate.__new__(ConfidenceGate)
    gate._db = None
    gate._decision_log = deque(maxlen=50)
    gate._stats = {
        "total_evaluated": 0, "go_count": 0, "reduce_count": 0,
        "skip_count": 0, "today_evaluated": 0, "today_go": 0,
        "today_skip": 0, "today_date": "2025-01-01",
    }
    gate._trading_mode = "normal"
    gate._mode_reason = None
    gate.PARALLEL_PREFETCH_TIMEOUT_S = 1.0  # tighter for tests

    def _make_method(name, default_payload):
        async def fake(*args, **kwargs):
            if name in raise_on:
                raise RuntimeError(f"{name} crashed")
            if name in timeout_on:
                await asyncio.sleep(5.0)  # well over the 1s test timeout
                return default_payload
            sleep_s = latencies_ms.get(name, 50) / 1000.0
            await asyncio.sleep(sleep_s)
            return {**default_payload, "_called_at": time.monotonic()}
        return fake

    gate._query_model_consensus = _make_method("model_consensus", {"has_models": True, "agreement_pct": 0.8})
    gate._get_live_prediction = _make_method("live_prediction", {"has_prediction": True, "confidence": 0.7})
    gate._get_learning_feedback = _make_method("learning_feedback", {"has_data": True, "win_rate": 0.6})
    gate._get_cnn_signal = _make_method("cnn_signal", {"has_prediction": True, "win_probability": 0.65})
    gate._get_tft_signal = _make_method("tft_signal", {"has_prediction": True, "confidence": 0.7})
    gate._get_vae_regime_signal = _make_method("vae_signal", {"has_prediction": True, "confidence": 0.7})
    gate._get_cnn_lstm_signal = _make_method("cnn_lstm_signal", {"has_prediction": True, "confidence": 0.7})
    gate._get_ensemble_meta_signal = _make_method("ensemble_meta", {"has_prediction": True, "confidence": 0.7})

    return gate


# --------------------------------------------------------------------------
# Parallelism — total time must be ~max(latencies), not sum
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parallel_prefetch_total_time_is_max_not_sum():
    """If the 8 model calls each take 100ms sequentially, total time
    should be ~100ms (concurrent) not ~800ms (sequential)."""
    gate = _make_gate(latencies_ms={
        "model_consensus": 100, "live_prediction": 100, "learning_feedback": 100,
        "cnn_signal": 100, "tft_signal": 100, "vae_signal": 100,
        "cnn_lstm_signal": 100, "ensemble_meta": 100,
    })
    start = time.monotonic()
    signals = await gate._prefetch_signals_parallel(
        symbol="NVDA", setup_type="9_ema_scalp",
        direction="long", regime_state="TRADE",
    )
    elapsed = time.monotonic() - start

    # Concurrent: ~100ms; sequential would be ~800ms. Allow generous
    # 250ms ceiling to absorb event-loop scheduling overhead.
    assert elapsed < 0.25, (
        f"Prefetch took {elapsed*1000:.0f}ms — must be ~100ms (concurrent), "
        f"not ~800ms (sequential). The asyncio.gather may have regressed "
        f"to sequential awaits."
    )
    # All 8 results present
    assert set(signals.keys()) == {
        "model_signals", "live_prediction", "learning_adjustment",
        "cnn_signal", "tft_signal", "vae_signal",
        "cnn_lstm_signal", "ensemble_meta",
    }


@pytest.mark.asyncio
async def test_slow_model_does_not_drag_others():
    """One slow (but under-timeout) model shouldn't hold up the others.
    Total time should be max(latencies), driven by the slow one only."""
    gate = _make_gate(latencies_ms={
        "model_consensus": 50,
        "live_prediction": 50,
        "learning_feedback": 50,
        "cnn_signal": 50,
        "tft_signal": 500,  # the slow one — but under 1s timeout
        "vae_signal": 50,
        "cnn_lstm_signal": 50,
        "ensemble_meta": 50,
    })
    start = time.monotonic()
    await gate._prefetch_signals_parallel(
        symbol="NVDA", setup_type="9_ema_scalp",
        direction="long", regime_state="TRADE",
    )
    elapsed = time.monotonic() - start
    # Sequential would be ~850ms; parallel is bound by the slow one (~500ms).
    assert 0.45 < elapsed < 0.7, (
        f"Slow model elapsed {elapsed*1000:.0f}ms — should be ~500ms "
        f"(slowest call wins), not ~850ms (sequential)."
    )


# --------------------------------------------------------------------------
# Exception isolation
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_one_model_crashing_does_not_crash_gather():
    """A model raising an exception must NOT propagate up — it should
    be caught and replaced with a "no signal" default. Other models'
    results must still come through."""
    gate = _make_gate(raise_on={"cnn_signal", "tft_signal"})

    signals = await gate._prefetch_signals_parallel(
        symbol="NVDA", setup_type="9_ema_scalp",
        direction="long", regime_state="TRADE",
    )

    # Crashed models get the safe default (has_prediction=False)
    assert signals["cnn_signal"] == {"has_prediction": False}
    assert signals["tft_signal"] == {"has_prediction": False}
    # Others still came through with their real payloads
    assert signals["model_signals"]["has_models"] is True
    assert signals["live_prediction"]["has_prediction"] is True


@pytest.mark.asyncio
async def test_timeout_replaces_with_default_not_crash():
    """A model that takes longer than the per-coro timeout must
    timeout cleanly, not crash the gather."""
    gate = _make_gate(timeout_on={"vae_signal"})

    start = time.monotonic()
    signals = await gate._prefetch_signals_parallel(
        symbol="NVDA", setup_type="9_ema_scalp",
        direction="long", regime_state="TRADE",
    )
    elapsed = time.monotonic() - start

    # Total time ≤ slightly above the 1s test timeout
    assert elapsed < 1.4, (
        f"Timeout took {elapsed*1000:.0f}ms — should be <1.4s "
        "(timeout=1.0s + scheduling overhead)."
    )
    # Timed-out model gets default
    assert signals["vae_signal"] == {"has_prediction": False}
    # Others came through fine
    assert signals["model_signals"]["has_models"] is True


# --------------------------------------------------------------------------
# Source-level regression guard
# --------------------------------------------------------------------------

INLINE_AWAIT_PATTERNS = [
    r"=\s*await\s+self\._query_model_consensus\(",
    r"=\s*await\s+self\._get_live_prediction\(",
    r"=\s*await\s+self\._get_learning_feedback\(",
    r"=\s*await\s+self\._get_cnn_signal\(",
    r"=\s*await\s+self\._get_tft_signal\(",
    r"=\s*await\s+self\._get_vae_regime_signal\(",
    r"=\s*await\s+self\._get_cnn_lstm_signal\(",
    r"=\s*await\s+self\._get_ensemble_meta_signal\(",
]


@pytest.mark.parametrize("pattern", INLINE_AWAIT_PATTERNS)
def test_no_inline_model_awaits_remain_in_evaluate(pattern):
    """Source-level guard: every model-method call inside the
    confidence_gate module must be either:
      (a) inside `_prefetch_signals_parallel` (where they're packed
          into asyncio.gather), or
      (b) inside the model method's own `async def` definition.

    Inline `foo = await self._get_foo(...)` outside those two
    contexts is the v19 regression we're guarding against — a
    contributor "cleaning up" could re-introduce sequential awaits
    and silently undo the 3-5× speedup.

    We approximate "outside of those contexts" by counting matches:
    each model method appears EXACTLY once as a lambda inside
    `_prefetch_signals_parallel`. So total matches MUST be 1.
    """
    matches = re.findall(pattern, GATE_SRC)
    # Each pattern should match 0 inline awaits (the lambda inside
    # the prefetch helper uses `lambda: self._get_X(...)` without
    # `await`, so it doesn't match these patterns).
    assert len(matches) == 0, (
        f"Found {len(matches)} inline await(s) for `{pattern}` in "
        f"confidence_gate.py. v19 requires all model awaits to be "
        f"in `_prefetch_signals_parallel` via asyncio.gather. "
        "Reverting to inline awaits silently undoes the parallelism."
    )


def test_prefetch_helper_uses_asyncio_gather():
    """The fan-out must use `asyncio.gather` — `await` in a loop is
    sequential and silently regresses the speedup."""
    helper_match = re.search(
        r"async def _prefetch_signals_parallel.*?(?=\n    async def |\n    def |\nclass )",
        GATE_SRC, re.DOTALL,
    )
    assert helper_match, "_prefetch_signals_parallel must exist in confidence_gate.py"
    helper_body = helper_match.group(0)
    assert "asyncio.gather" in helper_body, (
        "_prefetch_signals_parallel must use asyncio.gather() for fan-out. "
        "Using `await` in a loop instead would silently regress the v19 "
        "3-5× speedup."
    )
    # Verify all 8 model methods are routed through the gather
    for method in ("_query_model_consensus", "_get_live_prediction",
                   "_get_learning_feedback", "_get_cnn_signal",
                   "_get_tft_signal", "_get_vae_regime_signal",
                   "_get_cnn_lstm_signal", "_get_ensemble_meta_signal"):
        assert method in helper_body, (
            f"_prefetch_signals_parallel must invoke {method} — "
            "missing means that model's call was orphaned outside the gather."
        )


def test_phase1_regime_calls_also_parallelized():
    """Bonus: the regime_engine + _get_ai_regime calls in Phase 1
    were also converted to asyncio.gather (saves another ~50-100ms)."""
    # Match the v19 Phase 1 fan-out block in evaluate()
    phase1_match = re.search(
        r"# 2026-04-30 v19 — Phase 1 fan-out.*?await asyncio\.gather\(\s*"
        r"_safe_regime\(\),\s*_safe_ai_regime\(\),\s*\)",
        GATE_SRC, re.DOTALL,
    )
    assert phase1_match, (
        "Phase 1 (regime_engine + _get_ai_regime) must be parallelised "
        "via asyncio.gather. v19 saves ~50-100ms here."
    )
