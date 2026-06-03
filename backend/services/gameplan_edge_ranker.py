"""
v19.34.233 (Phase D) — GamePlan realized open-session edge ranker.

Replaces the heuristic pm -> daily -> intraday *append order* of
`stocks_in_play` with a DATA-DRIVEN ranking computed from the bot's own
realized trade history (`trade_outcomes`).

For each stock-in-play we look up the Expected Value in R (EV-R) the bot has
historically realized for that *kind* of setup, bucketed by:

    (setup_type, catalyst_tag, gap_bucket, regime_bias)

…and blend that realized edge with the alert's TQS grade. Because a fine
4-D bucket is often thin (or — for historical rows written before v232 —
missing the catalyst/gap dimensions entirely), the lookup performs a
*shrinkage walk* to progressively coarser buckets:

    L4  (setup, catalyst, gap_bucket, regime)
    L3  (setup, catalyst, regime)
    L2  (setup, regime)
    L1  (setup)

…picking the first level that has >= MIN_SAMPLES decided trades. When no
level qualifies, we COLD-START to the TQS score (current heuristic order is
TQS-driven), tagged `edge_source="tqs_fallback"`.

The regime vocabularies differ across the codebase — the gameplan/regime
engine emits `CONFIRMED_UP` / `HOLD` while `trade_outcomes.context.
market_regime` uses `strong_uptrend` / `range_bound`. Both are reduced to a
shared 3-way bias bucket {up, down, range} so the dimension is comparable.

Pure & side-effect free: the indexer takes a list of outcome dicts so it is
trivially unit-testable without Mongo.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── shared normalizers ────────────────────────────────────────────────────
def regime_bias(regime) -> str:
    """Collapse any regime label (either vocabulary) to {up, down, range}."""
    s = str(regime or "").lower()
    if "down" in s or "bear" in s:
        return "down"
    if "up" in s or "bull" in s:
        return "up"
    return "range"


def gap_bucket(gap_pct) -> str:
    """Bucket the absolute gap percent. Premarket gappers cluster here."""
    try:
        g = abs(float(gap_pct or 0.0))
    except (TypeError, ValueError):
        g = 0.0
    if g < 1.0:
        return "flat"
    if g < 3.0:
        return "small"
    if g < 6.0:
        return "medium"
    return "large"


def normalize_setup(setup) -> str:
    """Round-trip the prettified gameplan setup ("Gap And Go") back to the
    raw `trade_outcomes` vocabulary ("gap_and_go")."""
    return str(setup or "").strip().lower().replace(" ", "_")


_CATALYST_TYPE_MAP = {
    "earnings": "earnings",
    "news": "news",
    "analyst": "analyst",
    "sector_rotation": "sympathy",
    "sympathy": "sympathy",
    "no_catalyst": "no_catalyst",
}

_GRADE_COMPONENT = {
    "A+": 0.95, "A": 0.88, "A-": 0.80,
    "B+": 0.72, "B": 0.62, "B-": 0.52,
    "C+": 0.42, "C": 0.32, "C-": 0.25,
    "D": 0.18, "F": 0.10,
}


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _outcome_catalyst(doc: Dict) -> str:
    """Derive a catalyst tag for a historical outcome. Prefers the v232+
    top-level `catalyst_tag`; falls back to the older
    `context.fundamentals.catalyst_type` / `has_catalyst`. Returns "" when
    unknown so the row only contributes to the catalyst-agnostic buckets."""
    tag = str(doc.get("catalyst_tag") or "").strip().lower()
    if tag:
        return tag
    fund = (doc.get("context") or {}).get("fundamentals") or {}
    ct = str(fund.get("catalyst_type") or "").strip().lower()
    if ct in _CATALYST_TYPE_MAP:
        return _CATALYST_TYPE_MAP[ct]
    if fund.get("has_catalyst") is False:
        return "no_catalyst"
    return ""


class GamePlanEdgeRanker:
    """Index realized `trade_outcomes` and rank stocks-in-play by EV-R."""

    MIN_SAMPLES = 5      # decided trades required to trust a bucket
    SHRINK_K0 = 10.0     # Bayesian shrinkage half-weight constant
    W_EV = 0.65          # max EV weight (asymptotic, large sample)
    LOOKBACK_DAYS = 120

    def __init__(self, outcomes: List[Dict]):
        # key tuple -> aggregate dict
        self._b: Dict[Tuple, Dict] = {}
        self._index(outcomes or [])

    # ── construction ──────────────────────────────────────────────────────
    @classmethod
    def from_db(cls, db, lookback_days: Optional[int] = None) -> "GamePlanEdgeRanker":
        outcomes: List[Dict] = []
        days = lookback_days or cls.LOOKBACK_DAYS
        try:
            col = db["trade_outcomes"]
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            cur = col.find(
                {"created_at": {"$gte": cutoff},
                 "outcome": {"$in": ["won", "lost"]}},
                {"_id": 0, "setup_type": 1, "outcome": 1, "actual_r": 1,
                 "catalyst_tag": 1, "gap_pct": 1,
                 "context.market_regime": 1, "context.fundamentals": 1},
            )
            outcomes = list(cur)
        except Exception as e:  # noqa: BLE001 — best-effort; never block a gameplan
            logger.warning("[edge-rank] trade_outcomes load failed: %s", e)
        return cls(outcomes)

    # ── indexing ──────────────────────────────────────────────────────────
    @staticmethod
    def _blank() -> Dict:
        return {"wins": 0, "losses": 0, "win_r_sum": 0.0, "win_n": 0,
                "loss_r_sum": 0.0, "loss_n": 0}

    def _accum(self, key: Tuple, outcome: str, r: float) -> None:
        a = self._b.get(key)
        if a is None:
            a = self._blank()
            self._b[key] = a
        if outcome == "won":
            a["wins"] += 1
            a["win_r_sum"] += r
            a["win_n"] += 1
        else:  # lost
            a["losses"] += 1
            a["loss_r_sum"] += r
            a["loss_n"] += 1

    def _index(self, outcomes: List[Dict]) -> None:
        for o in outcomes:
            outcome = str(o.get("outcome") or "").lower()
            if outcome not in ("won", "lost"):
                continue
            setup = normalize_setup(o.get("setup_type"))
            if not setup:
                continue
            ctx = o.get("context") or {}
            rb = regime_bias(ctx.get("market_regime"))
            cat = _outcome_catalyst(o)
            gb = gap_bucket(o.get("gap_pct"))
            r = _safe_float(o.get("actual_r"))
            for key in (
                ("L4", setup, cat, gb, rb),
                ("L3", setup, cat, rb),
                ("L2", setup, rb),
                ("L1", setup),
            ):
                self._accum(key, outcome, r)

    # ── scoring math ──────────────────────────────────────────────────────
    @staticmethod
    def _ev_r(a: Dict) -> Optional[float]:
        decided = a["wins"] + a["losses"]
        if decided == 0:
            return None
        wr = a["wins"] / decided
        avg_win = (a["win_r_sum"] / a["win_n"]) if a["win_n"] else 0.0
        avg_loss = abs(a["loss_r_sum"] / a["loss_n"]) if a["loss_n"] else 1.0
        return wr * avg_win - (1.0 - wr) * avg_loss

    def _lookup(self, setup: str, cat: str, gb: str, rb: str) -> Optional[Tuple[float, int, str]]:
        """Shrinkage walk L4 -> L1. First level with >= MIN_SAMPLES wins."""
        for key in (
            ("L4", setup, cat, gb, rb),
            ("L3", setup, cat, rb),
            ("L2", setup, rb),
            ("L1", setup),
        ):
            a = self._b.get(key)
            if a and (a["wins"] + a["losses"]) >= self.MIN_SAMPLES:
                ev = self._ev_r(a)
                if ev is not None:
                    return ev, a["wins"] + a["losses"], key[0]
        return None

    @staticmethod
    def _tqs_component(stock: Dict) -> float:
        ts = _safe_float(stock.get("tqs_score"))
        if ts > 0:
            return max(0.0, min(1.0, ts / 100.0))
        grade = str(stock.get("tqs_grade") or "").upper().strip()
        return _GRADE_COMPONENT.get(grade, 0.5)

    @staticmethod
    def _ev_component(ev_r: float) -> float:
        # Map EV-R in [-1, +1] linearly into [0, 1], clamp the tails.
        return max(0.0, min(1.0, 0.5 + ev_r / 2.0))

    # ── public API ────────────────────────────────────────────────────────
    def score_stock(self, stock: Dict, rb: str) -> Dict:
        """Annotate a single stock entry in place with edge_* fields."""
        setup = normalize_setup(stock.get("setup_type"))
        cat = str(stock.get("catalyst_tag") or "").strip().lower()
        gb = gap_bucket(stock.get("gap_pct"))
        tqs_comp = self._tqs_component(stock)

        hit = self._lookup(setup, cat, gb, rb)
        if hit is None:
            # Cold-start: rank by TQS, preserving the existing heuristic order.
            stock["edge_source"] = "tqs_fallback"
            stock["edge_score"] = round(tqs_comp, 4)
            stock["edge_ev_r"] = None
            stock["edge_sample_size"] = 0
            stock["edge_bucket_level"] = None
            return stock

        ev_r, n, level = hit
        ev_comp = self._ev_component(ev_r)
        # Sample-size shrinkage: trust EV more as n grows; lean on TQS when thin.
        k = n / (n + self.SHRINK_K0)
        ev_w = self.W_EV * k
        score = ev_w * ev_comp + (1.0 - ev_w) * tqs_comp

        stock["edge_source"] = "realized"
        stock["edge_score"] = round(score, 4)
        stock["edge_ev_r"] = round(ev_r, 3)
        stock["edge_sample_size"] = n
        stock["edge_bucket_level"] = level
        return stock

    def rank(self, stocks: List[Dict], regime) -> List[Dict]:
        """Score + sort `stocks` in place (descending edge_score); assign
        a 1-indexed `edge_rank`. Returns the same list for convenience."""
        if not stocks:
            return stocks
        rb = regime_bias(regime)
        for s in stocks:
            self.score_stock(s, rb)
        # Stable sort keeps prior order for ties (TQS/heuristic tiebreak).
        stocks.sort(key=lambda s: s.get("edge_score", 0.0), reverse=True)
        for i, s in enumerate(stocks, 1):
            s["edge_rank"] = i
        return stocks
