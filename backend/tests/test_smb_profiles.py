"""
Tests for the 3 SMB training profiles added 2026-04-22 (OPENING_DRIVE,
SECOND_CHANCE, BIG_DOG).

Why this test exists
--------------------
Phase 13 v2 coverage check revealed 3/12 scanner setups (opening_drive,
second_chance, big_dog) had no matching training model → 75% coverage.
Unlike `rubber_band_scalp_short` → `SHORT_SCALP` which is a family variant,
these 3 are distinct SMB patterns needing their own models.

After this commit:
  - SETUP_TRAINING_PROFILES["OPENING_DRIVE"] declares 2 bar sizes (5 mins, 1 min)
  - SETUP_TRAINING_PROFILES["SECOND_CHANCE"] declares 1 bar size (5 mins)
  - SETUP_TRAINING_PROFILES["BIG_DOG"] declares 2 bar sizes (5 mins, 1 day)
  - Resolver's family-substring list includes all 3 (so variants like
    `big_dog_breakout_long` route correctly even after suffix strip)

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_smb_profiles.py -v
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.ai_modules.setup_training_config import (  # noqa: E402
    SETUP_TRAINING_PROFILES, get_model_name,
)
from services.ai_modules.timeseries_service import TimeSeriesAIService  # noqa: E402


resolve = TimeSeriesAIService._resolve_setup_model_key


# ── Profile declarations ────────────────────────────────────────────────

def test_opening_drive_profile_declared():
    profiles = SETUP_TRAINING_PROFILES.get("OPENING_DRIVE", [])
    assert len(profiles) >= 1, "OPENING_DRIVE must have at least one profile"
    bars = {p["bar_size"] for p in profiles}
    assert "5 mins" in bars


def test_second_chance_profile_declared():
    profiles = SETUP_TRAINING_PROFILES.get("SECOND_CHANCE", [])
    assert len(profiles) >= 1
    assert profiles[0]["bar_size"] == "5 mins"


def test_big_dog_profile_declared_with_daily():
    profiles = SETUP_TRAINING_PROFILES.get("BIG_DOG", [])
    assert len(profiles) >= 1
    bars = {p["bar_size"] for p in profiles}
    # Big-dog plays hold overnight → daily bar profile included
    assert "1 day" in bars


def test_every_smb_profile_has_required_fields():
    required = {"bar_size", "forecast_horizon", "noise_threshold",
                "min_samples", "num_boost_round", "num_classes", "description"}
    for setup in ("OPENING_DRIVE", "SECOND_CHANCE", "BIG_DOG"):
        for p in SETUP_TRAINING_PROFILES[setup]:
            missing = required - set(p.keys())
            assert not missing, f"{setup}/{p.get('bar_size')} missing {missing}"
            # Triple-barrier 3-class is the standard now
            assert p["num_classes"] == 3


# ── Expected model names ────────────────────────────────────────────────

def test_generated_model_names_match_resolver_expectations():
    # These are the names the loader will look for in `timeseries_models`
    # after next retrain. If a scanner emits `opening_drive`, the resolver
    # needs OPENING_DRIVE in available_keys; the loader produces
    # OPENING_DRIVE from the model name pattern.
    assert get_model_name("OPENING_DRIVE", "5 mins") == "opening_drive_5min_predictor"
    assert get_model_name("SECOND_CHANCE", "5 mins") == "second_chance_5min_predictor"
    assert get_model_name("BIG_DOG", "1 day") == "big_dog_1day_predictor"


# ── Resolver routing ────────────────────────────────────────────────────

def _available_with_smb():
    """What _setup_models.keys() will look like after the next retrain."""
    return {
        "SCALP", "VWAP", "REVERSAL", "BREAKOUT",
        "OPENING_DRIVE", "SECOND_CHANCE", "BIG_DOG",  # ← newly trained
        "SHORT_SCALP", "SHORT_VWAP", "SHORT_REVERSAL",
    }


def test_exact_scanner_name_resolves_to_new_smb_models():
    avail = _available_with_smb()
    assert resolve("opening_drive", avail) == "OPENING_DRIVE"
    assert resolve("second_chance", avail) == "SECOND_CHANCE"
    assert resolve("big_dog", avail) == "BIG_DOG"


def test_smb_variants_route_via_family_substring():
    # Scanner might emit variants like "big_dog_rvol" or "opening_drive_gap"
    # once Tier 2 SMB setups are added. Family substring should catch them.
    avail = _available_with_smb()
    assert resolve("big_dog_rvol", avail) == "BIG_DOG"
    assert resolve("opening_drive_momentum", avail) == "OPENING_DRIVE"
    assert resolve("second_chance_breakout", avail) == "SECOND_CHANCE"


def test_smb_short_variants_fall_back_to_base():
    # No SHORT_BIG_DOG trained → `big_dog_short` should still find the base
    # (better than the general model; direction handled elsewhere in predict)
    avail = _available_with_smb()
    # big_dog_short → strips _SHORT → BIG_DOG base match
    assert resolve("big_dog_short", avail) == "BIG_DOG"


def test_no_smb_models_loaded_falls_back_cleanly():
    # Before the next retrain runs, SMB keys aren't in _setup_models yet.
    # Resolver must fall back gracefully (will_use_general=True path).
    avail = {"SCALP", "VWAP", "REVERSAL"}  # pre-retrain state
    for name in ("opening_drive", "second_chance", "big_dog"):
        resolved = resolve(name, avail)
        # Stays as the uppercased input since no match exists
        assert resolved == name.upper()
