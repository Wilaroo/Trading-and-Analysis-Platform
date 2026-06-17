#!/usr/bin/env python3
"""
v320z — RUBBER BAND vs SMB CHEAT-SHEET TRUTH (READ-ONLY)

CONTEXT
-------
The SMB "Rubber Band Scalp" edge is a TRIGGER, not a STATE:
  • Entry  = a SINGLE green candle that clears the highs of 2+ prior candles
             (a "double-bar-break" SNAPBACK) AFTER an accelerated extension.
  • Extension metric = price > 3 ATRs FROM THE OPEN (not % from EMA9).
  • Quality        = RVOL 5+ ; snapback bar a top-5 volume bar of the day.
  • Avoid          = a cleanly trending market (SPY/QQQ/IWM steady trend).
  • Discipline     = "2 strikes and out" — max 2 attempts per stock per day.

Our detector (`_check_rubber_band`, enhanced_scanner.py) fires on a STATE:
    dist_from_ema9 < -2.5%  AND  rsi_14 < 38  AND  rvol >= 1.5     (long)
    dist_from_ema9 >  3.0%  AND  rsi_14 > 65  AND  rvol >= 1.5     (short)
There is NO candle/snapback check — so it flags EVERY bar of the grind-down,
not the one reversal bar. That is the over-fire hypothesis.

This diag replays stored rubber_band_* alerts against the parts of the cheat
sheet we CAN compute from stored data, and quantifies over-firing via the
"2 strikes/day" discipline the detector ignores. It does NOT modify anything.

What we CAN measure from stored alerts (fields + parsed `reasoning` text):
  1. RVOL  vs cheat-sheet quality bar (≥5)   [detector floor is 1.5]
  2. extension% vs the detector's own HIGH tier (>3.5% long / >4.0% short)
  3. OVER-FIRE: alerts per (symbol, day) vs the "2 attempts/day" cap
  4. clean-trend violation: longs fired while regime is STRONG_DOWNTREND
     (and shorts in STRONG_UPTREND) = fading a clean trend (cheat-sheet AVOID)
  5. tape / priority mix
  6. realized edge from bot_trades (auto-detecting schema)

What we CANNOT measure here (needs intraday bars at alert time, not stored):
  • the actual double-bar-break snapback candle
  • ATRs-from-open  (we proxy with the detector's % extension)
  • snapback bar = top-5 volume bar
These are flagged as the residual that only a true bar-replay can settle.

NOTHING IS WRITTEN. live_alerts reads project {"_id": 0}; bot_trades read-only.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_v320z_rubber_band_truth.py            # 5 days
  .venv/bin/python backend/scripts/diag_v320z_rubber_band_truth.py --days 10
"""
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# cheat-sheet quality / discipline constants
RVOL_QUALITY = 5.0          # cheat sheet: RVOL 5+ is the "really In Play" bar
DAILY_ATTEMPT_CAP = 2       # cheat sheet: 2 strikes and out, per stock per day
HIGH_EXT_LONG = 3.5         # detector's own CRITICAL/HIGH extension tier (long)
HIGH_EXT_SHORT = 4.0        # detector's own CRITICAL/HIGH extension tier (short)

_RE_EXT = re.compile(r"[Ee]xtended\s+([0-9.]+)%")
_RE_RVOL = re.compile(r"RVOL:\s*([0-9.]+)x")
_RE_RSI = re.compile(r"RSI\s+\w+\s+at\s+([0-9.]+)")


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=8000)[env["DB_NAME"]]


def _to_et(v):
    if isinstance(v, str) and len(v) >= 10:
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(ET)
        except Exception:
            return None
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(ET)
    return None


def _pct(n, d):
    return f"{(100.0 * n / d):.1f}%" if d else "  n/a"


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _prio(a):
    return str(a.get("priority", "")).strip().lower()


def _reason_text(a):
    r = a.get("reasoning")
    if isinstance(r, (list, tuple)):
        return " | ".join(str(x) for x in r)
    return str(r or "")


def _parse(a, regex, field_alts):
    """Prefer a stored numeric field; fall back to parsing reasoning text."""
    for f in field_alts:
        v = _f(a.get(f))
        if v is not None:
            return v
    m = regex.search(_reason_text(a))
    return _f(m.group(1)) if m else None


def _stats(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    mean = sum(xs) / n
    med = xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2
    return {"n": n, "min": xs[0], "med": med, "max": xs[-1], "mean": mean}


def main():
    days = 5
    if "--days" in sys.argv:
        try:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        except Exception:
            days = 5

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    print(f"\n=== v320z RUBBER BAND TRUTH — trailing {days} day(s) "
          f"(since {start.strftime('%Y-%m-%d')} ET) ===\n")

    rb = []
    for a in db.live_alerts.find({}, {"_id": 0}):
        su = (a.get("setup_type") or "").strip().lower()
        if not su.startswith("rubber_band"):
            continue
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if et and et >= start:
            a["_et"] = et
            a["_day"] = et.strftime("%Y-%m-%d")
            rb.append(a)

    if not rb:
        print("No rubber_band_* alerts in window. (live_alerts may be TTL-trimmed — try "
              "--days 1, or run intraday.)\n")
        return

    longs = [a for a in rb if (a.get("direction") or "").lower() == "long"
             or (a.get("setup_type") or "").endswith("long")]
    shorts = [a for a in rb if a not in longs]

    # ------------------------------------------------------------------
    print("=" * 80)
    print("SECTION 1 — rubber_band funnel")
    print("=" * 80)
    n = len(rb)
    tape_ok = sum(1 for a in rb if a.get("tape_confirmation") is True)
    prio = Counter(_prio(a) for a in rb)
    print(f"  total alerts      : {n}   (long={len(longs)}  short={len(shorts)})")
    print(f"  tape_confirmation : {tape_ok}  ({_pct(tape_ok, n)})")
    print(f"  priority mix      : " +
          ", ".join(f"{k or '?'}={v}" for k, v in prio.most_common()))
    hi = sum(prio[k] for k in ("high", "critical"))
    print(f"  HIGH+ (auto-fire) : {hi}  ({_pct(hi, n)})")

    # ------------------------------------------------------------------
    print("\n" + "=" * 80)
    print(f"SECTION 2 — RVOL vs cheat-sheet quality bar (≥{RVOL_QUALITY:g})  "
          f"[detector floor = 1.5]")
    print("=" * 80)
    rv = [_parse(a, _RE_RVOL, ("rvol", "relative_volume")) for a in rb]
    s = _stats(rv)
    if not s:
        print("  No RVOL recoverable (not stored, not in reasoning).")
    else:
        print(f"  parsed RVOL on {s['n']}/{n} alerts  "
              f"(min {s['min']:.1f} / med {s['med']:.1f} / mean {s['mean']:.1f} / max {s['max']:.1f})")
        q = sum(1 for x in rv if x is not None and x >= RVOL_QUALITY)
        print(f"  meet cheat-sheet RVOL ≥ {RVOL_QUALITY:g} : {q}  ({_pct(q, s['n'])})")
        print(f"  → {_pct(s['n'] - q, s['n'])} of current alerts are BELOW the cheat-sheet")
        print(f"    quality bar (fire on RVOL 1.5–5 the sheet would treat as low-conviction).")

    # ------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("SECTION 3 — extension vs detector HIGH tier "
          f"(long>{HIGH_EXT_LONG:g}% / short>{HIGH_EXT_SHORT:g}%)")
    print("=" * 80)
    ext_all = [_parse(a, _RE_EXT, ("dist_from_ema9_abs",)) for a in rb]
    s = _stats([abs(x) for x in ext_all if x is not None])
    if not s:
        print("  No extension recoverable.")
    else:
        print(f"  parsed extension% on {s['n']}/{n}  "
              f"(min {s['min']:.1f} / med {s['med']:.1f} / mean {s['mean']:.1f} / max {s['max']:.1f})")
        hi_l = sum(1 for a in longs if (lambda v: v is not None and v > HIGH_EXT_LONG)
                   (_parse(a, _RE_EXT, ("dist_from_ema9_abs",))))
        hi_s = sum(1 for a in shorts if (lambda v: v is not None and v > HIGH_EXT_SHORT)
                   (_parse(a, _RE_EXT, ("dist_from_ema9_abs",))))
        print(f"  longs  > {HIGH_EXT_LONG:g}% : {hi_l}/{len(longs)} ({_pct(hi_l, len(longs))})")
        print(f"  shorts > {HIGH_EXT_SHORT:g}% : {hi_s}/{len(shorts)} ({_pct(hi_s, len(shorts))})")
        print("  (note: cheat sheet measures extension in ATRs-FROM-OPEN, not %-from-EMA9;")
        print("   this % is the detector's own proxy — see residual note at the end.)")

    # ------------------------------------------------------------------
    print("\n" + "=" * 80)
    print(f"SECTION 4 — OVER-FIRE signature: alerts per (symbol, day) vs "
          f"cheat-sheet cap of {DAILY_ATTEMPT_CAP}/day")
    print("=" * 80)
    by_sd = Counter()
    for a in rb:
        by_sd[(a.get("symbol", "?"), a["_day"])] += 1
    counts = sorted(by_sd.values(), reverse=True)
    over = [c for c in counts if c > DAILY_ATTEMPT_CAP]
    sd_total = len(by_sd)
    fired_total = sum(counts)
    # how many alerts would collapse if capped at 2/symbol/day
    excess = sum(c - DAILY_ATTEMPT_CAP for c in counts if c > DAILY_ATTEMPT_CAP)
    print(f"  distinct (symbol,day) cells : {sd_total}")
    print(f"  cells exceeding {DAILY_ATTEMPT_CAP}/day      : {len(over)}  ({_pct(len(over), sd_total)})")
    print(f"  max alerts on one symbol/day: {counts[0] if counts else 0}")
    print(f"  total alerts                : {fired_total}")
    print(f"  EXCESS over a 2/day cap     : {excess}  "
          f"({_pct(excess, fired_total)} of all alerts)")
    print("  histogram (alerts/day → #cells):")
    hist = Counter(counts)
    for k in sorted(hist, reverse=True)[:12]:
        bar = "█" * min(hist[k], 50)
        flag = "  ← over cap" if k > DAILY_ATTEMPT_CAP else ""
        print(f"     {k:>3} → {hist[k]:>4} {bar}{flag}")
    print("\n  READ: a high EXCESS% is the data signature of firing on the grind-down")
    print("        STATE instead of the single SNAPBACK trigger. A snapback-gated")
    print("        detector + 2/day cap would collapse the excess to ~0.")

    # ------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("SECTION 5 — clean-trend violation (cheat-sheet AVOID: don't fade a clean trend)")
    print("=" * 80)
    reg = Counter((a.get("market_regime") or "?") for a in rb)
    for r, c in reg.most_common():
        print(f"     {r:<20} {c:>5}  ({_pct(c, n)})")
    long_dn = sum(1 for a in longs if "down" in str(a.get("market_regime", "")).lower())
    short_up = sum(1 for a in shorts if "up" in str(a.get("market_regime", "")).lower())
    print(f"  longs fired in a DOWN regime  : {long_dn}/{len(longs)} ({_pct(long_dn, len(longs))})  "
          f"(fading a falling tape)")
    print(f"  shorts fired in an UP regime  : {short_up}/{len(shorts)} ({_pct(short_up, len(shorts))})  "
          f"(fading a rising tape)")
    print("  (regime is a coarse proxy for SPY/QQQ/IWM trend; treat as directional, not exact.)")

    # ------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("SECTION 6 — realized edge from bot_trades (read-only, schema auto-detect)")
    print("=" * 80)
    try:
        bt = db["bot_trades"]
        sample = list(bt.find({}, {}).sort("created_at", -1).limit(1500))
        if not sample:
            print("  bot_trades empty in recent window.")
        else:
            keys = Counter()
            for d in sample:
                keys.update(d.keys())
            setup_field = next((k for k in ("setup_type", "setup", "strategy", "pattern",
                                            "strategy_name") if keys.get(k)), None)
            r_field = next((k for k in ("r_multiple", "realized_r", "r", "pnl_r")
                            if keys.get(k)), None)
            pnl_field = next((k for k in ("realized_pnl", "pnl", "net_pnl", "pnl_after_fees",
                                          "gross_pnl") if keys.get(k)), None)
            print(f"  detected → setup='{setup_field}' R='{r_field}' pnl='{pnl_field}'")
            if setup_field:
                matches = [d for d in sample
                           if str(d.get(setup_field, "")).strip().lower().startswith("rubber_band")]
                print(f"  rubber_band trades in last {len(sample)} bot_trades: {len(matches)}")
                rs = [_f(d.get(r_field)) for d in matches] if r_field else []
                rs = [x for x in rs if x is not None]
                if rs:
                    wins = sum(1 for x in rs if x > 0)
                    print(f"    win rate (R>0) : {_pct(wins, len(rs))}  mean R {sum(rs) / len(rs):+.2f}  (n={len(rs)})")
                pn = [_f(d.get(pnl_field)) for d in matches] if pnl_field else []
                pn = [x for x in pn if x is not None]
                if pn:
                    print(f"    sum pnl        : {sum(pn):+.2f}  mean {sum(pn) / len(pn):+.2f}")
                if not rs and not pn:
                    print("    (no R/pnl populated on matches)")
    except Exception as e:
        print(f"  bot_trades probe skipped: {e}")

    print("\n=== READING THE RESULT ===")
    print("• SECTION 4 EXCESS% is the headline number: it quantifies how much the")
    print("    state-based detector over-fires vs the cheat-sheet's single-snapback +")
    print("    2/day discipline. High EXCESS% ⇒ the fix is a TRIGGER + a daily cap,")
    print("    not just tightening the -2.5% threshold.")
    print("• SECTION 2 tells you how loose RVOL≥1.5 is vs the sheet's RVOL≥5 quality bar.")
    print("• SECTION 5 tells you how often we fade a clean trend (a cheat-sheet AVOID).")
    print("• RESIDUAL (cannot be settled here): the actual double-bar-break candle, true")
    print("    ATR-from-open extension, and top-5-volume snapback bar require an intraday")
    print("    BAR replay (bars are not stored on the alert). If SECTIONS 4/5 already show")
    print("    heavy over-fire + clean-trend fades, the patch case stands without it.\n")


if __name__ == "__main__":
    main()
