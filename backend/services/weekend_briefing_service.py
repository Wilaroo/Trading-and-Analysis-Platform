"""
Weekend Briefing Service
========================

Generates a comprehensive Sunday-afternoon report with:
  1. last_week_recap     — sector ETF performance + user closed P&L
  2. major_news          — top headlines from the past 7 days
  3. earnings_calendar   — companies reporting next 5 trading days
  4. macro_calendar      — economic events (CPI, Fed, jobs)
  5. sector_catalysts    — IPOs + FDA + conference-flagged headlines
  6. gameplan            — bot's top watches + LLM-synthesized thesis
  7. risk_map            — landmines (earnings on held positions, big macro days)

Data sources (per user contract — IB-first, Finnhub second, no Alpaca):
  * IB historical_data (Mongo) — sector ETF returns, closed positions
  * Finnhub                    — news, earnings, economic calendar, IPO calendar
  * Local LLM (gpt-oss:120b-cloud) — gameplan synthesis only

Caching:
  Briefings are keyed by ISO week (`%G-W%V`) and cached in
  `weekend_briefings`. Re-running for the same week upserts. The Sunday
  14:00 ET scheduler creates the canonical weekly entry; the on-demand
  `/generate` endpoint also lets the operator force a refresh.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
FINNHUB_TIMEOUT = 10  # seconds — Finnhub is fast in normal conditions

# Sector ETFs — same set used by BriefMeAgent so signals stay consistent.
SECTOR_ETFS = {
    "XLK":  "Technology",
    "XLF":  "Financials",
    "XLE":  "Energy",
    "XLV":  "Healthcare",
    "XLI":  "Industrials",
    "XLC":  "Comm Services",
    "XLY":  "Cons Discretionary",
    "XLP":  "Cons Staples",
    "XLU":  "Utilities",
    "XLRE": "Real Estate",
    "XLB":  "Materials",
}

# Major mega-caps we'll include in the earnings filter even if they're not
# already in the user's positions, so the operator sees the big-tape names.
DEFAULT_EARNINGS_WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
    "AVGO", "NFLX", "CRM", "ORCL",
]

# Catalyst keywords that flag a generic news headline as sector-moving.
CATALYST_KEYWORDS = [
    "fda", "approval", "earnings", "guidance",
    "ipo", "merger", "acquisition", "spinoff",
    "fed", "fomc", "rate", "powell",
    "lawsuit", "settlement", "investigation",
    "conference", "analyst day", "investor day",
]


def _iso_week(now_utc: Optional[datetime] = None) -> str:
    """Return the ISO week id we use as the briefing's `_id`.

    Uses ET to bucket Sunday-afternoon runs into the upcoming Mon-Fri week.
    """
    et = (now_utc or datetime.now(timezone.utc)) - timedelta(hours=5)
    return et.strftime("%G-W%V")


def _next_trading_window(now_utc: Optional[datetime] = None) -> Dict[str, str]:
    """Return ISO date strings for "next 5 trading days" earnings/macro windows.

    We do NOT consult a holiday calendar here — Finnhub returns events
    per-date so a holiday day in the window just yields zero results.
    """
    now = now_utc or datetime.now(timezone.utc)
    return {
        "from": now.strftime("%Y-%m-%d"),
        "to": (now + timedelta(days=7)).strftime("%Y-%m-%d"),
    }


def _last_week_window(now_utc: Optional[datetime] = None) -> Dict[str, str]:
    """ISO date strings for "the past 7 days" used in news + recap fetches."""
    now = now_utc or datetime.now(timezone.utc)
    return {
        "from": (now - timedelta(days=7)).strftime("%Y-%m-%d"),
        "to": now.strftime("%Y-%m-%d"),
    }


def _latest_ib_close(db, symbol: str) -> Optional[float]:
    """Most recent 1-day close for `symbol` from ib_historical_data."""
    if db is None or not symbol:
        return None
    try:
        bar = db["ib_historical_data"].find_one(
            {"symbol": symbol.upper(), "bar_size": {"$in": ["1day", "1 day"]}},
            {"_id": 0, "close": 1, "date": 1},
            sort=[("date", -1)],
        )
        if not bar:
            return None
        return float(bar.get("close")) if bar.get("close") is not None else None
    except Exception as exc:
        logger.warning(f"weekend_briefing._latest_ib_close({symbol}) failed: {exc}")
        return None


def _enrich_watches_with_signal_prices(db, watches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach `signal_price` (latest IB close at briefing-generation time)
    to each watch so the Friday-close snapshot can compute a P&L.
    Non-destructive — leaves watches without IB data untouched."""
    if not watches:
        return watches
    enriched: List[Dict[str, Any]] = []
    for w in watches:
        sym = (w.get("symbol") or "").upper()
        price = _latest_ib_close(db, sym)
        new_w = dict(w)
        if price is not None:
            new_w["signal_price"] = round(price, 4)
        enriched.append(new_w)
    return enriched


def _previous_iso_week(now_utc: Optional[datetime] = None) -> str:
    """ISO week id for the immediately-prior week — used to look up last
    Sunday's gameplan when generating the new Sunday's briefing."""
    et = (now_utc or datetime.now(timezone.utc)) - timedelta(hours=5)
    return (et - timedelta(days=7)).strftime("%G-W%V")


# ──────────────────────────────────────────────────────────────────────
# Section builders — each is independently testable + safely fallback to
# an empty payload on upstream failure so a single sub-source outage
# doesn't blow up the whole briefing.
# ──────────────────────────────────────────────────────────────────────


def _sector_returns_from_ib(db, days_back: int = 7) -> List[Dict[str, Any]]:
    """Compute sector ETF total return for the last `days_back` days.

    Reads from `ib_historical_data` (1-day bars) so we're 100% IB-only
    for the price source. Returns a list sorted by `change_pct` desc.
    Empty list if the data isn't available.
    """
    if db is None:
        return []
    try:
        cutoff_recent = datetime.now(timezone.utc) - timedelta(days=2)
        cutoff_old = datetime.now(timezone.utc) - timedelta(days=days_back + 4)
        results: List[Dict[str, Any]] = []
        for sym, label in SECTOR_ETFS.items():
            cursor = db["ib_historical_data"].find(
                {"symbol": sym, "bar_size": {"$in": ["1day", "1 day"]}},
                {"_id": 0, "date": 1, "close": 1},
                sort=[("date", -1)],
                limit=days_back + 5,
            )
            bars = list(cursor)
            if len(bars) < 2:
                continue
            recent = next((b for b in bars
                           if _bar_is_after(b["date"], cutoff_recent)), bars[0])
            old = next((b for b in bars
                        if _bar_is_before(b["date"], cutoff_old)), bars[-1])
            try:
                ro = float(old["close"])
                rn = float(recent["close"])
                if ro <= 0:
                    continue
                pct = (rn - ro) / ro * 100.0
                results.append({
                    "symbol": sym,
                    "name": label,
                    "change_pct": round(pct, 2),
                    "close": round(rn, 2),
                })
            except (ValueError, TypeError):
                continue
        results.sort(key=lambda r: r["change_pct"], reverse=True)
        return results
    except Exception as exc:  # noqa: BLE001 — service must never raise
        logger.warning(f"weekend_briefing._sector_returns_from_ib failed: {exc}")
        return []


def _bar_is_after(bar_date: Any, cutoff: datetime) -> bool:
    """Loose comparison — bar dates may be ISO strings OR datetime objects."""
    try:
        if isinstance(bar_date, str):
            d = datetime.fromisoformat(bar_date.replace("Z", "+00:00"))
        else:
            d = bar_date
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d >= cutoff
    except Exception:
        return False


def _bar_is_before(bar_date: Any, cutoff: datetime) -> bool:
    try:
        if isinstance(bar_date, str):
            d = datetime.fromisoformat(bar_date.replace("Z", "+00:00"))
        else:
            d = bar_date
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d <= cutoff
    except Exception:
        return False


def _user_closed_positions_recap(db, days_back: int = 7) -> Dict[str, Any]:
    """Aggregate the user's closed-trade results from the past week."""
    if db is None:
        return {"trades": [], "summary": {}}
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        # Try a couple of likely collection names the codebase uses.
        for col_name in ("closed_positions", "trade_history", "trades"):
            if col_name not in db.list_collection_names():
                continue
            cursor = db[col_name].find(
                {"closed_at": {"$gte": cutoff.isoformat()}},
                {"_id": 0, "symbol": 1, "realized_pnl": 1, "pnl": 1,
                 "setup_type": 1, "closed_at": 1},
                limit=200,
            )
            trades = []
            for t in cursor:
                pnl = t.get("realized_pnl", t.get("pnl"))
                if pnl is None:
                    continue
                trades.append({
                    "symbol": t.get("symbol"),
                    "setup": t.get("setup_type"),
                    "pnl": round(float(pnl), 2),
                    "closed_at": t.get("closed_at"),
                })
            if trades:
                wins = sum(1 for t in trades if t["pnl"] > 0)
                losses = sum(1 for t in trades if t["pnl"] < 0)
                total_pnl = round(sum(t["pnl"] for t in trades), 2)
                return {
                    "trades": trades[:25],
                    "summary": {
                        "total_trades": len(trades),
                        "wins": wins,
                        "losses": losses,
                        "win_rate": round(wins / max(1, len(trades)), 3),
                        "total_pnl": total_pnl,
                    },
                }
        return {"trades": [], "summary": {}}
    except Exception as exc:
        logger.warning(f"weekend_briefing._user_closed_positions_recap failed: {exc}")
        return {"trades": [], "summary": {}}


def _fetch_finnhub_market_news() -> List[Dict[str, Any]]:
    if not FINNHUB_API_KEY:
        return []
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/news",
            params={"category": "general", "token": FINNHUB_API_KEY},
            timeout=FINNHUB_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json() or []
        # Filter to last 7 days.
        cutoff_ts = (datetime.now(timezone.utc) - timedelta(days=7)).timestamp()
        out = []
        for it in items:
            if (it.get("datetime") or 0) < cutoff_ts:
                continue
            out.append({
                "headline": (it.get("headline") or "").strip(),
                "summary": (it.get("summary") or "").strip()[:400],
                "source": it.get("source") or "Finnhub",
                "url": it.get("url"),
                "datetime": it.get("datetime"),
                "related": (it.get("related") or "").split(",") if it.get("related") else [],
            })
        # Newest first, cap to 20.
        out.sort(key=lambda h: h.get("datetime") or 0, reverse=True)
        return out[:20]
    except Exception as exc:
        logger.warning(f"weekend_briefing._fetch_finnhub_market_news failed: {exc}")
        return []


def _fetch_finnhub_earnings_calendar(symbols: List[str]) -> List[Dict[str, Any]]:
    if not FINNHUB_API_KEY:
        return []
    win = _next_trading_window()
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/calendar/earnings",
            params={"from": win["from"], "to": win["to"], "token": FINNHUB_API_KEY},
            timeout=FINNHUB_TIMEOUT,
        )
        resp.raise_for_status()
        events = resp.json().get("earningsCalendar", []) or []
        watch_set = {s.upper() for s in symbols if s}
        out: List[Dict[str, Any]] = []
        for e in events:
            sym = (e.get("symbol") or "").upper()
            # Always include user's symbols + mega-caps. Other tickers
            # are skipped — the briefing is meant to be focused.
            if sym not in watch_set:
                continue
            timing_raw = (e.get("hour") or "").lower()
            timing = ("Before Open" if timing_raw == "bmo"
                      else "After Close" if timing_raw == "amc"
                      else "TBD")
            out.append({
                "symbol": sym,
                "date": e.get("date"),
                "timing": timing,
                "eps_estimate": e.get("epsEstimate"),
                "revenue_estimate": e.get("revenueEstimate"),
            })
        out.sort(key=lambda x: (x.get("date") or "", x.get("timing") or ""))
        return out
    except Exception as exc:
        logger.warning(f"weekend_briefing._fetch_finnhub_earnings_calendar failed: {exc}")
        return []


def _fetch_finnhub_economic_calendar() -> List[Dict[str, Any]]:
    if not FINNHUB_API_KEY:
        return []
    win = _next_trading_window()
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/calendar/economic",
            params={"from": win["from"], "to": win["to"], "token": FINNHUB_API_KEY},
            timeout=FINNHUB_TIMEOUT,
        )
        resp.raise_for_status()
        events = resp.json().get("economicCalendar", []) or []
        # Keep only US events with notable impact (high) — Finnhub uses
        # an `impact` field with "high" / "medium" / "low".
        out = []
        for e in events:
            country = (e.get("country") or "").upper()
            impact = (e.get("impact") or "").lower()
            if country and country != "US":
                continue
            if impact not in ("high", "medium"):
                continue
            out.append({
                "event": e.get("event"),
                "time": e.get("time"),
                "impact": impact,
                "actual": e.get("actual"),
                "estimate": e.get("estimate"),
                "prev": e.get("prev"),
                "unit": e.get("unit"),
            })
        # Stable order: by time string.
        out.sort(key=lambda x: x.get("time") or "")
        return out[:30]
    except Exception as exc:
        logger.warning(f"weekend_briefing._fetch_finnhub_economic_calendar failed: {exc}")
        return []


def _fetch_finnhub_ipo_calendar() -> List[Dict[str, Any]]:
    if not FINNHUB_API_KEY:
        return []
    win = _next_trading_window()
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/calendar/ipo",
            params={"from": win["from"], "to": win["to"], "token": FINNHUB_API_KEY},
            timeout=FINNHUB_TIMEOUT,
        )
        resp.raise_for_status()
        events = resp.json().get("ipoCalendar", []) or []
        out = []
        for e in events:
            out.append({
                "symbol": e.get("symbol"),
                "name": e.get("name"),
                "date": e.get("date"),
                "exchange": e.get("exchange"),
                "price_range": e.get("price"),
                "shares": e.get("numberOfShares"),
            })
        return out[:15]
    except Exception as exc:
        logger.warning(f"weekend_briefing._fetch_finnhub_ipo_calendar failed: {exc}")
        return []


def _filter_sector_catalysts(headlines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pull headlines containing catalyst keywords for the catalyst section."""
    out = []
    for h in headlines:
        text = f"{h.get('headline', '')} {h.get('summary', '')}".lower()
        matched = [kw for kw in CATALYST_KEYWORDS if kw in text]
        if matched:
            out.append({**h, "matched_keywords": matched[:3]})
    return out[:12]


def _build_risk_map(positions: List[str], earnings: List[Dict[str, Any]],
                    macro: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Identify "landmines" — known things to watch out for next week."""
    risks: List[Dict[str, Any]] = []
    pos_set = {s.upper() for s in positions if s}
    # 1. Earnings on a held position.
    for e in earnings:
        if e.get("symbol", "").upper() in pos_set:
            risks.append({
                "type": "earnings_on_position",
                "severity": "high",
                "symbol": e["symbol"],
                "detail": (
                    f"Earnings {e.get('date')} {e.get('timing')} on held position "
                    f"{e['symbol']} — consider hedging or trimming."
                ),
            })
    # 2. High-impact macro events.
    for m in macro:
        if m.get("impact") == "high":
            risks.append({
                "type": "high_impact_macro",
                "severity": "medium",
                "detail": f"{m.get('event')} ({m.get('time')}) — expect volatility.",
            })
    return risks[:15]


# ──────────────────────────────────────────────────────────────────────
# LLM gameplan synthesis
# ──────────────────────────────────────────────────────────────────────


_GAMEPLAN_SYSTEM_PROMPT = (
    "You are SentCom, an AI trading-bot strategist writing the operator's "
    "weekly gameplan note for the upcoming Mon-Fri trading week. Be "
    "concrete, opinionated, and brief. Always cite specific tickers when "
    "relevant. Avoid filler and disclaimers.\n\n"
    "OUTPUT STRICT JSON ONLY (no prose before or after, no markdown fences). "
    "The JSON object must match this schema exactly:\n"
    "{\n"
    '  "text": "<4-6 short paragraphs covering market backdrop and reasoning, '
    'separated by \\n\\n>",\n'
    '  "watches": [\n'
    "    {\n"
    '      "symbol": "<TICKER>",\n'
    '      "thesis": "<one-line thesis, 80 chars max>",\n'
    '      "key_level": "<price level or trigger, e.g. \\"break above $185\\">",\n'
    '      "invalidation": "<what kills the trade, 80 chars max>"\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Provide 3-5 watches. The `text` ends with a one-line risk caveat."
)


def _coerce_gameplan_payload(raw: str) -> Dict[str, Any]:
    """Parse the LLM's JSON-only response into a structured gameplan.

    Resilient to common model misbehaviours:
      * Wraps in ```json fences → strip them.
      * Trails with prose → take the first balanced JSON object.
      * Returns plain prose → fall back to {"text": <prose>, "watches": []}
        so the UI still renders the paragraph view.

    Always returns a dict with `text: str` and `watches: list[dict]`.
    """
    import json
    import re

    if not raw:
        return {"text": "", "watches": []}

    cleaned = raw.strip()
    # Strip optional markdown fences.
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)

    # Try direct parse first.
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Last-ditch — find the first balanced { ... } block.
        m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                return {"text": cleaned[:2000], "watches": []}
        else:
            return {"text": cleaned[:2000], "watches": []}

    if not isinstance(parsed, dict):
        return {"text": cleaned[:2000], "watches": []}

    text = str(parsed.get("text") or "").strip()
    watches_raw = parsed.get("watches") or []
    watches: List[Dict[str, str]] = []
    if isinstance(watches_raw, list):
        for w in watches_raw[:5]:  # cap at 5 — UI fits ~4 cards comfortably
            if not isinstance(w, dict):
                continue
            sym = str(w.get("symbol") or "").upper().strip()
            if not sym or len(sym) > 6:
                continue
            watches.append({
                "symbol": sym,
                "thesis": str(w.get("thesis") or "").strip()[:160],
                "key_level": str(w.get("key_level") or "").strip()[:80],
                "invalidation": str(w.get("invalidation") or "").strip()[:160],
            })

    return {"text": text, "watches": watches}


async def _synthesize_gameplan(facts: Dict[str, Any]) -> Dict[str, Any]:
    """Ask the local LLM to compose the gameplan + structured watches.

    Returns ``{"text": str, "watches": [{symbol, thesis, key_level, invalidation}]}``.
    Empty payload (`{"text": "", "watches": []}`) when LLM is unavailable —
    callers should treat this as a degraded section, not an error.
    """
    try:
        from agents.llm_provider import get_llm_provider
        provider = get_llm_provider()
    except Exception as exc:
        logger.warning(f"weekend_briefing: LLM unavailable ({exc}) — skipping gameplan")
        return {"text": "", "watches": []}
    if provider is None:
        return {"text": "", "watches": []}

    # Compose a tight fact pack for the prompt — keep it small or the
    # cloud model rate-limits us.
    sectors = facts.get("last_week_recap", {}).get("sectors", [])[:5]
    earnings = facts.get("earnings_calendar", [])[:8]
    macro = facts.get("macro_calendar", [])[:5]
    positions = facts.get("positions_held", [])[:8]
    catalysts = facts.get("sector_catalysts", [])[:6]
    summary_lines: List[str] = []
    if sectors:
        leaders = ", ".join(f"{s['symbol']} {s['change_pct']:+.1f}%" for s in sectors[:3])
        laggards = ", ".join(
            f"{s['symbol']} {s['change_pct']:+.1f}%" for s in sectors[-3:]
        )
        summary_lines.append(f"Last-week sector leaders: {leaders}")
        summary_lines.append(f"Laggards: {laggards}")
    if earnings:
        summary_lines.append("Notable earnings: " + ", ".join(
            f"{e['symbol']} {e.get('date', '')}" for e in earnings
        ))
    if macro:
        summary_lines.append("Macro: " + ", ".join(
            (m.get("event") or "") for m in macro
        ))
    if positions:
        summary_lines.append("Currently held: " + ", ".join(positions))
    if catalysts:
        summary_lines.append("Catalysts seen: " + ", ".join(
            (c.get("headline") or "")[:80] for c in catalysts[:3]
        ))

    # Self-improvement signal — last 4 weeks of gameplan grades. Given
    # to the model so it can adjust thesis style based on what's been
    # working vs flopping. Critical for closing the self-correct loop.
    track_record = facts.get("track_record") or {}
    if track_record.get("total_calls"):
        wr = int(track_record.get("win_rate", 0) * 100)
        avg = track_record.get("avg_change_pct")
        summary_lines.append(
            f"YOUR RECENT TRACK RECORD ({track_record.get('weeks_graded')} weeks, "
            f"{track_record.get('total_calls')} calls): "
            f"{track_record.get('wins')}W/{track_record.get('losses')}L · "
            f"{wr}% WR · avg {avg:+.2f}%"
        )
        bc = track_record.get("best_call") or {}
        wc = track_record.get("worst_call") or {}
        if bc.get("symbol") and bc.get("change_pct") is not None:
            summary_lines.append(
                f"Best call: {bc['symbol']} {bc['change_pct']:+.2f}% "
                f"({bc.get('iso_week', '')})"
            )
        if wc.get("symbol") and wc.get("change_pct") is not None:
            summary_lines.append(
                f"Worst call: {wc['symbol']} {wc['change_pct']:+.2f}% "
                f"({wc.get('iso_week', '')})"
            )
        summary_lines.append(
            "Use this track record to self-correct — lean into the thesis "
            "style of the winners and dial down what's been losing."
        )

    prompt = "\n".join([
        "Compose the weekly gameplan note based on these facts:",
        *summary_lines,
        "",
        "Audience: a discretionary day-trading operator who runs an AI bot.",
        "Reminder: respond with STRICT JSON only — no prose, no markdown.",
    ])

    try:
        resp = await provider.generate(
            prompt=prompt,
            system_prompt=_GAMEPLAN_SYSTEM_PROMPT,
            temperature=0.4,
            max_tokens=1200,
        )
        if not getattr(resp, "success", False):
            logger.warning(f"weekend_briefing LLM call failed: {getattr(resp, 'error', 'unknown')}")
            return {"text": "", "watches": []}
        return _coerce_gameplan_payload(resp.content or "")
    except Exception as exc:
        logger.warning(f"weekend_briefing LLM call exception: {exc}")
        return {"text": "", "watches": []}


# ──────────────────────────────────────────────────────────────────────
# Top-level orchestrator
# ──────────────────────────────────────────────────────────────────────


class WeekendBriefingService:
    """Generates and caches the Sunday-afternoon weekly briefing."""

    COLLECTION = "weekend_briefings"
    SNAPSHOT_COLLECTION = "friday_close_snapshots"

    def __init__(self, db):
        self._db = db
        if db is not None:
            try:
                db[self.COLLECTION].create_index([("_id", 1)])
                db[self.COLLECTION].create_index([("generated_at", -1)])
                db[self.SNAPSHOT_COLLECTION].create_index([("_id", 1)])
                db[self.SNAPSHOT_COLLECTION].create_index([("snapshot_at", -1)])
            except Exception:
                pass  # missing perms — non-fatal

    # ── Cache reads ────────────────────────────────────────────────
    def get_latest(self) -> Optional[Dict[str, Any]]:
        if self._db is None:
            return None
        try:
            doc = self._db[self.COLLECTION].find_one(
                {"_id": _iso_week()}, projection={"_id": 0}
            )
            if doc:
                return doc
            # Fallback — most recently generated regardless of week.
            doc = self._db[self.COLLECTION].find_one(
                sort=[("generated_at", -1)], projection={"_id": 0}
            )
            return doc
        except Exception as exc:
            logger.warning(f"weekend_briefing.get_latest failed: {exc}")
            return None

    # ── Generation ─────────────────────────────────────────────────
    async def generate(self, force: bool = False) -> Dict[str, Any]:
        """Build the briefing and persist it under the current ISO week id."""
        wid = _iso_week()
        if not force and self._db is not None:
            existing = self._db[self.COLLECTION].find_one(
                {"_id": wid}, projection={"_id": 0}
            )
            if existing:
                # Detect "has gameplan" across both old (str) and new
                # (dict {text, watches}) shapes for back-compat with any
                # cached docs from before the structured-output migration.
                gp = existing.get("gameplan")
                has_gp = (
                    bool(gp) and isinstance(gp, str)
                ) or (
                    isinstance(gp, dict) and bool(gp.get("text") or gp.get("watches"))
                )
                if has_gp:
                    logger.info(f"weekend_briefing: returning cached {wid}")
                    return existing

        logger.info(f"weekend_briefing: generating fresh briefing for {wid}")

        # Pull current open positions from Mongo (best-effort source).
        positions_held = self._fetch_open_position_symbols()

        # Run all data fetches in parallel where they're independent.
        sector_returns = _sector_returns_from_ib(self._db)
        closed_recap = _user_closed_positions_recap(self._db)
        # Per-watch P&L from last Sunday's gameplan (joined from
        # friday_close_snapshots). Empty if no prior briefing exists or
        # if the Friday cron hasn't fired yet for that week.
        prev_recap = self._build_previous_week_recap()

        # Earnings watchlist = positions ∪ default mega-caps.
        watchlist = list({*positions_held, *DEFAULT_EARNINGS_WATCHLIST})

        loop = asyncio.get_event_loop()
        market_news, earnings, macro, ipo_cal = await asyncio.gather(
            loop.run_in_executor(None, _fetch_finnhub_market_news),
            loop.run_in_executor(None, _fetch_finnhub_earnings_calendar, watchlist),
            loop.run_in_executor(None, _fetch_finnhub_economic_calendar),
            loop.run_in_executor(None, _fetch_finnhub_ipo_calendar),
        )

        catalysts = _filter_sector_catalysts(market_news)

        last_week_recap = {
            "sectors": sector_returns,
            "closed_trades": closed_recap.get("trades", []),
            "closed_summary": closed_recap.get("summary", {}),
            # Per-watch P&L from last Sunday's gameplan (joined from
            # friday_close_snapshots). Empty if no prior briefing exists
            # or if the Friday cron hasn't fired yet for that week.
            "gameplan_recap": prev_recap,
        }

        risk_map = _build_risk_map(positions_held, earnings, macro)

        # Synthesize the gameplan paragraph + structured watches from facts.
        # Last 4 weeks of grading flow into the prompt so the model can
        # self-correct against its own track record (e.g. dial down
        # thesis types it's been wrong about, lean into the winners).
        track_record = self.get_recent_track_record(weeks=4)
        facts: Dict[str, Any] = {
            "last_week_recap": last_week_recap,
            "earnings_calendar": earnings,
            "macro_calendar": macro,
            "sector_catalysts": catalysts,
            "positions_held": positions_held,
            "track_record": track_record,
        }
        gameplan_payload = await _synthesize_gameplan(facts)
        # Enrich watches with the IB close at briefing-generation time so
        # we can compute per-watch P&L when the Friday-close snapshot
        # fires next week.
        if isinstance(gameplan_payload, dict):
            gameplan_payload["watches"] = _enrich_watches_with_signal_prices(
                self._db, gameplan_payload.get("watches") or []
            )

        briefing: Dict[str, Any] = {
            "iso_week": wid,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "last_week_recap": last_week_recap,
            "major_news": market_news,
            "earnings_calendar": earnings,
            "macro_calendar": macro,
            "sector_catalysts": catalysts,
            "ipo_calendar": ipo_cal,
            # gameplan is now a structured object: {text, watches[]}.
            # Older cached docs that stored a raw string still render OK
            # because the frontend handles both shapes.
            "gameplan": gameplan_payload,
            "risk_map": risk_map,
            "positions_held": positions_held,
            "sources": {
                "sectors": "ib_historical_data",
                "news": "finnhub" if FINNHUB_API_KEY else "unavailable",
                "earnings": "finnhub" if FINNHUB_API_KEY else "unavailable",
                "macro": "finnhub" if FINNHUB_API_KEY else "unavailable",
                "ipo": "finnhub" if FINNHUB_API_KEY else "unavailable",
                "gameplan": "gpt-oss:120b-cloud" if gameplan_payload.get("text") else "skipped",
            },
        }

        # Persist (upsert by ISO week id).
        if self._db is not None:
            try:
                self._db[self.COLLECTION].update_one(
                    {"_id": wid}, {"$set": briefing}, upsert=True
                )
                logger.info(f"weekend_briefing: persisted {wid}")
            except Exception as exc:
                logger.warning(f"weekend_briefing: persistence failed: {exc}")

        return briefing

    # ── Helpers ─────────────────────────────────────────────────────
    def _fetch_open_position_symbols(self) -> List[str]:
        """Best-effort pull of currently open position symbols."""
        if self._db is None:
            return []
        try:
            for col in ("open_positions", "positions"):
                if col not in self._db.list_collection_names():
                    continue
                cursor = self._db[col].find(
                    {"status": {"$in": ["open", "live", None]}},
                    {"_id": 0, "symbol": 1},
                    limit=50,
                )
                syms = [d.get("symbol") for d in cursor if d.get("symbol")]
                if syms:
                    return list({s.upper() for s in syms})
            return []
        except Exception as exc:
            logger.warning(f"weekend_briefing._fetch_open_position_symbols failed: {exc}")
            return []

    # ── Friday close snapshot ───────────────────────────────────────
    def snapshot_friday_close(self) -> Dict[str, Any]:
        """Capture the Friday close price for each watch in the current
        week's gameplan and persist into `friday_close_snapshots`.
        Idempotent — re-running for the same ISO week upserts.

        Returns the snapshot doc shape:
            {iso_week, snapshot_at, watches: [
                {symbol, signal_price, friday_close, change_pct, thesis}
            ]}
        """
        if self._db is None:
            return {"success": False, "error": "db_unavailable"}

        wid = _iso_week()
        try:
            briefing = self._db[self.COLLECTION].find_one(
                {"_id": wid}, projection={"_id": 0}
            )
            if not briefing:
                return {"success": False, "iso_week": wid,
                        "error": "no_briefing_for_week"}

            gp = briefing.get("gameplan") or {}
            watches = gp.get("watches") if isinstance(gp, dict) else []
            if not watches:
                return {"success": False, "iso_week": wid,
                        "error": "no_watches_in_briefing"}

            entries: List[Dict[str, Any]] = []
            for w in watches:
                sym = (w.get("symbol") or "").upper()
                if not sym:
                    continue
                signal_price = w.get("signal_price")
                friday_close = _latest_ib_close(self._db, sym)
                change_pct: Optional[float] = None
                if (
                    signal_price not in (None, 0)
                    and friday_close is not None
                ):
                    try:
                        change_pct = round(
                            (float(friday_close) - float(signal_price))
                            / float(signal_price) * 100.0,
                            2,
                        )
                    except (ValueError, TypeError, ZeroDivisionError):
                        change_pct = None
                entries.append({
                    "symbol": sym,
                    "signal_price": signal_price,
                    "friday_close": round(friday_close, 4) if friday_close is not None else None,
                    "change_pct": change_pct,
                    "thesis": (w.get("thesis") or "")[:160],
                })

            snap = {
                "_id": wid,
                "iso_week": wid,
                "snapshot_at": datetime.now(timezone.utc).isoformat(),
                "watches": entries,
            }
            self._db[self.SNAPSHOT_COLLECTION].update_one(
                {"_id": wid}, {"$set": snap}, upsert=True,
            )
            logger.info(
                f"weekend_briefing.snapshot_friday_close: persisted {wid} "
                f"with {len(entries)} watches"
            )
            return {"success": True, **{k: v for k, v in snap.items() if k != "_id"}}
        except Exception as exc:
            logger.exception("snapshot_friday_close failed")
            return {"success": False, "iso_week": wid, "error": str(exc)}

    def get_friday_snapshot(self, iso_week: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if self._db is None:
            return None
        wid = iso_week or _iso_week()
        try:
            return self._db[self.SNAPSHOT_COLLECTION].find_one(
                {"_id": wid}, projection={"_id": 0}
            )
        except Exception as exc:
            logger.warning(f"get_friday_snapshot failed: {exc}")
            return None

    def get_recent_track_record(self, weeks: int = 4) -> Dict[str, Any]:
        """Aggregate the last `weeks` Friday-close snapshots into a
        compact track-record summary the LLM can self-correct against.

        Returns:
            {
              "weeks_graded": int,
              "total_calls": int,
              "wins": int,
              "losses": int,
              "win_rate": float,
              "avg_change_pct": float,
              "per_week": [{iso_week, wins, losses, avg_change_pct}],
              "best_call": {symbol, change_pct, iso_week},
              "worst_call": {symbol, change_pct, iso_week},
            }
        """
        if self._db is None:
            return {}
        try:
            cursor = self._db[self.SNAPSHOT_COLLECTION].find(
                {}, projection={"_id": 0},
                sort=[("snapshot_at", -1)], limit=max(1, min(int(weeks), 12)),
            )
            snaps = list(cursor)
            if not snaps:
                return {}
            all_graded: List[Dict[str, Any]] = []
            per_week = []
            for s in snaps:
                graded = [w for w in (s.get("watches") or [])
                          if w.get("change_pct") is not None]
                if not graded:
                    continue
                wins = sum(1 for w in graded if w["change_pct"] > 0)
                losses = sum(1 for w in graded if w["change_pct"] < 0)
                avg = round(sum(w["change_pct"] for w in graded) / len(graded), 2)
                per_week.append({
                    "iso_week": s.get("iso_week"),
                    "wins": wins,
                    "losses": losses,
                    "avg_change_pct": avg,
                })
                for w in graded:
                    all_graded.append({**w, "iso_week": s.get("iso_week")})
            if not all_graded:
                return {}
            wins = sum(1 for w in all_graded if w["change_pct"] > 0)
            losses = sum(1 for w in all_graded if w["change_pct"] < 0)
            avg = round(sum(w["change_pct"] for w in all_graded) / len(all_graded), 2)
            best = max(all_graded, key=lambda w: w["change_pct"])
            worst = min(all_graded, key=lambda w: w["change_pct"])
            return {
                "weeks_graded": len(per_week),
                "total_calls": len(all_graded),
                "wins": wins,
                "losses": losses,
                "win_rate": round(wins / max(1, len(all_graded)), 3),
                "avg_change_pct": avg,
                "per_week": per_week,
                "best_call": {"symbol": best.get("symbol"),
                              "change_pct": best.get("change_pct"),
                              "iso_week": best.get("iso_week")},
                "worst_call": {"symbol": worst.get("symbol"),
                               "change_pct": worst.get("change_pct"),
                               "iso_week": worst.get("iso_week")},
            }
        except Exception as exc:
            logger.warning(f"get_recent_track_record failed: {exc}")
            return {}

    def _build_previous_week_recap(self) -> Dict[str, Any]:
        """Return a compact recap of last Sunday's gameplan, joined with
        the friday_close_snapshot for that week. Empty dict when no
        prior data exists so the frontend can hide the section.
        """
        if self._db is None:
            return {}
        try:
            prev_wid = _previous_iso_week()
            snap = self.get_friday_snapshot(prev_wid)
            if not snap or not snap.get("watches"):
                return {}
            watches = snap["watches"]
            graded = [w for w in watches if w.get("change_pct") is not None]
            wins = sum(1 for w in graded if w["change_pct"] > 0)
            losses = sum(1 for w in graded if w["change_pct"] < 0)
            avg = (
                round(sum(w["change_pct"] for w in graded) / len(graded), 2)
                if graded else None
            )
            return {
                "iso_week": prev_wid,
                "snapshot_at": snap.get("snapshot_at"),
                "watches": watches,
                "summary": {
                    "graded": len(graded),
                    "wins": wins,
                    "losses": losses,
                    "avg_change_pct": avg,
                },
            }
        except Exception as exc:
            logger.warning(f"_build_previous_week_recap failed: {exc}")
            return {}



# Singleton accessor — pattern matches the other services in this codebase.
_singleton: Optional[WeekendBriefingService] = None


def get_weekend_briefing_service(db=None) -> Optional[WeekendBriefingService]:
    """Return (and lazily construct) the singleton service.

    Safe to call with `db=None` — returns the previously-constructed
    instance if one exists, so route handlers can grab it without
    knowing about the DB.
    """
    global _singleton  # noqa: PLW0603 — intentional module-level cache
    if _singleton is None and db is not None:
        _singleton = WeekendBriefingService(db)
    return _singleton
