#!/usr/bin/env python3
"""diag_v374 (READ-ONLY) — universe / tradeability audit.

Goal (operator 2026-06): stop guessing the known-liquid list. (A) dump the
HARDCODED `_known_liquid_symbols` the scanner ships and audit it against the
live `symbol_adv_cache`; (B) rank the real top-N tradeable names from OUR OWN
Mongo data on the three axes pro day-trading screeners use —
  • avg DOLLAR volume   (liquidity / fill quality)
  • avg SHARE volume    (book depth)
  • ADRP %              (Average Daily Range % = avg((high-low)/close) over ~20
                         trading days — normalized intraday movement)
…and a blended tradeability score so we can decide the universe policy.

NOTHING WRITTEN. Usage (repo root, DGX):
  .venv/bin/python backend/scripts/diag_v374_universe_tradeability.py --top 300 --adr-days 20
"""
import re
import sys
from datetime import datetime, timedelta, timezone


def _arg(flag, d, c):
    if flag in sys.argv:
        try:
            return c(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return d
    return d


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    from pymongo import MongoClient
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=30000)[env["DB_NAME"]]


def _hardcoded_known_liquid():
    """Parse the `_known_liquid_symbols` set literal straight out of the
    scanner source so the audit always reflects what actually ships."""
    path = "backend/services/enhanced_scanner.py"
    try:
        src = open(path, encoding="utf-8").read()
    except FileNotFoundError:
        src = open("services/enhanced_scanner.py", encoding="utf-8").read()
    i = src.index("_known_liquid_symbols")
    brace = src.index("{", i)
    depth = 0
    j = brace
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    block = src[brace:j + 1]
    return sorted(set(re.findall(r'"([A-Z][A-Z0-9.\-]{0,9})"', block)))


def _fmt_m(v):
    if not isinstance(v, (int, float)):
        return "n/a"
    if v >= 1e9:
        return f"${v/1e9:.1f}B"
    return f"${v/1e6:.0f}M"


def main():
    top = _arg("--top", 300, int)
    adr_days = _arg("--adr-days", 20, int)
    db = _load_db()

    # ── A) hardcoded list audit ──────────────────────────────────────────
    hard = _hardcoded_known_liquid()
    print(f"\n=== v374 A) hardcoded _known_liquid_symbols audit ({len(hard)} symbols) ===")
    cache = {d["symbol"]: d for d in db["symbol_adv_cache"].find(
        {}, {"_id": 0, "symbol": 1, "avg_volume": 1, "avg_dollar_volume": 1, "tier": 1})}
    miss, below50, below3m_share = [], [], []
    for s in hard:
        c = cache.get(s)
        if not c:
            miss.append(s)
            continue
        if (c.get("avg_dollar_volume") or 0) < 50_000_000:
            below50.append((s, c.get("avg_dollar_volume") or 0))
        if (c.get("avg_volume") or 0) < 3_000_000:
            below3m_share.append((s, int(c.get("avg_volume") or 0)))
    print(f"  not in symbol_adv_cache at all : {len(miss)}  {miss[:25]}")
    print(f"  in cache but < $50M $-vol      : {len(below50)}")
    for s, v in sorted(below50, key=lambda kv: kv[1])[:25]:
        print(f"      {s:<7} {_fmt_m(v)}")
    print(f"  in cache but < 3M SHARE-vol    : {len(below3m_share)}  "
          f"(these BYPASS the scalp share floor today)")
    for s, v in sorted(below3m_share, key=lambda kv: kv[1])[:30]:
        print(f"      {s:<7} {v:,} sh/day  {_fmt_m((cache.get(s) or {}).get('avg_dollar_volume'))}")

    # ── B) data-driven top-N tradeability ────────────────────────────────
    ranked = sorted(
        [c for c in cache.values() if (c.get("avg_dollar_volume") or 0) > 0],
        key=lambda c: -(c.get("avg_dollar_volume") or 0))[:top]
    syms = [c["symbol"] for c in ranked]
    print(f"\n=== v374 B) computing ADRP({adr_days}d) for top {len(syms)} by $-vol ===")

    # ADRP per symbol from daily bars
    adrp = {}
    cut = (datetime.now(timezone.utc) - timedelta(days=adr_days * 3)).isoformat()
    for n, s in enumerate(syms):
        bars = list(db["ib_historical_data"].find(
            {"symbol": s, "bar_size": "1 day"},
            {"_id": 0, "high": 1, "low": 1, "close": 1, "date": 1}
        ).sort([("date", -1)]).limit(adr_days))
        rngs = []
        for b in bars:
            h, lo, c = b.get("high"), b.get("low"), b.get("close")
            if all(isinstance(x, (int, float)) for x in (h, lo, c)) and c > 0:
                rngs.append((h - lo) / c)
        adrp[s] = (100 * sum(rngs) / len(rngs)) if rngs else 0.0
        if (n + 1) % 50 == 0:
            print(f"    …{n + 1}/{len(syms)}")

    rows = []
    for c in ranked:
        s = c["symbol"]
        dv = c.get("avg_dollar_volume") or 0
        sv = int(c.get("avg_volume") or 0)
        price = (dv / sv) if sv else 0.0
        a = adrp.get(s, 0.0)
        # blended tradeability: movement (ADRP) × liquidity (sqrt $-vol),
        # so a name must MOVE *and* be liquid to rank — pure $-vol giants
        # that don't move (mega ETFs) score lower than mid-cap movers.
        score = a * (dv ** 0.5) / 1000.0
        rows.append({"s": s, "dv": dv, "sv": sv, "px": price, "adrp": a, "score": score,
                     "tier": c.get("tier")})

    def _table(title, items, extra=""):
        print(f"\n  {title}")
        print(f"    {'sym':<7}{'$-vol':>8}{'shares':>13}{'price':>9}{'ADRP%':>8}{'score':>9}")
        for r in items:
            print(f"    {r['s']:<7}{_fmt_m(r['dv']):>8}{r['sv']:>13,}"
                  f"{r['px']:>9.1f}{r['adrp']:>8.2f}{r['score']:>9.1f}")

    _table("TOP 25 by avg DOLLAR volume (liquidity):",
           rows[:25])
    liquid_deep = [r for r in rows if r["dv"] >= 50_000_000 and r["sv"] >= 3_000_000]
    _table(f"TOP 25 by ADRP%% (movement) among liquid (≥$50M & ≥3M sh) "
           f"[{len(liquid_deep)} qualify]:",
           sorted(liquid_deep, key=lambda r: -r["adrp"])[:25])
    _table("TOP 25 by BLENDED tradeability score (ADRP × √$-vol):",
           sorted(rows, key=lambda r: -r["score"])[:25])

    # ── C) the flagged tickers for reference ─────────────────────────────
    print("\n=== v374 C) flagged tickers (HON/EWT/IWF/FXI) ===")
    by_sym = {r["s"]: r for r in rows}
    for s in ("HON", "EWT", "IWF", "FXI"):
        r = by_sym.get(s)
        if not r:
            c = cache.get(s) or {}
            print(f"  {s:<6} (outside top {top}) "
                  f"$-vol={_fmt_m(c.get('avg_dollar_volume'))} "
                  f"shares={int(c.get('avg_volume') or 0):,}")
            continue
        print(f"  {s:<6} $-vol={_fmt_m(r['dv'])}  shares={r['sv']:,}  "
              f"price={r['px']:.1f}  ADRP%={r['adrp']:.2f}  score={r['score']:.1f}  "
              f"share_floor_pass={r['sv'] >= 3_000_000}")

    print("\n=== READING ===")
    print("• A) lists hardcoded names that DON'T clear $50M (stale picks) and those")
    print("  < 3M shares that silently BYPASS the scalp share floor today (the HON class).")
    print("• B) ADRP% is the movement axis pros use; a great day-trade name is HIGH on")
    print("  BOTH liquidity AND ADRP. Mega ETFs (SPY/QQQ) are liquid but low-ADRP →")
    print("  fine for size, poor for scalp range. The blended score surfaces movers.")
    print("• Decide universe policy from the data: e.g. require $-vol≥X AND share≥Y AND")
    print("  ADRP≥Z for scalp-eligibility; drop the static bypass for a computed one.\n")


if __name__ == "__main__":
    main()
