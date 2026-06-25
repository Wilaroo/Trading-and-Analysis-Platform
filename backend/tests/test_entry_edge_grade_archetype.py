"""1C proof — per-archetype GRADE + per-cell CONFIDENCE-CI + clean triple stamp.

  • score_conditional now returns a `cell_key` (deepest resolved archetype label).
  • the gate grades an edge within its OWN 'kind' cohort (setup × direction) — a
    rolling per-archetype percentile, NOT the global pool — falling back to global
    only when the kind cohort is thin.
  • a per-cell realized-R CI half-width is exposed as the CONFIDENCE width.

The kind cohort (not the finest cell) is required because the conditional model
assigns every trade in one finest cell the SAME shrunk edge → zero spread. The kind
spans multiple cells (time_window/regime) so the percentile is meaningful.
DB-free: drives the gate's grade/cohort logic directly.
"""


def run():
    from services import entry_edge_score as ees
    from services.entry_edge_gate import _EntryEdgeGate, _kind_key

    # breakout-long KIND with 3 distinct cells (open/midday/close) → varied edges.
    rows = []
    for tw, base in [("open", 1.5), ("midday", 0.8), ("close", 0.2)]:
        for i in range(15):
            rows.append(({"direction": "long", "setup_type": "breakout",
                          "time_window": tw, "market_regime": "bull_trend"},
                         base + (i % 2) * 0.05))
    # a contrasting kind to populate the global pool below the breakout-longs.
    for i in range(20):
        rows.append(({"direction": "short", "setup_type": "fade",
                      "time_window": "open", "market_regime": "bear_trend"}, -0.5))

    model = ees.fit_conditional(rows)

    # 1) score_conditional surfaces the finest cell_key.
    sc_close = ees.score_conditional(model, rows[-21][0])  # a "close" breakout-long
    assert sc_close.get("cell_key") and "time_window=close" in sc_close["cell_key"]
    print("✅ cell_key:", sc_close["cell_key"])

    # build the gate internals exactly like _fit does.
    g = _EntryEdgeGate()
    g._min_cohort = 12
    g._model = model
    edges, kind = [], {}
    for f, _t in rows:
        e = ees.score_conditional(model, f)["edge"]
        edges.append(e)
        kk = _kind_key(f)
        kind.setdefault(kk, []).append(e)
    g._edges_sorted = sorted(edges)
    g._cohort_edges = {k: sorted(v) for k, v in kind.items()}
    g._cohort_ci = {}
    g._threshold = g._edges_sorted[0]

    # 2) the WORST cell within breakout-long (close, edge≈0.2) should grade LOW within
    #    its kind, but HIGHER globally (it still beats the fade-shorts at −0.5).
    f_close = {"direction": "long", "setup_type": "breakout",
               "time_window": "close", "market_regime": "bull_trend"}
    edge_low = ees.score_conditional(model, f_close)["edge"]
    grade_arch, basis = g._grade(edge_low, _kind_key(f_close))
    grade_glob, basis_glob = g._grade(edge_low, "setup_type=unknown|direction=long")
    assert basis == "archetype" and basis_glob == "global"
    assert grade_arch < grade_glob, (
        "per-archetype grade (%.1f) must rank the close cell BELOW its global grade "
        "(%.1f) — it is bottom-of-kind but mid-of-pool" % (grade_arch, grade_glob))
    assert grade_arch < 50, "close cell should be bottom third of breakout-longs"
    print("✅ close cell: archetype grade=%.1f (own kind) vs global=%.1f"
          % (grade_arch, grade_glob))

    # 3) the BEST cell (open, edge≈1.5) tops its kind → ~100 archetype.
    f_open = dict(f_close, time_window="open")
    edge_hi = ees.score_conditional(model, f_open)["edge"]
    grade_hi, _ = g._grade(edge_hi, _kind_key(f_open))
    assert grade_hi >= 90, "open cell should top its kind"
    print("✅ open cell: archetype grade=%.1f (top of kind)" % grade_hi)

    # 4) thin/unknown kind → global fallback.
    _, basis_thin = g._grade(0.1, "setup_type=rare|direction=long")
    assert basis_thin == "global"
    print("✅ unknown kind → global fallback")

    print("\n✅ 1C OK — per-archetype (kind) grade + cohort fallback + cell_key surfaced")


if __name__ == "__main__":
    run()
