"""2026-06-26 — DISABLED_SETUPS proven-bleeder blocklist promoted into the code
DEFAULT (was an env-only override of just daily_breakout,vwap_fade_short which
silently left vwap_bounce/off_sides_short enabled). Guards the canonical list and
the /api/diagnostic/disabled-setups-audit "silent re-enable" diff logic."""

from services.entry_gate import parse_disabled_setups, DEFAULT_DISABLED_SETUPS

EXPECTED_DEFAULT = {"daily_breakout", "vwap_fade_short", "vwap_bounce", "off_sides_short"}


def test_code_default_is_the_canonical_bleeder_list():
    assert parse_disabled_setups(None) == EXPECTED_DEFAULT
    # constant string parses to the same set regardless of spacing/case
    assert parse_disabled_setups(DEFAULT_DISABLED_SETUPS) == EXPECTED_DEFAULT


def test_empty_env_string_explicitly_clears_blocklist():
    # operator can still fully clear it on purpose
    assert parse_disabled_setups("") == set()


def test_env_keeping_old_value_flags_reenabled_bleeders():
    # The audit's env_dropped_from_default = code_default - effective.
    code_default = parse_disabled_setups(None)
    effective_old_env = parse_disabled_setups("daily_breakout,vwap_fade_short")
    assert sorted(code_default - effective_old_env) == ["off_sides_short", "vwap_bounce"]


def test_dropping_env_uses_clean_code_default():
    code_default = parse_disabled_setups(None)
    effective_no_env = parse_disabled_setups(None)  # env unset -> default
    assert (code_default - effective_no_env) == set()


def test_backside_intentionally_stays_enabled():
    # operator chose to keep backside (mild -0.19R) for a possible exit-side fix
    assert "backside" not in parse_disabled_setups(None)
    # vwap_fade_LONG (+0.22R) must never be blocked by the short-variant entry
    assert "vwap_fade_long" not in parse_disabled_setups(None)
