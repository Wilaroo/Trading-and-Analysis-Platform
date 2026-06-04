"""
test_v19_34_216_strategy_stats_live_hook.py

Validates the v19.34.216 LIVE EV hook in pnl_compute:
  - _base_setup keying matches the TQS Setup-pillar consumer + the backfill.
  - _upsert_strategy_stats_bestEffort folds an R-outcome into a strategy_stats
    doc with the SAME win_rate / EV math as backfill_strategy_stats.py.
"""
import importlib

pnl = importlib.import_module("services.pnl_compute")


class _FakeColl:
    def __init__(self, seed=None):
        self._doc = dict(seed) if seed else None

    def find_one(self, _q):
        return dict(self._doc) if self._doc else None

    def update_one(self, _q, update, upsert=False):
        self._doc = dict(update["$set"])


class _FakeDB:
    def __init__(self, seed=None):
        self._coll = _FakeColl(seed)

    def __getitem__(self, _name):
        return self._coll


class _Trade:
    def __init__(self, setup_type):
        self.setup_type = setup_type


def _install_fake_db(seed=None):
    db = _FakeDB(seed)
    pnl._AO_DB = db
    pnl._get_outcomes_collection = lambda: db["strategy_stats"]
    return db


def test_base_setup_strips_direction_suffix():
    assert pnl._base_setup("vwap_fade_long") == "vwap_fade"
    assert pnl._base_setup("vwap_fade_short") == "vwap_fade"
    assert pnl._base_setup("squeeze") == "squeeze"
    assert pnl._base_setup(None) == ""


def test_first_win_creates_doc():
    db = _install_fake_db()
    pnl._upsert_strategy_stats_bestEffort(_Trade("squeeze"), "won", 2.0, 100.0)
    d = db["strategy_stats"].find_one({})
    assert d["setup_type"] == "squeeze"
    assert d["alerts_triggered"] == 1
    assert d["alerts_won"] == 1
    assert d["alerts_lost"] == 0
    assert d["win_rate"] == 1.0
    assert d["r_outcomes"] == [2.0]
    assert d["expected_value_r"] == 0.0


def test_ev_unlocks_and_matches_backfill_math():
    seed = {
        "setup_type": "vwap_fade",
        "alerts_triggered": 4,
        "alerts_won": 2,
        "alerts_lost": 2,
        "total_pnl": 0.0,
        "r_outcomes": [2.0, 2.0, -1.0, -1.0],
    }
    db = _install_fake_db(seed)
    pnl._upsert_strategy_stats_bestEffort(_Trade("vwap_fade_long"), "won", 2.0, 50.0)
    d = db["strategy_stats"].find_one({})
    assert d["alerts_triggered"] == 5
    assert d["alerts_won"] == 3
    assert d["r_outcomes"] == [2.0, 2.0, -1.0, -1.0, 2.0]
    assert d["win_rate"] == 0.6
    assert d["expected_value_r"] == 0.8


def test_loss_increments_lost_and_pnl():
    seed = {"setup_type": "mean_reversion", "alerts_triggered": 1,
            "alerts_won": 1, "alerts_lost": 0, "total_pnl": 100.0,
            "r_outcomes": [1.5]}
    db = _install_fake_db(seed)
    pnl._upsert_strategy_stats_bestEffort(_Trade("mean_reversion"), "lost", -1.0, -40.0)
    d = db["strategy_stats"].find_one({})
    assert d["alerts_lost"] == 1
    assert d["alerts_triggered"] == 2
    assert d["total_pnl"] == 60.0
    assert d["r_outcomes"] == [1.5, -1.0]


def test_scratch_skipped():
    db = _install_fake_db()
    pnl._upsert_strategy_stats_bestEffort(_Trade("squeeze"), "scratch", 0.0, 0.0)
    assert db["strategy_stats"].find_one({}) is None


def test_blank_setup_noop():
    db = _install_fake_db()
    pnl._upsert_strategy_stats_bestEffort(_Trade(None), "won", 2.0, 100.0)
    assert db["strategy_stats"].find_one({}) is None


def test_r_outcomes_capped_100():
    seed = {"setup_type": "squeeze", "alerts_triggered": 100,
            "alerts_won": 100, "alerts_lost": 0, "total_pnl": 0.0,
            "r_outcomes": [1.0] * 100}
    db = _install_fake_db(seed)
    pnl._upsert_strategy_stats_bestEffort(_Trade("squeeze"), "won", 2.0, 10.0)
    d = db["strategy_stats"].find_one({})
    assert len(d["r_outcomes"]) == 100
    assert d["r_outcomes"][-1] == 2.0
