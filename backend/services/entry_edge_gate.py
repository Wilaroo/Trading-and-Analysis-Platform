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
        self._threshold = None        # bottom-PCTILE predicted-edge cutoff
        self._n = 0
        self._fitted_at = None
        self._pctile = _envi("ENTRY_EDGE_VETO_PCTILE", 30)

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
            self._threshold = None
            self._n = len(rows)
            self._fitted_at = datetime.now(timezone.utc)
            return

        model = ees.fit_conditional([(f, tval) for f, _, _, tval in rows])
        edges = sorted(ees.score_conditional(model, f)["edge"] for f, _, _, _ in rows)
        # "skip bottom PCTILE%": k = #trades in the bottom band; threshold = the
        # LARGEST edge still inside it. Veto if edge <= threshold, so a tie-block
        # straddling the boundary (common with shrunk thin cells) is fully cut.
        k = max(1, min(len(edges), int(self._pctile / 100.0 * len(edges))))
        self._model = model
        self._edges_sorted = edges
        self._threshold = edges[k - 1]
        self._n = len(edges)
        self._fitted_at = datetime.now(timezone.utc)
        logger.info(
            "[edge-gate] fitted: n=%d target=%s clip=%s days=%s skip_bottom=%d%% "
            "threshold=%.4f", self._n, target, clip, days, self._pctile, self._threshold)

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
    def _grade(self, edge):
        e = self._edges_sorted
        if not e or edge is None:
            return None
        below = sum(1 for x in e if x <= edge)
        return round(below / len(e) * 100, 1)

    def evaluate(self, trade_like, entry_context):
        """Score a live candidate. FAIL-OPEN: returns None or veto=False on any issue."""
        try:
            from database import get_database
            db = get_database()
            self._ensure(db)
            if self._model is None or self._threshold is None:
                return {"edge": None, "veto": False, "reason": "model_unavailable",
                        "model_n": self._n,
                        "fitted_at": self._fitted_at.isoformat() if self._fitted_at else None}
            factors = ees._raw_factors(trade_like or {}, entry_context or {})
            sc = ees.score_conditional(self._model, factors)
            edge = sc.get("edge")
            cn = sc.get("confidence_n")
            # Veto ONLY when the model located this trade in a REAL archetype cell
            # (cn is not None) AND its predicted edge is in the bottom band
            # (edge <= the bottom-PCTILE cutoff). A trade we cannot place in any cell
            # shrinks to the global prior and is NOT vetoed — we only block
            # archetypes we have evidence against.
            veto = (cn is not None) and (edge is not None) and (edge <= self._threshold)
            grade = self._grade(edge)
            out = {
                "edge": edge,
                "grade": grade,
                "threshold": round(self._threshold, 4),
                "pctile": self._pctile,
                "confidence_n": cn,
                "model_n": self._n,
                "fitted_at": self._fitted_at.isoformat() if self._fitted_at else None,
                "veto": bool(veto),
            }
            # PROMOTE verdict (GO + sizing) — always computed so shadow mode can
            # observe it; the caller decides whether to act on it.
            out.update(compute_decision(edge, grade, cn, self._threshold))
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
            "fitted_at": self._fitted_at.isoformat() if self._fitted_at else None,
            "promote_mode": os.environ.get("ENTRY_EDGE_PROMOTE_MODE", "off"),
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
