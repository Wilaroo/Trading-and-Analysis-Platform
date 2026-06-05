"""
m9 — exit_archetype MFE/MAE data-override tests.

Covers the pure distribution classifier, the horizon-lock guard, the
env-disable switch, the resolve() fail-open, and the describe() trace —
all without a live DB (a fake bot_trades collection is injected).
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _reset_env(monkeypatch):
    for k in [
        "EXIT_ARCHETYPE_DATA_OVERRIDE_ENABLED", "EXIT_ARCHETYPE_MIN_SAMPLES",
        "EXIT_ARCHETYPE_LOOKBACK_DAYS", "EXIT_ARCHETYPE_RUNNER_P50_R",
        "EXIT_ARCHETYPE_RUNNER_P75_R", "EXIT_ARCHETYPE_TARGET_P75_R",
        "EXIT_ARCHETYPE_CACHE_TTL_S",
    ]:
        monkeypatch.delenv(k, raising=False)


# ── pure classifier ────────────────────────────────────────────────────────

def test_classify_runner_when_winners_extend(monkeypatch):
    _reset_env(monkeypatch)
    from services.exit_archetype_service import classify_distribution
    # 40 samples, median ~2.5R, fat tail to 6R → runner.
    vals = [0.5, 1.0, 1.5, 2.0] + [2.5] * 12 + [3.5, 4.0, 4.5, 5.0, 6.0] * 5 + [2.6] * 3
    arch, stats = classify_distribution(vals)
    assert arch == "runner", stats
    assert stats["n"] == len(vals)
    assert stats["p50_mfe_r"] >= 2.0 and stats["p75_mfe_r"] >= 3.5


def test_classify_target_when_mfe_capped(monkeypatch):
    _reset_env(monkeypatch)
    from services.exit_archetype_service import classify_distribution
    # 40 samples all clustered ≤2R → target (no extension).
    vals = [0.3, 0.6, 0.9, 1.0, 1.1, 1.2, 1.4, 1.6] * 5
    arch, stats = classify_distribution(vals)
    assert arch == "target", stats
    assert stats["p75_mfe_r"] <= 2.0


def test_classify_none_when_insufficient(monkeypatch):
    _reset_env(monkeypatch)
    from services.exit_archetype_service import classify_distribution
    arch, stats = classify_distribution([3.0, 4.0, 5.0])  # < 30 samples
    assert arch is None
    assert stats["reason"] == "insufficient_samples"


def test_classify_none_when_ambiguous(monkeypatch):
    _reset_env(monkeypatch)
    from services.exit_archetype_service import classify_distribution
    # median ~2.4 but p75 ~2.8 (< runner 3.5 and > target 2.0) → ambiguous.
    vals = [1.8, 2.0, 2.2, 2.4, 2.6, 2.8] * 6
    arch, stats = classify_distribution(vals)
    assert arch is None and stats["reason"] == "ambiguous"


# ── fake-DB integration (resolve + describe) ───────────────────────────────

class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def __iter__(self):
        return iter(self._docs)


class _FakeColl:
    def __init__(self, docs):
        self._docs = docs

    def find(self, *a, **k):
        return _FakeCursor(self._docs)


class _FakeDB:
    def __init__(self, docs):
        self._docs = docs

    def __getitem__(self, name):
        return _FakeColl(self._docs)


def _runner_docs(setup="tidal_wave", n=40):
    # winners that run: median ~2.5, p75 ~4
    mfes = ([2.5] * (n // 2)) + ([4.0] * (n // 2))
    return [{"setup_type": setup, "mfe_r": m, "status": "closed"} for m in mfes]


def test_resolve_overrides_target_prior_to_runner(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("EXIT_ARCHETYPE_CACHE_TTL_S", "0")  # no cache between calls
    import services.exit_archetype_service as eas
    eas._service_singleton = None
    # fading_bounce's static prior is 'target'; feed it a runner distribution.
    db = _FakeDB(_runner_docs(setup="fading_bounce"))
    out = eas.resolve_exit_archetype("fading_bounce", db=db)
    assert out == "runner"
    desc = eas.get_exit_archetype_service(db=db).describe("fading_bounce", db=db)
    assert desc["prior"] == "target" and desc["final"] == "runner" and desc["overridden"]


def test_horizon_locked_setups_never_overridden(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("EXIT_ARCHETYPE_CACHE_TTL_S", "0")
    import services.exit_archetype_service as eas
    from services.setup_taxonomy import exit_archetype_prior
    eas._service_singleton = None
    # a swing setup is horizon-locked → even a runner distribution can't flip it.
    swing_setup = "daily_breakout"
    assert exit_archetype_prior(swing_setup) in ("swing_hold", "position_hold")
    db = _FakeDB(_runner_docs(setup=swing_setup))
    out = eas.resolve_exit_archetype(swing_setup, db=db)
    assert out == exit_archetype_prior(swing_setup)
    desc = eas.get_exit_archetype_service(db=db).describe(swing_setup, db=db)
    assert desc["horizon_locked"] is True and desc["overridden"] is False


def test_env_disable_returns_prior(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("EXIT_ARCHETYPE_DATA_OVERRIDE_ENABLED", "0")
    import services.exit_archetype_service as eas
    from services.setup_taxonomy import exit_archetype_prior
    eas._service_singleton = None
    db = _FakeDB(_runner_docs(setup="fading_bounce"))
    out = eas.resolve_exit_archetype("fading_bounce", db=db)
    assert out == exit_archetype_prior("fading_bounce") == "target"


def test_learning_only_trades_excluded(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("EXIT_ARCHETYPE_CACHE_TTL_S", "0")
    monkeypatch.setenv("EXIT_ARCHETYPE_MIN_SAMPLES", "30")
    import services.exit_archetype_service as eas
    eas._service_singleton = None
    # 40 runner docs but all flagged learning_only → excluded → insufficient → prior held.
    docs = [{"setup_type": "fading_bounce", "mfe_r": 4.0, "status": "closed",
             "learning_only": True} for _ in range(40)]
    out = eas.resolve_exit_archetype("fading_bounce", db=_FakeDB(docs))
    assert out == "target"  # prior, because all samples excluded
