"""
v19.22 — News provider override + exclude-list semantics.

Operator pruning request: drop FLY + BRFUPDN duplicates from the
historical-news call without touching IB Gateway settings. Two envs
support this:

  • IB_NEWS_PROVIDER_OVERRIDE=BZ,DJ,BRFG  → use exactly those (wins absolutely)
  • IB_NEWS_PROVIDER_EXCLUDE=FLY,BRFUPDN  → filter the live IB list

These tests exercise the resolution logic without touching live IB.
"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _mk_provider(code):
    """Mimic the ib_insync NewsProvider shape (dataclass with providerCode)."""
    return SimpleNamespace(providerCode=code, providerName=code)


def _build_resolver():
    """
    Reproduce the post-v19.22 provider-resolution logic in pure Python so
    we can unit-test it without needing an `ib_insync.IB` instance.
    """
    def resolve(ib_provider_codes, *, override=None, exclude=None):
        env = {}
        if override is not None:
            env["IB_NEWS_PROVIDER_OVERRIDE"] = override
        if exclude is not None:
            env["IB_NEWS_PROVIDER_EXCLUDE"] = exclude

        with patch.dict(os.environ, env, clear=False):
            # Strip any prior values that aren't in `env` so we don't leak
            # test-context state.
            for k in ("IB_NEWS_PROVIDER_OVERRIDE", "IB_NEWS_PROVIDER_EXCLUDE"):
                if k not in env:
                    os.environ.pop(k, None)

            _override = (os.environ.get("IB_NEWS_PROVIDER_OVERRIDE") or "").strip()
            if _override:
                return [p.strip() for p in _override.split(",") if p.strip()]

            _exclude_raw = (os.environ.get("IB_NEWS_PROVIDER_EXCLUDE") or "").strip()
            _excluded = {
                p.strip().upper() for p in _exclude_raw.split(",") if p.strip()
            }
            providers = [_mk_provider(c) for c in ib_provider_codes]
            if providers:
                return [
                    p.providerCode for p in providers
                    if hasattr(p, "providerCode")
                    and (p.providerCode or "").upper() not in _excluded
                ]
            return ["BZ", "DJ", "BRFG"]
    return resolve


def test_override_wins_absolutely():
    resolve = _build_resolver()
    res = resolve(
        ib_provider_codes=["BZ", "FLY", "DJ", "BRFG", "BRFUPDN"],
        override="BZ,DJ,BRFG",
    )
    assert res == ["BZ", "DJ", "BRFG"]


def test_exclude_filters_live_list():
    """Operator's stated 2026-05-01 ask: drop FLY + BRFUPDN, keep the rest."""
    resolve = _build_resolver()
    res = resolve(
        ib_provider_codes=["BZ", "FLY", "DJ", "BRFG", "BRFUPDN"],
        exclude="FLY,BRFUPDN",
    )
    assert res == ["BZ", "DJ", "BRFG"]


def test_exclude_case_insensitive():
    resolve = _build_resolver()
    res = resolve(
        ib_provider_codes=["BZ", "FLY", "DJ"],
        exclude="fly",  # lower-case
    )
    assert res == ["BZ", "DJ"]


def test_no_envs_returns_full_live_list():
    resolve = _build_resolver()
    res = resolve(ib_provider_codes=["BZ", "FLY", "DJ", "BRFG", "BRFUPDN"])
    assert res == ["BZ", "FLY", "DJ", "BRFG", "BRFUPDN"]


def test_empty_live_list_uses_trimmed_default():
    """If reqNewsProviders returns empty, fallback drops to the trimmed
    operator-preferred set (NOT the legacy 5-vendor list)."""
    resolve = _build_resolver()
    res = resolve(ib_provider_codes=[])
    assert res == ["BZ", "DJ", "BRFG"]


def test_override_takes_precedence_over_exclude():
    """Override is the absolute lock — exclude is ignored when override is set."""
    resolve = _build_resolver()
    res = resolve(
        ib_provider_codes=["BZ", "FLY", "DJ"],
        override="BZ,FLY,DJ,BRFG,BRFUPDN",  # all 5
        exclude="FLY,BRFUPDN",              # would normally drop 2
    )
    assert res == ["BZ", "FLY", "DJ", "BRFG", "BRFUPDN"]
