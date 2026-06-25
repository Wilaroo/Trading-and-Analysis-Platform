"""Entry Edge GATE (P4' LIVE abstention) — the cached, FAIL-OPEN serving layer in
front of the conditional Entry Edge Score model (services/entry_edge_score.py).

WHAT: fits the OOS-proven CONDITIONAL model once from closed `bot_trades`, caches it
in-memory (TTL auto-refit + nightly cron), precomputes the bottom-PCTILE predicted-
edge cutoff from the training distribution, and scores a live candidate at decision
time. The DGX head-to-head proved the conditional abstention curve flips the book
from -133R to +EV when the bottom 30% of predicted-edge trades are skipped
(`memory/ENTRY_EDGE_SCORE_PLAN.md`). This turns that proof into a live veto.

CONTRACT — every public call is FAIL-OPEN (any error / missing model -> NO veto):
    get_gate().evaluate(trade_like, entry_context) -> dict | None
        {edge, grade, threshold, pctile, confidence_n, model_n, fitted_at, veto}
        `veto` is True ONLY when the model placed the trade in a real archetype cell
        (confidence_n is not None) AND its predicted edge < the bottom-PCTILE cutoff.
        The CALLER is responsible for the ENTRY_EDGE_VETO_ENABLED arm-check, so the
        score is always available for OBSERVE-mode stamping even when disarmed.

CONFIG (env, all optional — defaults match the validated DGX run):
    ENTRY_EDGE_VETO_ENABLED    armed only when == "true"   (checked by the caller)
    ENTRY_EDGE_VETO_PCTILE     bottom-% cutoff             (default 30)
    ENTRY_EDGE_VETO_TARGET     fit target                  (default realized_r)
    ENTRY_EDGE_VETO_CLIP       winsorize +/-R              (default 3)
    ENTRY_EDGE_VETO_DAYS       training window days        (default 120)
    ENTRY_EDGE_VETO_TTL_HOURS  lazy auto-refit TTL         (default 24)
    ENTRY_EDGE_VETO_MIN_TRADES min book to arm             (default ees.MIN_TRADES)
"""
import os
import logging
import threading
from datetime import datetime, timezone

from services import entry_edge_score as ees

logger = logging.getLogger(__name__)


def _envf(key, default):
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _envi(key, default):
    try:
        return int(float(os.environ.get(key, default)))
    except (TypeError, ValueError):
        return int(default)


# ── PROMOTE decision logic (shared by the live gate + the backtest report) ──────
# The plain-English contract (ENTRY_EDGE_SCORE_PLAN.md Stage 3):
#   • GRADE ranks the trade among its archetype peers; EDGE (in R) decides GO.
#   • GO uses the CONSERVATIVE edge — edge discounted by confidence — so a high
#     edge backed by thin data does NOT get a free pass. STAND DOWN if it isn't
#     positive (a pretty setup in a hostile regime gets benched).
#   • SIZE scales with edge × confidence: high grade + high confidence → up toward
#     SIZE_MAX; weak/uncertain → down toward SIZE_MIN.
_CONF_FACTOR = {"high": 1.0, "medium": 0.6, "low": 0.3}


def _kind_key(f):
    """The trade's archetype 'KIND' (setup × direction) — the peer set the GRADE
    ranks within. Coarser than the finest scoring cell (whose trades all share ONE
    shrunk edge → zero spread → degenerate percentile); broad enough to contain
    varied edges across time_window/regime so the per-archetype percentile is
    meaningful. Returns None when either dim is missing (→ global grade fallback)."""
    st = f.get("setup_type")
    d = f.get("direction")
    if st is None or d is None:
        return None
    return "setup_type=%s|direction=%s" % (st, d)


def compute_decision(edge, grade, confidence_n, veto_threshold):
    """Pure GO/SIZE verdict from a scored candidate. No I/O. Used live + in backtest."""
    go_threshold = _envf("ENTRY_EDGE_GO_THRESHOLD", 0.0)
    smin = _envf("ENTRY_EDGE_SIZE_MIN", 0.5)
    smax = _envf("ENTRY_EDGE_SIZE_MAX", 1.25)

    level = ees.confidence_level(confidence_n) if confidence_n is not None else "low"
    cf = _CONF_FACTOR.get(level, 0.3)
    # discount uncertain POSITIVES toward 0; never rescue negatives
    cons = (edge * cf) if (edge is not None and edge > 0) else edge

    veto = (confidence_n is not None) and (edge is not None) \
        and (veto_threshold is not None) and (edge <= veto_threshold)

    if edge is None or confidence_n is None:
        reason = "unscoreable"
    elif veto:
        reason = "edge_below_veto_cutoff"
    elif cons is None or cons <= go_threshold:
        reason = "nonpositive_conservative_edge"
    else:
        reason = None
    go = reason is None

    if grade is None:
        size_mult = 1.0
    else:
        size_mult = smin + (smax - smin) * (max(0.0, min(100.0, grade)) / 100.0) * cf
        size_mult = round(max(smin, min(smax, size_mult)), 3)

    return {
        "confidence": level,
        "confidence_factor": cf,
        "conservative_edge": round(cons, 4) if cons is not None else None,
        "go_threshold": go_threshold,
        "go": bool(go),
        "stand_down_reason": reason,
        "size_mult": size_mult,
    }


class _EntryEdgeGate:
    def __init__(self):
        self._lock = threading.Lock()
        self._model = None
        self._edges_sorted = None     # ascending in-sample predicted edges (for grade)
        self._cohort_edges = None     # cell_key -> ascending edges (per-archetype grade)
        self._cohort_ci = None        # cell_key -> realized-R CI half-width (confidence)
        self._threshold = None        # bottom-PCTILE predicted-edge cutoff
        self._n = 0
        self._fitted_at = None
        self._pctile = _envi("ENTRY_EDGE_VETO_PCTILE", 30)
        self._min_cohort = _envi("ENTRY_EDGE_GRADE_MIN_COHORT", 12)

    # ---- fit / cache -------------------------------------------------------
    def _is_stale(self):
        if self._model is None or self._fitted_at is None:
            return True
        ttl_h = _envf("ENTRY_EDGE_VETO_TTL_HOURS", 24)
        age_h = (datetime.now(timezone.utc) - self._fitted_at).total_seconds() / 3600.0
        return age_h >= ttl_h

    def _fit(self, db):
        target = os.environ.get("ENTRY_EDGE_VETO_TARGET", "realized_r")
        clip = _envf("ENTRY_EDGE_VETO_CLIP", 3)
        days = _envi("ENTRY_EDGE_VETO_DAYS", 120)
        min_trades = _envi("ENTRY_EDGE_VETO_MIN_TRADES", ees.MIN_TRADES)
        self._pctile = _envi("ENTRY_EDGE_VETO_PCTILE", 30)

        rows, _ = ees.load_training_rows(db, days, target, clip)
        if len(rows) < min_trades:
            logger.info("[edge-gate] insufficient book (%d < %d) — gate stays OPEN",
                        len(rows), min_trades)
            self._model = None
            self._edges_sorted = None
            self._cohort_edges = None
            self._cohort_ci = None
            self._threshold = None
            self._n = len(rows)
            self._fitted_at = datetime.now(timezone.utc)
            return

        model = ees.fit_conditional([(f, tval) for f, _, _, tval in rows])
        # Single pass: global edge distribution (for the bottom-PCTILE veto cutoff) +
        # per-archetype cohort edges (for the rolling per-cell GRADE) + per-cell
        # realized-R CI (the CONFIDENCE width). Grading a candidate within its OWN
        # archetype cell — not the global pool — is the plan's "scored as its own
        # kind" vision; thin cells fall back to global at score time.
        from collections import defaultdict as _dd
        edges = []
        kind_edges = _dd(list)      # (setup × direction) "kind" → edges, for the GRADE
        cell_tvals = _dd(list)      # finest archetype cell → realized-R, for the CI
        for f, _, _, tval in rows:
            sc = ees.score_conditional(model, f)
            e = sc["edge"]
            edges.append(e)
            kk = _kind_key(f)
            if kk is not None:
                kind_edges[kk].append(e)
            ck = sc.get("cell_key")
            if ck is not None:
                cell_tvals[ck].append(tval)
        edges.sort()
        cohort_ci = {}
        for ck, tv in cell_tvals.items():
            nn = len(tv)
            if nn >= 2:
                m = sum(tv) / nn
                var = sum((x - m) ** 2 for x in tv) / (nn - 1)
                cohort_ci[ck] = round(1.96 * (var ** 0.5) / (nn ** 0.5), 4)
        # "skip bottom PCTILE%": k = #trades in the bottom band; threshold = the
        # LARGEST edge still inside it. Veto if edge <= threshold, so a tie-block
        # straddling the boundary (common with shrunk thin cells) is fully cut.
        k = max(1, min(len(edges), int(self._pctile / 100.0 * len(edges))))
        self._model = model
        self._edges_sorted = edges
        self._cohort_edges = {kk: sorted(v) for kk, v in kind_edges.items()}
        self._cohort_ci = cohort_ci
        self._threshold = edges[k - 1]
        self._n = len(edges)
        self._fitted_at = datetime.now(timezone.utc)
        logger.info(
            "[edge-gate] fitted: n=%d target=%s clip=%s days=%s skip_bottom=%d%% "
            "threshold=%.4f kinds=%d", self._n, target, clip, days,
            self._pctile, self._threshold, len(self._cohort_edges))

    def _ensure(self, db, force=False):
        if not force and not self._is_stale():
            return
        with self._lock:
            if force or self._is_stale():
                try:
                    self._fit(db)
                except Exception as e:
                    logger.warning("[edge-gate] fit failed — gate stays OPEN (%s)", e)
                    self._model = None
                    # stamp time so we don't hot-retry-storm on a persistent failure
                    self._fitted_at = datetime.now(timezone.utc)

    def refresh(self, db=None, force=True):
        """Nightly / manual refit. Returns the status dict. Never raises."""
        try:
            if db is None:
                from database import get_database
                db = get_database()
            self._ensure(db, force=force)
        except Exception as e:
            logger.warning("[edge-gate] refresh failed (%s)", e)
        return self.status()

    # ---- scoring -----------------------------------------------------------
    def _grade(self, edge, kind_key=None):
        """Rolling per-archetype percentile (the plan's GRADE). Grade the edge within
        the candidate's OWN 'kind' cohort (setup × direction) when it's thick enough
        (>= _min_cohort); else fall back to the global edge pool. Returns (grade,
        basis)."""
        cohort, basis = None, "global"
        if kind_key and self._cohort_edges:
            c = self._cohort_edges.get(kind_key)
            if c and len(c) >= self._min_cohort:
                cohort, basis = c, "archetype"
        if cohort is None:
            cohort = self._edges_sorted
        if not cohort or edge is None:
            return None, basis
        below = sum(1 for x in cohort if x <= edge)
        return round(below / len(cohort) * 100, 1), basis

    def evaluate(self, trade_like, entry_context):
        """Score a live candidate. FAIL-OPEN: returns None or veto=False on any issue."""
        try:
            from database import get_database
            db = get_database()
            self._ensure(db)
            if self._model is None or self._threshold is None:
                return {"edge": None, "veto": False, "reason": "model_unavailable",
                        "model_n": self._n, "triple": None,
                        "fitted_at": self._fitted_at.isoformat() if self._fitted_at else None}
            factors = ees._raw_factors(trade_like or {}, entry_context or {})
            sc = ees.score_conditional(self._model, factors)
            edge = sc.get("edge")
            cn = sc.get("confidence_n")
            cell_key = sc.get("cell_key")
            # Veto ONLY when the model located this trade in a REAL archetype cell
            # (cn is not None) AND its predicted edge is in the bottom band
            # (edge <= the bottom-PCTILE cutoff). A trade we cannot place in any cell
            # shrinks to the global prior and is NOT vetoed — we only block
            # archetypes we have evidence against.
            veto = (cn is not None) and (edge is not None) and (edge <= self._threshold)
            kind_key = _kind_key(factors)
            grade, grade_basis = self._grade(edge, kind_key)
            ci = self._cohort_ci.get(cell_key) if (self._cohort_ci and cell_key) else None
            out = {
                "edge": edge,
                "grade": grade,
                "grade_basis": grade_basis,
                "threshold": round(self._threshold, 4),
                "pctile": self._pctile,
                "confidence_n": cn,
                "confidence_ci": ci,
                "cell_key": cell_key,
                "model_n": self._n,
                "fitted_at": self._fitted_at.isoformat() if self._fitted_at else None,
                "veto": bool(veto),
            }
            # PROMOTE verdict (GO + sizing) — always computed so shadow mode can
            # observe it; the caller decides whether to act on it.
            decision = compute_decision(edge, grade, cn, self._threshold)
            out.update(decision)
            # Clean UI-facing TRIPLE contract — the EDGE/GRADE/CONFIDENCE the V6
            # provenance ring + Edge drawer read. Stable shape; everything else on
            # `out` is internal detail. 1C.
            out["triple"] = {
                "edge_r": edge,
                "grade": grade,
                "grade_basis": grade_basis,
                "grade_cohort": kind_key,
                "confidence": decision.get("confidence"),
                "confidence_n": cn,
                "confidence_ci": ci,
                "cell": cell_key,
                "verdict": "GO" if decision.get("go") else "STAND_DOWN",
                "stand_down_reason": decision.get("stand_down_reason"),
                "conservative_edge": decision.get("conservative_edge"),
            }
            return out
        except Exception as e:
            logger.debug("[edge-gate] evaluate fail-open (%s)", e)
            return None

    def status(self):
        return {
            "armed": os.environ.get("ENTRY_EDGE_VETO_ENABLED") == "true",
            "model_loaded": self._model is not None,
            "model_n": self._n,
            "skip_bottom_pct": self._pctile,
            "threshold": round(self._threshold, 4) if self._threshold is not None else None,
            "grade_cohorts": len(self._cohort_edges) if self._cohort_edges else 0,
            "grade_min_cohort": self._min_cohort,
            "fitted_at": self._fitted_at.isoformat() if self._fitted_at else None,
            "promote_mode": os.environ.get("ENTRY_EDGE_PROMOTE_MODE", "off"),
            "size_enabled": os.environ.get("ENTRY_EDGE_SIZE_ENABLED") == "true",
            "config": {
                "target": os.environ.get("ENTRY_EDGE_VETO_TARGET", "realized_r"),
                "clip": _envf("ENTRY_EDGE_VETO_CLIP", 3),
                "days": _envi("ENTRY_EDGE_VETO_DAYS", 120),
                "ttl_hours": _envf("ENTRY_EDGE_VETO_TTL_HOURS", 24),
                "min_trades": _envi("ENTRY_EDGE_VETO_MIN_TRADES", ees.MIN_TRADES),
                "go_threshold": _envf("ENTRY_EDGE_GO_THRESHOLD", 0.0),
                "size_min": _envf("ENTRY_EDGE_SIZE_MIN", 0.5),
                "size_max": _envf("ENTRY_EDGE_SIZE_MAX", 1.25),
            },
        }


_GATE = None


def get_gate():
    global _GATE
    if _GATE is None:
        _GATE = _EntryEdgeGate()
    return _GATE
