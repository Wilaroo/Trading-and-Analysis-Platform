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
    "relevant. Avoid filler and disclaimers. Output 4-6 short paragraphs "
    "covering: market backdrop · top 3-5 watches with thesis · key levels "
    "if known · risk + what would invalidate the view."
)


async def _synthesize_gameplan(facts: Dict[str, Any]) -> str:
    """Ask the local LLM to compose the gameplan paragraph from the facts."""
    try:
        from agents.llm_provider import get_llm_provider
        provider = get_llm_provider()
    except Exception as exc:
        logger.warning(f"weekend_briefing: LLM unavailable ({exc}) — skipping gameplan")
        return ""
    if provider is None:
        return ""

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

    prompt = "\n".join([
        "Compose the weekly gameplan note based on these facts:",
        *summary_lines,
        "",
        "Audience: a discretionary day-trading operator who runs an AI bot.",
        "Format: 4-6 short paragraphs. End with a one-line risk caveat.",
    ])

    try:
        resp = await provider.generate(
            prompt=prompt,
            system_prompt=_GAMEPLAN_SYSTEM_PROMPT,
            temperature=0.5,
            max_tokens=900,
        )
        if not getattr(resp, "success", False):
            logger.warning(f"weekend_briefing LLM call failed: {getattr(resp, 'error', 'unknown')}")
            return ""
        return (resp.content or "").strip()
    except Exception as exc:
        logger.warning(f"weekend_briefing LLM call exception: {exc}")
        return ""


# ──────────────────────────────────────────────────────────────────────
# Top-level orchestrator
# ──────────────────────────────────────────────────────────────────────


class WeekendBriefingService:
    """Generates and caches the Sunday-afternoon weekly briefing."""

    COLLECTION = "weekend_briefings"

    def __init__(self, db):
        self._db = db
        if db is not None:
            try:
                db[self.COLLECTION].create_index([("_id", 1)])
                db[self.COLLECTION].create_index([("generated_at", -1)])
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
            if existing and existing.get("gameplan"):
                logger.info(f"weekend_briefing: returning cached {wid}")
                return existing

        logger.info(f"weekend_briefing: generating fresh briefing for {wid}")

        # Pull current open positions from Mongo (best-effort source).
        positions_held = self._fetch_open_position_symbols()

        # Run all data fetches in parallel where they're independent.
        sector_returns = _sector_returns_from_ib(self._db)
        closed_recap = _user_closed_positions_recap(self._db)

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
        }

        risk_map = _build_risk_map(positions_held, earnings, macro)

        # Synthesize the gameplan paragraph from facts.
        facts: Dict[str, Any] = {
            "last_week_recap": last_week_recap,
            "earnings_calendar": earnings,
            "macro_calendar": macro,
            "sector_catalysts": catalysts,
            "positions_held": positions_held,
        }
        gameplan_text = await _synthesize_gameplan(facts)

        briefing: Dict[str, Any] = {
            "iso_week": wid,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "last_week_recap": last_week_recap,
            "major_news": market_news,
            "earnings_calendar": earnings,
            "macro_calendar": macro,
            "sector_catalysts": catalysts,
            "ipo_calendar": ipo_cal,
            "gameplan": gameplan_text,
            "risk_map": risk_map,
            "positions_held": positions_held,
            "sources": {
                "sectors": "ib_historical_data",
                "news": "finnhub" if FINNHUB_API_KEY else "unavailable",
                "earnings": "finnhub" if FINNHUB_API_KEY else "unavailable",
                "macro": "finnhub" if FINNHUB_API_KEY else "unavailable",
                "ipo": "finnhub" if FINNHUB_API_KEY else "unavailable",
                "gameplan": "gpt-oss:120b-cloud" if gameplan_text else "skipped",
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
