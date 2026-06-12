#!/usr/bin/env python3
"""
diag_decision_audit.py — READ-ONLY full-system decision audit (2026-06-12)
===========================================================================
Operator question: "is the system making close-to-correct decisions —
regimes at all levels, the trades chosen in these regimes, how they were
scored vs others — and what holes/leaks remain before live money?"

Plus three specific complaints from today's session:
  • every position's thought stream spams "⚪ skipped — no intraday bars
    (snapshot unavailable)" mid-session,
  • all 14 open positions show the AMBER quote-freshness chip,
  • zero scalps by 1pm, and charts only scroll back a few days.

SECTIONS
  1. DATA PIPELINE — snapshot blackout forensics + collector cadence
  2. REGIME — market_regime_state / FTD / snapshots timeline vs reality
  3. TRADES — today's + open positions: geometry, HSBG stamps, reach ratios
  4. SCORING — TQS taken-vs-rejected, rejection reasons, reach-gate events
  5. SCALPS — why none fired
  6. CHART DEPTH — how far back intraday bars actually exist per symbol
  7. EXPOSURE — direction skew, gross/net $, total open risk
  8. VERDICT — consolidated FLAG list

READ-ONLY: no writes, no API mutations. Safe during market hours.
Run from repo root:  .venv/bin/python /tmp/diag_decision_audit.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    from pymongo import MongoClient
except ImportError:
    print("FATAL: pymongo not available"); sys.exit(1)

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
API = "http://127.0.0.1:8001"

FLAGS: list = []


def flag(severity, text):
    FLAGS.append((severity, text))
    print(f"   {severity} {text}")


def hr(title):
    print("\n" + "═" * 74)
    print(f"  {title}")
    print("═" * 74)


def _load_env():
    # backend/.env from repo root or cwd
    for cand in (".", "backend", "../backend"):
        p = os.path.join(cand, ".env")
        if os.path.exists(p):
            for line in open(p):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _parse_ts(v):
    """Best-effort: ISO string / datetime / unix → aware UTC datetime."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(float(v), tz=UTC)
        except Exception:
            return None
    try:
        s = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except Exception:
        return None


def _age_min(dt):
    if not dt:
        return None
    return round((datetime.now(UTC) - dt).total_seconds() / 60.0, 1)


def _get(url, timeout=15):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"_error": str(e)}


def main():
    _load_env()
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    if not mongo_url:
        print("FATAL: MONGO_URL not found (run from repo root)"); sys.exit(1)
    db = MongoClient(mongo_url)[db_name]

    now_et = datetime.now(ET)
    sod_et = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    sod_utc = sod_et.astimezone(UTC)
    print(f"diag_decision_audit — {now_et:%Y-%m-%d %H:%M ET}  (db={db_name})")

    # Thought collection name discovery
    coll_names = set(db.list_collection_names())
    thought_coll = None
    for cand in ("sentcom_thoughts", "thoughts", "bot_thoughts"):
        if cand in coll_names:
            thought_coll = cand
            break

    # ────────────────────────────────────────────────────────────────
    hr("1. DATA PIPELINE — snapshot blackout forensics")
    # ────────────────────────────────────────────────────────────────
    # Open + today's trade symbols are the focus set
    open_trades = list(db["bot_trades"].find(
        {"status": {"$in": ["open", "active", "partial", "pending"]}}, {"_id": 0}))
    focus = sorted({t.get("symbol", "") for t in open_trades if t.get("symbol")} |
                   {"SPY", "QQQ", "IWM", "ADBE"})
    print(f"focus symbols ({len(focus)}): {', '.join(focus)}")

    if thought_coll:
        # blackout timeline
        q = {"text": {"$regex": "no intraday bars"}}
        rows = list(db[thought_coll].find(q, {"_id": 0, "text": 1, "ts": 1,
                                              "created_at": 1, "timestamp": 1,
                                              "symbol": 1}).sort("_id", -1).limit(8000))
        today_rows = []
        for r in rows:
            ts = _parse_ts(r.get("ts") or r.get("created_at") or r.get("timestamp"))
            if ts and ts >= sod_utc:
                today_rows.append((ts, r.get("symbol", "?")))
        by_hour = Counter(ts.astimezone(ET).strftime("%H:00") for ts, _ in today_rows)
        syms = {s for _, s in today_rows}
        print(f"'no intraday bars' skips TODAY: {len(today_rows)} events, "
              f"{len(syms)} distinct symbols")
        if today_rows:
            first = min(ts for ts, _ in today_rows).astimezone(ET)
            last = max(ts for ts, _ in today_rows).astimezone(ET)
            print(f"   window: {first:%H:%M ET} → {last:%H:%M ET}")
            print("   by hour:", dict(sorted(by_hour.items())))
            if len(today_rows) > 200:
                flag("🔴", f"SNAPSHOT BLACKOUT: {len(today_rows)} no-intraday-bars skips "
                           f"across {len(syms)} symbols today — scanner mostly blind")
    else:
        print("   (no thought collection found)")

    # freshest 5m bars vs the 30s snapshot gate
    hist = db["ib_historical_data"]
    print(f"\n   {'symbol':<7} {'5m fresh(min)':<14} {'5m today':<9} "
          f"{'1m fresh(min)':<14} {'5m earliest':<12} {'5m total':<8}")
    stale_5m = 0
    for sym in focus:
        newest5 = hist.find_one({"symbol": sym, "bar_size": "5 mins"},
                                {"_id": 0, "date": 1}, sort=[("date", -1)])
        oldest5 = hist.find_one({"symbol": sym, "bar_size": "5 mins"},
                                {"_id": 0, "date": 1}, sort=[("date", 1)])
        n5_total = hist.count_documents({"symbol": sym, "bar_size": "5 mins"})
        n5_today = hist.count_documents({"symbol": sym, "bar_size": "5 mins",
                                         "date": {"$gte": sod_utc.isoformat()}})
        newest1 = hist.find_one({"symbol": sym, "bar_size": "1 min"},
                                {"_id": 0, "date": 1}, sort=[("date", -1)])
        a5 = _age_min(_parse_ts((newest5 or {}).get("date")))
        a1 = _age_min(_parse_ts((newest1 or {}).get("date")))
        e5 = str((oldest5 or {}).get("date", "—"))[:10]
        if a5 is not None and a5 > 15:
            stale_5m += 1
        print(f"   {sym:<7} {str(a5):<14} {n5_today:<9} {str(a1):<14} {e5:<12} {n5_total:<8}")
    if stale_5m:
        flag("🔴", f"{stale_5m}/{len(focus)} focus symbols have 5-min bars >15min stale "
                   f"— turbo collectors starved or down (scanner gate is 30s + live-quote check)")

    # live_bar_cache freshness
    if "live_bar_cache" in coll_names:
        lbc = db["live_bar_cache"]
        sample = lbc.find_one({}, sort=[("_id", -1)])
        if sample:
            ts = _parse_ts(sample.get("updated_at") or sample.get("ts") or
                           sample.get("timestamp") or sample.get("date"))
            print(f"\n   live_bar_cache newest row age: {_age_min(ts)} min "
                  f"(rows={lbc.estimated_document_count()})")
            if _age_min(ts) and _age_min(ts) > 10:
                flag("🟡", f"live_bar_cache newest row is {_age_min(ts)}min old — pusher "
                           f"live-bar overlay also stale")

    # collector write cadence today (per bar_size per hour) — starvation windows
    print("\n   collector writes today (per bar_size per ET hour):")
    try:
        pipe = [
            {"$match": {"collected_at": {"$gte": sod_utc.isoformat()}}},
            {"$group": {"_id": {"bs": "$bar_size",
                                "h": {"$substr": ["$collected_at", 11, 2]}},
                        "n": {"$sum": 1}}},
        ]
        rows = list(hist.aggregate(pipe, allowDiskUse=True))
        table = defaultdict(dict)
        for r in rows:
            table[r["_id"]["bs"]][r["_id"]["h"]] = r["n"]
        for bs in sorted(table):
            hours = " ".join(f"{h}:{n}" for h, n in sorted(table[bs].items()))
            print(f"     {bs:<8} {hours}")
        if not rows:
            print("     (no collected_at field or no writes today)")
            flag("🟡", "no collector writes stamped today via collected_at — "
                       "either field missing or collectors idle")
    except Exception as e:
        print(f"     (cadence aggregation failed: {e})")

    # ────────────────────────────────────────────────────────────────
    hr("2. REGIME — all levels vs reality")
    # ────────────────────────────────────────────────────────────────
    for cname in ("market_regime_state", "market_regime_ftd"):
        if cname in coll_names:
            doc = db[cname].find_one({}, {"_id": 0}, sort=[("_id", -1)])
            if doc:
                slim = {k: v for k, v in list(doc.items())[:14]}
                print(f"   {cname}: {json.dumps(slim, default=str)[:500]}")
    if "regime_snapshots" in coll_names:
        snaps = list(db["regime_snapshots"].find(
            {"ts": {"$gte": sod_utc}}, {"_id": 0}).sort("ts", 1))
        if not snaps:
            snaps = list(db["regime_snapshots"].find(
                {}, {"_id": 0}).sort("ts", -1).limit(5))[::-1]
            print("   (no regime transitions persisted TODAY — showing last 5 overall)")
        print(f"   regime transitions ({len(snaps)}):")
        for s in snaps[-12:]:
            ts = _parse_ts(s.get("ts"))
            print(f"     {ts.astimezone(ET):%H:%M ET} → {s.get('regime'):<18} "
                  f"agree={s.get('agreement')} div={s.get('divergence_flag')} "
                  f"votes ↑{s.get('uptrend_votes')}/↓{s.get('downtrend_votes')}")
    # reality check from index bars
    print("\n   index reality check (today's 5m bars):")
    for sym in ("SPY", "QQQ", "IWM"):
        bars = list(hist.find({"symbol": sym, "bar_size": "5 mins",
                               "date": {"$gte": sod_utc.isoformat()}},
                              {"_id": 0, "open": 1, "high": 1, "low": 1,
                               "close": 1, "date": 1}).sort("date", 1))
        if not bars:
            print(f"     {sym}: NO BARS TODAY")
            continue
        o = float(bars[0]["open"]); c = float(bars[-1]["close"])
        hi = max(float(b["high"]) for b in bars); lo = min(float(b["low"]) for b in bars)
        print(f"     {sym}: {len(bars)} bars · open {o:.2f} → last {c:.2f} "
              f"({(c-o)/o*100:+.2f}%) · range {(hi-lo)/o*100:.2f}% · "
              f"last bar {_age_min(_parse_ts(bars[-1]['date']))}min old")

    # ────────────────────────────────────────────────────────────────
    hr("3. TRADES — geometry, HSBG stamps, reach ratios")
    # ────────────────────────────────────────────────────────────────
    today_trades = list(db["bot_trades"].find(
        {"$or": [{"created_at": {"$gte": sod_utc.isoformat()}},
                 {"executed_at": {"$gte": sod_utc.isoformat()}}]}, {"_id": 0}))
    seen_ids = {t.get("id") for t in today_trades}
    all_rows = today_trades + [t for t in open_trades if t.get("id") not in seen_ids]
    print(f"   today's trades: {len(today_trades)} · open (incl. older): {len(open_trades)}")

    adv = db["symbol_adv_cache"]
    style_hold = {"scalp": 60, "intraday": 240, "trade_2_hold": 240, "": 240,
                  "multi_day": 5*390, "swing": 10*390, "position": 30*390,
                  "investment": 90*390}
    pre_v325_open = 0
    unreachable_open = 0
    print(f"\n   {'sym':<6}{'dir':<6}{'style':<11}{'setup':<22}{'TQS':<5}"
          f"{'stop%':<7}{'PT1%':<7}{'PTn%':<7}{'reach':<7}{'hsbg':<5}{'regime':<14}{'status'}")
    for t in sorted(all_rows, key=lambda x: str(x.get("created_at", ""))):
        sym = t.get("symbol", "?")
        e = float(t.get("entry_price") or 0)
        sl = float(t.get("stop_price") or 0)
        tps = [float(x) for x in (t.get("target_prices") or []) if x]
        if not e:
            continue
        stop_pct = abs(e - sl) / e * 100 if sl else None
        pt1_pct = abs(tps[0] - e) / e * 100 if tps else None
        ptn_pct = abs(tps[-1] - e) / e * 100 if tps else None
        style = (t.get("trade_style") or "").lower()
        hsbg = ((t.get("entry_context") or {}).get("multipliers") or {}).get("hsbg")
        # recompute reach ratio from current adv cache
        ratio = None
        doc = adv.find_one({"symbol": sym}, {"atr_pct": 1, "_id": 0})
        if doc and doc.get("atr_pct") and pt1_pct:
            atr_pct = float(doc["atr_pct"]) * 100
            hold = style_hold.get(style, 240)
            envelope_pct = atr_pct * ((hold / 390.0) ** 0.5)
            ratio = pt1_pct / envelope_pct if envelope_pct > 0 else None
        is_open = t.get("status") in ("open", "active", "partial", "pending")
        if is_open and not hsbg:
            pre_v325_open += 1
        if is_open and ratio and ratio > 1.5:
            unreachable_open += 1
        print(f"   {sym:<6}{(t.get('direction') or '?'):<6}{style[:10]:<11}"
              f"{(t.get('setup_type') or '?')[:21]:<22}"
              f"{str(t.get('tqs_score', '—')):<5}"
              f"{f'{stop_pct:.2f}' if stop_pct else '—':<7}"
              f"{f'{pt1_pct:.2f}' if pt1_pct else '—':<7}"
              f"{f'{ptn_pct:.2f}' if ptn_pct else '—':<7}"
              f"{f'{ratio:.2f}x' if ratio else '—':<7}"
              f"{'✓' if hsbg else '✗':<5}"
              f"{(t.get('market_regime') or '—')[:13]:<14}"
              f"{t.get('status')}")
    if pre_v325_open:
        flag("🔴", f"{pre_v325_open} OPEN positions carry PRE-v325 geometry (no hsbg stamp) "
                   f"— their PTs were sized off daily ATR and are likely unreachable. "
                   f"Decide: flatten, or re-bracket to v325 geometry.")
    if unreachable_open:
        flag("🔴", f"{unreachable_open} OPEN positions have PT1 > 1.5× reach envelope "
                   f"RIGHT NOW — mathematically configured to fail.")

    # post-restart sanity: any trade WITH hsbg stamp today?
    stamped = [t for t in today_trades if ((t.get("entry_context") or {})
               .get("multipliers") or {}).get("hsbg")]
    print(f"\n   trades with v325 hsbg stamps today: {len(stamped)}")
    if today_trades and not stamped:
        flag("🟡", "NO trade today carries an hsbg stamp — if any fired AFTER the "
                   "restart, v325 isn't actually in the running process")
    for t in stamped[:5]:
        h = t["entry_context"]["multipliers"]["hsbg"]
        print(f"     {t.get('symbol')}: style={h.get('style')} frac={h.get('frac')} "
              f"atr_src={h.get('atr_source')} pt1_env={h.get('pt1_env_ratio')}")

    # ────────────────────────────────────────────────────────────────
    hr("4. SCORING — taken vs rejected")
    # ────────────────────────────────────────────────────────────────
    scores = [t.get("tqs_score") for t in all_rows if t.get("tqs_score")]
    if scores:
        print(f"   taken-trade TQS: n={len(scores)} min={min(scores)} "
              f"max={max(scores)} spread={max(scores)-min(scores)}")
        if max(scores) - min(scores) <= 12:
            flag("🟡", f"TQS on taken trades spans only {min(scores)}–{max(scores)} — "
                       f"score is barely separating winners from average (rescale parked "
                       f"on data sufficiency, but watch it)")
    if "rejection_events" in coll_names:
        rej = list(db["rejection_events"].find(
            {"$or": [{"created_at": {"$gte": sod_utc.isoformat()}},
                     {"ts": {"$gte": sod_utc}}]},
            {"_id": 0, "reason_code": 1, "symbol": 1, "setup_type": 1}))
        cnt = Counter(r.get("reason_code", "?") for r in rej)
        print(f"   rejections today: {len(rej)}")
        for code, n in cnt.most_common(15):
            print(f"     {code:<36} {n}")
        gate = [r for r in rej if r.get("reason_code") == "hsbg_pt_unreachable"]
        if gate:
            print(f"   reach-gate blocks: {len(gate)} → "
                  f"{', '.join(sorted({g.get('symbol','?') for g in gate})[:10])}")
    if thought_coll:
        warns = db[thought_coll].count_documents(
            {"text": {"$regex": "reach"}, })
        print(f"   thoughts mentioning 'reach' (all time, quick count): {warns}")

    # ────────────────────────────────────────────────────────────────
    hr("5. SCALPS — why none fired")
    # ────────────────────────────────────────────────────────────────
    scalp_setups = ["scalp", "nine_ema_scalp", "9_ema_scalp", "spencer_scalp",
                    "abc_scalp", "vwap_continuation", "or_break"]
    scalp_trades = [t for t in today_trades
                    if (t.get("trade_style") == "scalp"
                        or any(s in str(t.get("setup_type", "")).lower()
                               for s in ("scalp",)))]
    print(f"   scalp trades today: {len(scalp_trades)}")
    if "rejection_events" in coll_names:
        rej = list(db["rejection_events"].find(
            {"$or": [{"created_at": {"$gte": sod_utc.isoformat()}},
                     {"ts": {"$gte": sod_utc}}]},
            {"_id": 0, "reason_code": 1, "setup_type": 1, "symbol": 1}))
        scalp_rej = [r for r in rej if any(
            s in str(r.get("setup_type", "")).lower() for s in ("scalp", "9_ema", "abc"))]
        cnt = Counter(r.get("reason_code", "?") for r in scalp_rej)
        print(f"   scalp-setup rejections today: {len(scalp_rej)} → {dict(cnt.most_common(8))}")
        if not scalp_rej and not scalp_trades:
            flag("🔴", "ZERO scalp trades AND zero scalp rejections today — scalp "
                       "detectors never even evaluated (consistent with the snapshot "
                       "blackout: no snapshot → detectors never run → no scalps)")
    # daily-bar poisoning check (v323b regression watch)
    today_str = now_et.strftime("%Y-%m-%d")
    poisoned = hist.count_documents({"bar_size": "1 day", "date": today_str})
    print(f"   in-progress daily bars stored for {today_str}: {poisoned} "
          f"(v323b expects 0 before the close)")
    if poisoned > 0 and now_et.hour < 16:
        flag("🟡", f"{poisoned} in-progress daily bars present for today — v323b "
                   f"guard not fully holding (RVOL may be poisoned again)")

    # ────────────────────────────────────────────────────────────────
    hr("6. CHART DEPTH — intraday history per symbol (the ADBE question)")
    # ────────────────────────────────────────────────────────────────
    print("   (chart scroll-back stops at the EARLIEST collected bar — that's "
        "a data-depth wall, not a UI bug, if dates below are recent)")
    for sym in ("ADBE", "SPY", "QQQ"):
        for bs in ("5 mins", "1 min"):
            oldest = hist.find_one({"symbol": sym, "bar_size": bs},
                                   {"_id": 0, "date": 1}, sort=[("date", 1)])
            n = hist.count_documents({"symbol": sym, "bar_size": bs})
            print(f"   {sym:<6} {bs:<8} earliest={str((oldest or {}).get('date','—'))[:16]:<18} total={n}")

    # ────────────────────────────────────────────────────────────────
    hr("7. EXPOSURE — concentration & open risk")
    # ────────────────────────────────────────────────────────────────
    longs = [t for t in open_trades if (t.get("direction") or "").lower() == "long"]
    shorts = [t for t in open_trades if (t.get("direction") or "").lower() == "short"]
    gross = net = risk_total = 0.0
    for t in open_trades:
        e = float(t.get("entry_price") or 0); sh = abs(float(t.get("shares") or 0))
        sl = float(t.get("stop_price") or 0)
        notional = e * sh
        gross += notional
        net += notional if (t.get("direction") or "").lower() == "long" else -notional
        if sl and e:
            risk_total += abs(e - sl) * sh
    print(f"   open: {len(open_trades)} ({len(longs)} long / {len(shorts)} short)")
    print(f"   gross exposure ≈ ${gross:,.0f} · net ≈ ${net:,.0f} "
          f"({'SHORT' if net < 0 else 'LONG'} tilt)")
    print(f"   total open risk (Σ |entry−SL|×shares) ≈ ${risk_total:,.0f}")
    if len(open_trades) >= 8 and (len(shorts) >= 0.8 * len(open_trades)
                                  or len(longs) >= 0.8 * len(open_trades)):
        flag("🟡", f"direction concentration: {len(shorts)} short vs {len(longs)} long "
                   f"— acceptable ONLY if regime is decisively one-sided; cross-check §2")
    conflict = [t for t in open_trades if t.get("setup_type") == "reconciled_orphan"
                or "reconcil" in str(t.get("notes", "")).lower()]
    if conflict:
        flag("🟡", f"{len(conflict)} adopted/reconciled positions open "
                   f"({', '.join(t.get('symbol','?') for t in conflict)}) — the SPY one "
                   f"shows ⚠ CONFLICT (bot's own verdicts were REJECT); needs a manual decision")

    # ────────────────────────────────────────────────────────────────
    hr("8. LIVE ENDPOINTS (best-effort)")
    # ────────────────────────────────────────────────────────────────
    for path in ("/api/scanner/in-play-health",
                 "/api/trading-bot/audit-stops",
                 "/api/sentcom/chart/reach-meta?symbol=SPY"):
        resp = _get(f"{API}{path}")
        print(f"   GET {path}\n     → {json.dumps(resp, default=str)[:400]}")

    # ────────────────────────────────────────────────────────────────
    hr("VERDICT — consolidated flags")
    # ────────────────────────────────────────────────────────────────
    if not FLAGS:
        print("   ✅ no flags raised")
    for sev, text in FLAGS:
        print(f"   {sev} {text}")
    print("\ndone (read-only — nothing was modified)")


if __name__ == "__main__":
    main()
