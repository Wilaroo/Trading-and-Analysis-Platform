#!/usr/bin/env python3
"""
diag_bot_vs_ib_today.py  —  READ-ONLY drift forensics (v19.34.233-diag)

Compares what the BOT *thinks* it's holding / traded today against the ACTUAL
positions and executions at Interactive Brokers. NOTHING is closed, cancelled,
reconciled or written — this only READS:

  • GET /api/trading-bot/positions/truth-diff   (live _open_trades vs IB positions)
  • GET /api/trading-bot/trades/open            (bot's tracked open trades + entered_by)
  • GET /api/trading-bot/positions              (executor's broker-position view)
  • GET /api/trading-bot/share-drift-status     (bot's own drift detector)
  • Mongo  ib_executions  (today's real IB fills)   — root-cause origin
  • Mongo  bot_trades     (today's bot-recorded fills)

Run on the DGX:
    .venv/bin/python diag_bot_vs_ib_today.py
    .venv/bin/python diag_bot_vs_ib_today.py --symbol HOOD     # focus one name
    DIAG_API=http://localhost:8001 .venv/bin/python diag_bot_vs_ib_today.py
"""
import json
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

API = os.environ.get("DIAG_API", "http://localhost:8001")

# ── tiny ANSI helpers ──────────────────────────────────────────────────────
def _c(s, code):
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else str(s)

def red(s):    return _c(s, "1;31")
def grn(s):    return _c(s, "1;32")
def yel(s):    return _c(s, "1;33")
def cyn(s):    return _c(s, "1;36")
def dim(s):    return _c(s, "2")
def bold(s):   return _c(s, "1")

WARN = red("⚠")
OK = grn("✓")


# ── http (stdlib only) ─────────────────────────────────────────────────────
def get(path, timeout=25):
    try:
        req = urllib.request.Request(API + path, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"__error__": str(e)}


# ── env / mongo ────────────────────────────────────────────────────────────
def load_env():
    env = {}
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "backend", ".env"), "backend/.env", "/app/backend/.env"):
        if os.path.exists(p):
            for line in open(p):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            break
    return env


def mongo_db():
    try:
        from pymongo import MongoClient
    except Exception as e:
        print(red(f"pymongo not importable: {e} — Mongo sections skipped"))
        return None
    env = load_env()
    url = env.get("MONGO_URL") or os.environ.get("MONGO_URL")
    name = env.get("DB_NAME") or os.environ.get("DB_NAME")
    if not url or not name:
        print(red("MONGO_URL / DB_NAME not found — Mongo sections skipped"))
        return None
    try:
        return MongoClient(url, serverSelectionTimeoutMS=4000)[name]
    except Exception as e:
        print(red(f"Mongo connect failed: {e}"))
        return None


def et_today_start_utc():
    if ZoneInfo:
        et = ZoneInfo("America/New_York")
        now_et = datetime.now(et)
        start = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.astimezone(timezone.utc)
    return datetime.now(timezone.utc) - timedelta(hours=16)


def _norm_side(s):
    s = str(s or "").upper()
    if s in ("BUY", "BOT", "B", "LONG"):
        return "BUY"
    if s in ("SELL", "SLD", "S", "SHORT"):
        return "SELL"
    return s


def _signed(side, qty):
    return qty if side == "BUY" else -qty


def sgn_str(n):
    n = int(n)
    if n > 0:
        return grn(f"+{n}")
    if n < 0:
        return red(f"{n}")
    return dim("0")


# ── sections ───────────────────────────────────────────────────────────────
def hdr(title):
    print()
    print(bold(cyn("═" * 78)))
    print(bold(cyn(f" {title}")))
    print(bold(cyn("═" * 78)))


def section_truth_diff(focus):
    hdr("1) LIVE TRUTH-DIFF  —  bot._open_trades  vs  IB positions (authoritative now)")
    td = get("/api/trading-bot/positions/truth-diff")
    if "__error__" in td:
        print(red(f"  endpoint error: {td['__error__']}"))
        return {}
    in_sync = td.get("in_sync")
    print(f"  {'IN SYNC ' + OK if in_sync else 'OUT OF SYNC ' + WARN}    "
          f"bot_count={td.get('bot_count')}  ib_count={td.get('ib_count')}  "
          f"as_of={td.get('as_of')}")

    def _flt(rows):
        if focus:
            return [r for r in rows if (r.get('symbol') or '').upper() == focus]
        return rows

    bo = _flt(td.get("bot_only", []))
    io = _flt(td.get("ib_only", []))
    fl = _flt(td.get("direction_flipped", []))
    sm = _flt(td.get("share_mismatch", []))

    if bo:
        print(yel("\n  BOT-ONLY (bot tracks it, IB has NO position — phantom / already exited at IB):"))
        for r in bo:
            print(f"    {WARN} {r['symbol']:<6} bot {r.get('direction','?'):<5} {r.get('shares')}sh")
    if io:
        print(yel("\n  IB-ONLY (IB holds it, bot is NOT tracking — orphan / unrecorded fill):"))
        for r in io:
            print(f"    {WARN} {r['symbol']:<6} IB holds {r.get('shares')}sh")
    if fl:
        print(red("\n  DIRECTION FLIPPED (bot side != IB side — DANGER, position inverted):"))
        for r in fl:
            print(f"    {WARN} {r['symbol']:<6} bot={r.get('bot_side')} {r.get('bot_shares')}sh  "
                  f"IB={r.get('ib_side')} {r.get('ib_shares')}sh")
    if sm:
        print(yel("\n  SHARE MISMATCH (same direction, different size):"))
        for r in sm:
            print(f"    {WARN} {r['symbol']:<6} bot={r.get('bot_shares')}sh  IB={r.get('ib_shares')}sh")
    if not (bo or io or fl or sm):
        print(grn("  No live position discrepancies."))
    return td


def section_bot_open(focus):
    hdr("2) BOT TRACKED OPEN TRADES  (_open_trades — watch entered_by + dup (sym,dir))")
    data = get("/api/trading-bot/trades/open")
    if isinstance(data, dict) and "__error__" in data:
        print(red(f"  endpoint error: {data['__error__']}"))
        return
    items = data if isinstance(data, list) else next(
        (v for v in data.values() if isinstance(v, list)), []) if isinstance(data, dict) else []
    if focus:
        items = [t for t in items if (t.get('symbol') or '').upper() == focus]
    if not items:
        print(dim("  (no open trades tracked)"))
        return
    seen = defaultdict(int)
    for t in items:
        sym = (t.get("symbol") or "").upper()
        side = t.get("side") or t.get("direction") or "?"
        seen[(sym, str(side))] += 1
    for t in sorted(items, key=lambda x: (x.get("symbol") or "")):
        sym = (t.get("symbol") or "").upper()
        side = str(t.get("side") or t.get("direction") or "?")
        sh = t.get("shares") or t.get("remaining_shares") or 0
        eb = t.get("entered_by", "?")
        eb_s = red(eb) if str(eb).startswith("reconciled") else eb
        dup = red("  ← DUP (sym,dir)") if seen[(sym, side)] > 1 else ""
        entry = t.get("entry_price") or t.get("avg_price") or 0
        tid = t.get("trade_id") or t.get("id") or "?"
        print(f"    {sym:<6} {side:<5} {str(sh):>6}sh @ {entry:<9} entered_by={eb_s:<22} "
              f"{dim(str(tid)[:18])}{dup}")


def section_broker_positions(focus):
    hdr("3) IB BROKER POSITIONS  (executor view — independent of truth-diff)")
    data = get("/api/trading-bot/positions")
    if isinstance(data, dict) and "__error__" in data:
        print(red(f"  endpoint error: {data['__error__']}"))
        return
    positions = data.get("positions") if isinstance(data, dict) else data
    positions = positions or []
    if focus:
        positions = [p for p in positions if (p.get('symbol') or '').upper() == focus]
    if not positions:
        print(dim("  (no broker positions returned)"))
        return
    for p in sorted(positions, key=lambda x: (x.get("symbol") or "")):
        sym = (p.get("symbol") or "").upper()
        qty = p.get("position", p.get("shares", p.get("qty", 0)))
        avg = p.get("avg_cost", p.get("avgCost", p.get("avg_price", 0)))
        print(f"    {sym:<6} {sgn_str(qty)}sh  avg={avg}")


def section_fills_recon(db, td, focus):
    hdr("4) TODAY'S FILLS RECONCILIATION  (root cause: IB executions vs bot record)")
    if db is None:
        print(dim("  (Mongo unavailable — skipped)"))
        return
    cut = et_today_start_utc()
    cut_iso = cut.isoformat()
    print(dim(f"  window: since {cut_iso}  (ET session start)"))

    # --- IB executions today ---
    q = {"$or": [{"time": {"$gte": cut_iso}}, {"timestamp": {"$gte": cut_iso}}]}
    if focus:
        q["symbol"] = focus
    try:
        execs = list(db["ib_executions"].find(q, {"_id": 0}))
    except Exception as e:
        print(red(f"  ib_executions read failed: {e}"))
        execs = []
    ib_net = defaultdict(int)
    ib_cnt = defaultdict(int)
    ib_fills_by_sym = defaultdict(list)
    for f in execs:
        sym = (f.get("symbol") or "").upper()
        if not sym:
            continue
        side = _norm_side(f.get("side") or f.get("action"))
        qty = int(abs(float(f.get("shares") or f.get("qty") or 0)))
        if qty <= 0:
            continue
        ib_net[sym] += _signed(side, qty)
        ib_cnt[sym] += 1
        ib_fills_by_sym[sym].append(
            (str(f.get("time") or f.get("timestamp") or "")[:19], side, qty,
             f.get("price") or f.get("avg_price")))
    print(f"  IB executions today: {len(execs)} fills across {len(ib_net)} symbols")

    # --- bot_trades today ---
    try:
        bot_rows = list(db["bot_trades"].find({}, {
            "_id": 0, "symbol": 1, "side": 1, "direction": 1, "shares": 1,
            "status": 1, "entered_by": 1, "entry_time_ms": 1, "executed_at": 1,
            "closed_at": 1, "created_at": 1, "entry_price": 1, "trade_id": 1, "id": 1,
        }))
    except Exception as e:
        print(red(f"  bot_trades read failed: {e}"))
        bot_rows = []

    cut_ms = int(cut.timestamp() * 1000)

    def _is_today(r):
        for k in ("executed_at", "closed_at", "created_at"):
            v = r.get(k)
            if isinstance(v, str) and v >= cut_iso:
                return True
        ems = r.get("entry_time_ms")
        if isinstance(ems, (int, float)) and ems >= cut_ms:
            return True
        return False

    bot_today = [r for r in bot_rows if _is_today(r) or str(r.get("status")) == "open"]
    if focus:
        bot_today = [r for r in bot_today if (r.get("symbol") or "").upper() == focus]
    bot_open_net = defaultdict(int)   # tracked exposure from OPEN rows
    bot_today_cnt = defaultdict(int)
    for r in bot_today:
        sym = (r.get("symbol") or "").upper()
        if not sym:
            continue
        bot_today_cnt[sym] += 1
        if str(r.get("status")) == "open":
            side = _norm_side(r.get("side") or r.get("direction"))
            bot_open_net[sym] += _signed(side, int(r.get("shares") or 0))
    print(f"  bot_trades today/open: {len(bot_today)} rows across {len(bot_today_cnt)} symbols")

    # --- truth-diff signed maps (live authoritative) ---
    bot_signed, ib_signed = {}, {}
    for r in td.get("bot_only", []):
        s = r["symbol"].upper()
        bot_signed[s] = (-1 if r.get("direction") == "short" else 1) * int(r.get("shares") or 0)
    for r in td.get("ib_only", []):
        s = r["symbol"].upper()
        q2 = int(r.get("shares") or 0)
        ib_signed[s] = q2 if r.get("direction", "long") == "long" else -q2
    for r in td.get("direction_flipped", []):
        s = r["symbol"].upper()
        bot_signed[s] = (-1 if r.get("bot_side") == "short" else 1) * int(r.get("bot_shares") or 0)
        ib_signed[s] = (-1 if r.get("ib_side") == "short" else 1) * int(r.get("ib_shares") or 0)
    for r in td.get("share_mismatch", []):
        s = r["symbol"].upper()
        # direction same; sign unknown here → infer from bot_open_net if available
        sign = 1
        if bot_open_net.get(s, 0) < 0:
            sign = -1
        bot_signed[s] = sign * int(r.get("bot_shares") or 0)
        ib_signed[s] = sign * int(r.get("ib_shares") or 0)

    # --- combined per-symbol table ---
    syms = set(ib_net) | set(bot_open_net) | set(bot_signed) | set(ib_signed) | set(ib_cnt)
    if focus:
        syms = {s for s in syms if s == focus}
    print()
    print(bold(f"  {'SYM':<6} {'IB_POS':>8} {'BOT_POS':>8} {'Δ(IB-BOT)':>10} "
               f"{'IB_FILLS↻':>10} {'BOT_ROWS':>9}   flag"))
    print(dim("  " + "-" * 70))
    flagged = []
    for sym in sorted(syms):
        ibp = ib_signed.get(sym)
        botp = bot_signed.get(sym)
        delta = None
        if ibp is not None and botp is not None:
            delta = ibp - botp
        flag = ""
        if delta not in (None, 0):
            flag = red("DRIFT")
            flagged.append(sym)
        elif ibp is not None or botp is not None:
            flag = yel("see §1")
        ibp_s = sgn_str(ibp) if ibp is not None else dim("·")
        botp_s = sgn_str(botp) if botp is not None else dim("·")
        d_s = sgn_str(delta) if delta is not None else dim("·")
        print(f"  {sym:<6} {ibp_s:>8} {botp_s:>8} {d_s:>10} "
              f"{sgn_str(ib_net.get(sym,0)):>10} {bot_today_cnt.get(sym,0):>9}   {flag}")

    # --- per-symbol fill trails for flagged / IB-only names ---
    detail_syms = set(flagged) | {r["symbol"].upper() for r in td.get("ib_only", [])} \
        | {r["symbol"].upper() for r in td.get("direction_flipped", [])}
    if focus:
        detail_syms = {s for s in detail_syms if s == focus} or ({focus} if focus in ib_fills_by_sym else set())
    for sym in sorted(detail_syms):
        fills = ib_fills_by_sym.get(sym, [])
        if not fills:
            continue
        print(yel(f"\n  IB fill trail — {sym} (running net):"))
        run = 0
        for t, side, qty, px in fills:
            run += _signed(side, qty)
            print(f"    {dim(t)}  {side:<4} {qty:>5} @ {px}   net→ {sgn_str(run)}")


def section_drift_status(focus):
    hdr("5) BOT'S OWN DRIFT DETECTOR  (/share-drift-status)")
    data = get("/api/trading-bot/share-drift-status")
    if isinstance(data, dict) and "__error__" in data:
        print(red(f"  endpoint error: {data['__error__']}"))
        return
    print("  " + json.dumps(data, default=str)[:1200])


def main():
    focus = None
    if "--symbol" in sys.argv:
        i = sys.argv.index("--symbol")
        if i + 1 < len(sys.argv):
            focus = sys.argv[i + 1].upper()

    print(bold(f"\nBOT-vs-IB DRIFT FORENSICS  ·  API={API}  ·  "
               f"{datetime.now(timezone.utc).isoformat()}"
               + (f"  ·  FOCUS={focus}" if focus else "")))

    td = section_truth_diff(focus)
    section_bot_open(focus)
    section_broker_positions(focus)
    db = mongo_db()
    section_fills_recon(db, td or {}, focus)
    section_drift_status(focus)

    hdr("VERDICT")
    if td and td.get("in_sync"):
        print(grn("  Live bot/IB position sets are IN SYNC. Any historical fill"))
        print(grn("  divergence above is informational. Re-run if a new fill just landed."))
    else:
        bo = len(td.get("bot_only", [])) if td else 0
        io = len(td.get("ib_only", [])) if td else 0
        fl = len(td.get("direction_flipped", [])) if td else 0
        sm = len(td.get("share_mismatch", [])) if td else 0
        print(red(f"  OUT OF SYNC — bot_only={bo}  ib_only={io}  flipped={fl}  share_mismatch={sm}"))
        print("  Next (still READ-ONLY): inspect a symbol with")
        print(cyn("    curl -s 'http://localhost:8001/api/trading-bot/diag/symbol-state?symbol=SYM' | python3 -m json.tool"))
        print(cyn("    curl -s 'http://localhost:8001/api/trading-bot/positions/reconcile' | python3 -m json.tool   # dry compare"))
        print(red("  Do NOT run any /reconcile or /flatten POST until we agree on the fix."))
    print()


if __name__ == "__main__":
    main()
