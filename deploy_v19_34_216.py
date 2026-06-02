#!/usr/bin/env python3
"""
deploy_v19_34_216.py  —  LIVE EV HOOK (strategy_stats stays fresh on every close)

WHAT
  Adds a live upsert into `strategy_stats` inside
  `backend/services/pnl_compute.py::_record_alert_outcome_bestEffort` so the
  TQS Setup-pillar EV / real-win-rate feed is kept current on EVERY trade
  close — mirroring the one-time `backfill_strategy_stats.py` math + keying.
  Pre-v216, only enhanced_scanner.record_alert_outcome wrote strategy_stats
  and it required alert_id ∈ scanner._live_alerts, which the modern
  reconciler/operator/manage-loop close paths bypass → strategy_stats orphaned
  (EV=0 for ~100% of alerts).

SAFETY
  - Idempotent: re-running is a no-op (guards on the v19.34.216 marker).
  - Transactional: writes a .bak, py_compile-checks, rolls back on failure.
  - Commits + pushes BEFORE you restart (DGX restart runs `git checkout -- .`).

RUN ON THE DGX:
  curl -s https://paste.rs/XXXXX -o /tmp/deploy_v19_34_216.py
  python3 /tmp/deploy_v19_34_216.py
  # then:  ./start_backend.sh --force
"""
import os
import re
import shutil
import subprocess
import sys
import py_compile

REPO = os.path.expanduser("~/Trading-and-Analysis-Platform")
if not os.path.isdir(REPO):
    REPO = os.getcwd()
TARGET = os.path.join(REPO, "backend", "services", "pnl_compute.py")
TESTFILE = os.path.join(REPO, "backend", "tests",
                        "test_v19_34_216_strategy_stats_live_hook.py")

MARKER = "v19.34.216"

# ── insertion 1: the live-hook CALL, after the alert_outcomes upsert ───────
ANCHOR_CALL = (
    '    try:\n'
    '        # Upsert keyed on trade_id so retry-on-failure paths don\'t\n'
    '        # create duplicate outcome rows.\n'
    '        coll.update_one(\n'
    '            {"trade_id": doc["trade_id"]},\n'
    '            {"$set": doc},\n'
    '            upsert=True,\n'
    '        )\n'
    '    except Exception as e:\n'
    '        logger.debug("[pnl_compute] alert_outcomes upsert failed: %s", e)\n'
)

INSERT_CALL = ANCHOR_CALL + '''
    # ── v19.34.216 — LIVE EV HOOK ─────────────────────────────────────────
    # Keep `strategy_stats` (the TQS Setup-pillar EV / real-win-rate feed)
    # fresh on EVERY close. Pre-v216 only `enhanced_scanner.record_alert_outcome`
    # updated strategy_stats, and it required alert_id ∈ scanner._live_alerts —
    # which the modern reconciler/operator/manage-loop close paths bypass. So
    # strategy_stats was orphaned (EV=0 for ~100% of alerts; see backfill).
    # This upsert mirrors `backfill_strategy_stats.py` math + keying so the
    # one-time backfill and the live feed converge. Best-effort; never blocks.
    try:
        _upsert_strategy_stats_bestEffort(
            trade, outcome, r_multiple, pnl.get("net_pnl", 0.0),
        )
    except Exception as _ss_err:
        logger.debug("[v19.34.216 strategy_stats] live hook skipped: %s", _ss_err)
'''

# ── insertion 2: the helper FUNCTIONS, before compute_close_pnl ───────────
ANCHOR_FUNC = "def compute_close_pnl("
INSERT_FUNC = '''def _base_setup(setup_type: Any) -> str:
    """Normalize a setup_type to the family key the TQS Setup pillar queries
    (`enhanced_scanner` consumer at L3201): strip the _long/_short suffix.
    MUST match `backfill_strategy_stats.base_setup` exactly."""
    return str(setup_type or "").split("_long")[0].split("_short")[0]


def _upsert_strategy_stats_bestEffort(
    trade: Any, outcome: str, r_multiple: Optional[float], net_pnl: float,
) -> None:
    """v19.34.216 — incrementally fold one closed trade's R-outcome into the
    `strategy_stats` doc for its setup family, recomputing win_rate + EV with
    the SAME formula + keying as `backfill_strategy_stats.py` so the live hook
    and the one-time backfill stay consistent.

    EV (SMB): win_rate*avg_win_r - (1-win_rate)*avg_loss_r, unlocked at >=5
    r_outcomes; r_outcomes capped to the most-recent 100. Best-effort: any
    failure is swallowed (never blocks the close path)."""
    # _get_outcomes_collection() lazily inits the shared _AO_DB handle.
    if _get_outcomes_collection() is None or _AO_DB is None:
        return
    bs = _base_setup(getattr(trade, "setup_type", None))
    if not bs:
        return

    # Classify win/loss — mirror backfill _classify priority: outcome -> r -> pnl.
    cls: Optional[str] = None
    o = str(outcome or "").lower().strip()
    if o == "won":
        cls = "win"
    elif o == "lost":
        cls = "loss"
    elif r_multiple is not None and r_multiple != 0:
        cls = "win" if r_multiple > 0 else "loss"
    elif net_pnl:
        cls = "win" if net_pnl > 0 else "loss"
    if cls is None:
        return  # true scratch (0 pnl, 0 R) -- skip, matching the backfill

    coll = _AO_DB["strategy_stats"]
    try:
        prev = coll.find_one({"setup_type": bs}) or {}
        r_out = list(prev.get("r_outcomes", []) or [])
        if r_multiple is not None:
            r_out.append(round(float(r_multiple), 4))
            r_out = r_out[-100:]

        trig = int(prev.get("alerts_triggered", 0) or 0) + 1
        won = int(prev.get("alerts_won", 0) or 0) + (1 if cls == "win" else 0)
        lost = int(prev.get("alerts_lost", 0) or 0) + (1 if cls == "loss" else 0)
        total_pnl = round(float(prev.get("total_pnl", 0.0) or 0.0) + float(net_pnl or 0.0), 2)

        win_rate = (won / trig) if trig else 0.0
        wins_r = [x for x in r_out if x > 0]
        losses_r = [x for x in r_out if x <= 0]
        avg_win_r = (sum(wins_r) / len(wins_r)) if wins_r else 0.0
        avg_loss_r = abs(sum(losses_r) / len(losses_r)) if losses_r else 1.0
        ev = 0.0
        if len(r_out) >= 5:
            ev = (win_rate * avg_win_r) - ((1 - win_rate) * avg_loss_r)
        avg_rr = (sum(r_out) / len(r_out)) if r_out else 0.0
        profit_factor = (
            (sum(wins_r) / abs(sum(losses_r)))
            if losses_r and sum(losses_r) != 0 else 0.0
        )

        coll.update_one(
            {"setup_type": bs},
            {"$set": {
                "setup_type": bs,
                "alerts_triggered": trig,
                "total_alerts": trig,
                "alerts_won": won,
                "alerts_lost": lost,
                "total_pnl": total_pnl,
                "win_rate": round(win_rate, 4),
                "profit_factor": round(profit_factor, 3),
                "avg_rr_achieved": round(avg_rr, 3),
                "r_outcomes": [round(x, 4) for x in r_out],
                "avg_win_r": round(avg_win_r, 4),
                "avg_loss_r": round(avg_loss_r, 4),
                "expected_value_r": round(ev, 4),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        logger.info(
            "[v19.34.216 strategy_stats] %s <- r=%s cls=%s -> EV=%.3fR win=%.0f%% (#r=%d)",
            bs, r_multiple, cls, round(ev, 3), win_rate * 100, len(r_out),
        )
    except Exception as e:
        logger.debug("[v19.34.216 strategy_stats] upsert failed for %s: %s", bs, e)


def compute_close_pnl('''

TESTBODY = r'''"""
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
'''


def fail(msg):
    print(f"\n❌ {msg}")
    sys.exit(1)


def main():
    print(f"== deploy_v19_34_216 ==\nrepo: {REPO}\ntarget: {TARGET}")
    if not os.path.isfile(TARGET):
        fail(f"target not found: {TARGET}")

    src = open(TARGET, encoding="utf-8").read()

    if MARKER in src:
        print("✓ already patched (marker present) — patch step is a no-op.")
    else:
        if ANCHOR_CALL not in src:
            fail("call anchor not found — pnl_compute.py drifted; aborting (no changes).")
        if src.count(ANCHOR_FUNC) != 1:
            fail(f"func anchor count != 1 ({src.count(ANCHOR_FUNC)}); aborting.")

        new = src.replace(ANCHOR_CALL, INSERT_CALL, 1)
        new = new.replace(ANCHOR_FUNC, INSERT_FUNC, 1)

        if MARKER not in new or new == src:
            fail("patch produced no change / marker missing; aborting.")

        bak = TARGET + ".v216.bak"
        shutil.copy2(TARGET, bak)
        open(TARGET, "w", encoding="utf-8").write(new)
        try:
            py_compile.compile(TARGET, doraise=True)
        except py_compile.PyCompileError as e:
            shutil.copy2(bak, TARGET)
            fail(f"py_compile failed, rolled back: {e}")
        print("✓ pnl_compute.py patched + compiles clean.")

    # always (re)write the test file
    os.makedirs(os.path.dirname(TESTFILE), exist_ok=True)
    open(TESTFILE, "w", encoding="utf-8").write(TESTBODY)
    print(f"✓ wrote {TESTFILE}")

    # run the test
    print("\n== running pytest ==")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", TESTFILE, "-q"],
        cwd=os.path.join(REPO, "backend"),
    )
    if r.returncode != 0:
        fail("pytest failed — NOT committing. Review above.")
    print("✓ tests green.")

    # commit + push BEFORE restart (DGX restart runs git checkout -- .)
    print("\n== git commit + push ==")
    subprocess.run(["git", "add", "-A"], cwd=REPO)
    cm = subprocess.run(
        ["git", "commit", "-m",
         "v19.34.216 LIVE EV hook: strategy_stats upsert on every close (pnl_compute)"],
        cwd=REPO,
    )
    if cm.returncode == 0:
        subprocess.run(["git", "push"], cwd=REPO)
        print("✓ committed + pushed.")
    else:
        print("ℹ nothing to commit (already committed) — skipping push.")

    print("\n✅ DONE. Now restart the backend:")
    print("   ./start_backend.sh --force")
    print("\nThen watch the hook fire on the next close:")
    print("   grep 'v19.34.216 strategy_stats' /tmp/backend.log")


if __name__ == "__main__":
    main()
