"""P3' Entry Edge Score — math validation on SYNTHETIC data (no live data needed).

Validates that fit()/score() + the K-fold OOS lift machinery actually recover a
known signal and stay near-zero on pure noise. This is the market-closed proof
that the model logic is sound; the real-data lift is measured on the DGX via
GET /api/slow-learning/entry-edge-score/report.
"""
import random
import sys

from services import entry_edge_score as ees


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def __iter__(self):
        return iter(self._docs)


class FakeColl:
    def __init__(self, docs):
        self._docs = docs

    def find(self, *a, **k):
        return FakeCursor(self._docs)


class FakeDB:
    def __init__(self, docs):
        self._c = FakeColl(docs)

    def __getitem__(self, name):
        return self._c


def _make_trade(time_window, direction, mfe, realized):
    return {
        "status": "closed",
        "setup_type": "rubber_band",
        "timeframe": "scalp",
        "direction": direction,
        "mfe_r": mfe,
        "realized_pnl": realized * 100.0,   # risk_amount=100 → clean_R == realized
        "risk_amount": 100.0,
        "closed_at": "2026-06-20T15:00:00+00:00",
        "entry_context": {
            "time_window": time_window,
            "priority": "high",
            "regime_score": 50.0,
            "technicals": {"rsi": 50.0},
            "trigger_probability": 0.6,
        },
        "tape_score": 5.0,
    }


def test_recovers_known_signal():
    """time_window 'afternoon' is good (+R), 'midday' is bad (−R). OOS lift must
    be positive and top decile must beat bottom decile."""
    rnd = random.Random(7)
    docs = []
    for _ in range(600):
        if rnd.random() < 0.5:
            tw, base = "afternoon", 0.6
        else:
            tw, base = "midday", -0.6
        direction = "long" if rnd.random() < 0.7 else "short"
        noise = rnd.gauss(0, 0.5)
        r = base + noise + (0.0 if direction == "long" else -0.3)
        docs.append(_make_trade(tw, direction, max(0.0, r + 0.3), r))

    rep = ees.generate_report(FakeDB(docs), days=3650, target="realized_r", k_folds=5)
    assert rep["n_used"] >= 500, rep
    sp = rep["oos_spearman_pred_vs_realized"]
    assert sp is not None and sp > 0.15, ("expected positive OOS spearman, got %s" % sp)
    top = rep["oos_decile_lift"][-1]["avg_realized_r"]
    bot = rep["oos_decile_lift"][0]["avg_realized_r"]
    assert top > bot, ("top decile %.3f should beat bottom %.3f" % (top, bot))
    # the planted factor should surface as a strong effect
    facs = [f["factor"] for f in rep["factor_effects"][:3]]
    assert "time_window" in facs, facs
    return rep


def test_noise_no_false_positive():
    """Pure noise → OOS spearman must NOT be falsely positive. The estimator has a
    small CONSERVATIVE negative floor (~−0.04, the leave-out group-mean effect),
    which is the safe direction: it never manufactures lift on noise. Assert the
    mean over many seeds stays below a small positive threshold."""
    sps = []
    for seed in range(12):
        rnd = random.Random(100 + seed)
        docs = []
        for _ in range(400):
            tw = rnd.choice(["afternoon", "midday", "power_hour", "opening_drive"])
            direction = rnd.choice(["long", "short"])
            r = rnd.gauss(0, 1.0)
            docs.append(_make_trade(tw, direction, abs(r), r))
        rep = ees.generate_report(FakeDB(docs), days=3650, target="realized_r", k_folds=5)
        sp = rep["oos_spearman_pred_vs_realized"]
        if sp is not None:
            sps.append(sp)
    mean_sp = sum(sps) / len(sps)
    assert mean_sp < 0.05, ("noise must not produce positive OOS lift; got mean %.4f over %d seeds (%s)" % (mean_sp, len(sps), [round(x, 2) for x in sps]))
    return mean_sp


def test_score_full_triple_and_per_archetype():
    """score_full returns (edge, grade, confidence); a good archetype outranks a
    bad one; and the per-archetype grade check shows positive within-cohort lift."""
    rnd = random.Random(3)
    docs = []
    for _ in range(800):
        if rnd.random() < 0.5:
            tw, base = "afternoon", 0.6
        else:
            tw, base = "midday", -0.6
        direction = "long" if rnd.random() < 0.6 else "short"
        r = base + rnd.gauss(0, 0.5) + (0.0 if direction == "long" else -0.3)
        docs.append(_make_trade(tw, direction, max(0.0, r + 0.3), r))
    rep = ees.generate_report(FakeDB(docs), days=3650, target="realized_r", k_folds=5)

    # within-archetype lift should be positive for the strongest cohort
    pa = rep.get("per_archetype_grade_check") or []
    assert pa and pa[0]["within_archetype_lift"] > 0, pa

    # build a full-data model and confirm the triple orders good vs bad
    data = [(ees._raw_factors(d, d["entry_context"]), d["realized_pnl"] / d["risk_amount"]) for d in docs]
    model = ees.fit([(f, t) for f, t in data])
    cohort = sorted(ees.score(model, f)["edge"] for f, _ in data)
    good = ees.score_full(model, {"time_window": "afternoon", "direction": "long",
                                  "timeframe": "scalp", "priority": "high",
                                  "setup_type": "rubber_band"}, cohort)
    bad = ees.score_full(model, {"time_window": "midday", "direction": "short",
                                 "timeframe": "scalp", "priority": "high",
                                 "setup_type": "rubber_band"}, cohort)
    assert good["edge"] > bad["edge"], (good, bad)
    assert good["grade"] > bad["grade"], (good, bad)
    assert good["confidence"] in ("high", "medium", "low")
    return good, bad


if __name__ == "__main__":
    r1 = test_recovers_known_signal()
    print("SIGNAL: n_used=%d  OOS spearman(realized)=%s  top_decile=%s  bottom_decile=%s" % (
        r1["n_used"], r1["oos_spearman_pred_vs_realized"],
        r1["oos_decile_lift"][-1]["avg_realized_r"], r1["oos_decile_lift"][0]["avg_realized_r"]))
    print("  strongest factors:", [f["factor"] for f in r1["factor_effects"][:3]])
    mean_sp = test_noise_no_false_positive()
    print("NOISE:  mean OOS spearman over 12 seeds = %.4f (must be < 0.05; conservative-negative is fine)" % mean_sp)
    good, bad = test_score_full_triple_and_per_archetype()
    print("TRIPLE: good=%s" % good)
    print("        bad =%s" % bad)
    print("ALL_OK")
