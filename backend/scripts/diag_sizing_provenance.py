#!/usr/bin/env python3
"""
diag_sizing_provenance.py — READ-ONLY sizing forensics for OPEN trades.

Answers "why is this position the size it is?" by dumping, for every open
`bot_trades` row:
  • Grades:   unified / tqs(+score) / quality / smb  (so you can see which
              grade the sizer actually used: the grade multiplier reads the
              TQS grade per v19.34.175).
  • Prices:   entry · fill · DISPLAYED stop · ORIGINAL (sizing) stop.
  • Shares:   original / remaining.
  • Chain:    every position multiplier captured in
              entry_context.multipliers, multiplied into a COMBINED factor:
              volatility × regime × vp_path × grade × mr.
  • Risk:     stored risk_amount  vs  realized risk @ displayed stop  vs
              realized risk @ original stop  vs  the implied base budget
              (risk_amount / combined_factor). Flags a MISMATCH when the
              stored risk_amount disagrees with shares × |entry−stop|.

100% read-only — only `.find()`. No writes, no restart needed.

Run (DGX):
    .venv/bin/python backend/scripts/diag_sizing_provenance.py
    SYMBOL=BEN .venv/bin/python backend/scripts/diag_sizing_provenance.py   # one name
"""
import os
import sys

from pymongo import MongoClient

OPEN_STATUSES = ["pending", "open", "partial"]


def _f(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _fmt(v, nd=2, dollar=False, pct=False):
    if v is None:
        return "—"
    try:
        if pct:
            return f"{float(v) * 100:.1f}%"
        s = f"{float(v):.{nd}f}"
        return f"${s}" if dollar else s
    except (TypeError, ValueError):
        return str(v)


def _original_stop(doc):
    """Stop the SIZER used, if it differs from the live/displayed stop.
    Priority: multipliers.stop_guard.original_stop → trailing_stop_config.
    original_stop → scale_out_state.original_stop → None."""
    ec = doc.get("entry_context") or {}
    mult = ec.get("multipliers") or {}
    sg = mult.get("stop_guard") or {}
    for src in (
        sg.get("original_stop"),
        (doc.get("trailing_stop_config") or {}).get("original_stop"),
        (doc.get("scale_out_state") or {}).get("original_stop"),
    ):
        v = _f(src)
        if v and v > 0:
            return v
    return None


def _chain(doc):
    """Return (ordered list of (name, value), combined_product)."""
    ec = doc.get("entry_context") or {}
    mult = ec.get("multipliers") or {}
    order = [
        ("volatility", mult.get("volatility")),
        ("regime", mult.get("regime")),
        ("vp_path", mult.get("vp_path")),
        ("grade", mult.get("grade_multiplier")),
        ("mr", mult.get("mr_multiplier")),
    ]
    rows = []
    combined = 1.0
    for name, v in order:
        fv = _f(v)
        if fv is None:
            rows.append((name, None))
            continue
        rows.append((name, fv))
        combined *= fv
    return rows, combined, mult


def dump_trade(doc):
    sym = doc.get("symbol", "?")
    direction = (doc.get("direction") or "?")
    setup = doc.get("setup_type") or "?"
    style = doc.get("trade_style") or "?"
    status = doc.get("status") or "?"

    entry = _f(doc.get("entry_price"))
    fill = _f(doc.get("fill_price"))
    disp_stop = _f(doc.get("stop_price"))
    orig_stop = _original_stop(doc)

    shares = int(_f(doc.get("shares"), 0) or 0)
    orig_sh = int(_f(doc.get("original_shares"), 0) or 0)
    rem_sh = int(_f(doc.get("remaining_shares"), 0) or 0)
    size_sh = orig_sh or shares  # size the sizer produced

    risk_amount = _f(doc.get("risk_amount"))
    rr = _f(doc.get("risk_reward_ratio"))
    reward = _f(doc.get("potential_reward"))

    ug = doc.get("unified_grade") or "—"
    tg = doc.get("tqs_grade") or "—"
    tscore = _f(doc.get("tqs_score"))
    qg = doc.get("quality_grade") or "—"
    smb = doc.get("smb_grade") or "—"

    rows, combined, mult = _chain(doc)

    print(f"\n{'═' * 72}")
    print(f"  {sym:<6} {direction.upper():<5} · {setup} · style={style} · {status}")
    print(f"{'─' * 72}")
    print(f"  grades   unified={ug}  tqs={tg}"
          f"{f'({tscore:.0f})' if tscore else ''}  quality={qg}  smb={smb}")

    # ── Raw grade provenance — what the SIZER actually saw ────────────
    ec = doc.get("entry_context") or {}
    mult_raw = ec.get("multipliers") or {}
    tqs_ctx = ec.get("tqs") or {}
    sizer_grade = mult_raw.get("grade")  # normalized grade string the sizer used
    qscore = _f(doc.get("quality_score"))
    trade_grade = doc.get("trade_grade")
    print(f"  WHO-SET  sizer_used_grade={sizer_grade or '—'}  "
          f"(→ mult {_fmt(mult_raw.get('grade_multiplier'))})   "
          f"trade_grade(alert)={trade_grade or '—'}  "
          f"quality_score={_fmt(qscore, nd=0)}")
    if tqs_ctx:
        print(f"  ctx.tqs  score={_fmt(tqs_ctx.get('score'), nd=0)}  "
              f"unified={tqs_ctx.get('unified_grade') or '—'}  "
              f"post_gate_grade={tqs_ctx.get('post_gate_grade') or '—'}  "
              f"pre_gate_score={_fmt(tqs_ctx.get('pre_gate_score'), nd=0)}")
    else:
        print(f"  ctx.tqs  (none captured — no TQS for this setup)")
    print(f"  prices   entry={_fmt(entry, dollar=True)}  "
          f"fill={_fmt(fill, dollar=True)}  "
          f"stop(displayed)={_fmt(disp_stop, dollar=True)}  "
          f"stop(sizing)={_fmt(orig_stop, dollar=True)}")
    print(f"  shares   sized={size_sh}  remaining={rem_sh}")

    # Multiplier chain
    chain_str = "  chain    base × "
    parts = []
    for name, v in rows:
        parts.append(f"{name}={_fmt(v) if v is not None else 'n/a'}")
    print(chain_str + "  ".join(parts))
    print(f"           COMBINED factor = {combined:.3f}"
          f"  ({combined * 100:.0f}% of base max_risk)")
    # surface mr reason if present
    if mult.get("mr_reason"):
        print(f"           mr_reason={mult.get('mr_reason')}")
    sg = mult.get("stop_guard") or {}
    if sg.get("snapped"):
        print(f"           stop_guard SNAPPED: {sg.get('reason')} "
              f"widen={_fmt(sg.get('widen_pct'), pct=True)} "
              f"orig={_fmt(_f(sg.get('original_stop')), dollar=True)}")

    # ── Risk reconciliation ───────────────────────────────────────────
    risk_disp = (size_sh * abs(entry - disp_stop)
                 if entry and disp_stop and size_sh else None)
    risk_orig = (size_sh * abs(entry - orig_stop)
                 if entry and orig_stop and size_sh else None)
    implied_base = (risk_amount / combined) if (risk_amount and combined) else None

    print(f"  risk     stored risk_amount = {_fmt(risk_amount, dollar=True)}")
    print(f"           realized @ displayed stop = {_fmt(risk_disp, dollar=True)}"
          f"   (sized {size_sh} × |{_fmt(entry, dollar=True)}−{_fmt(disp_stop, dollar=True)}|)")
    if risk_orig is not None:
        print(f"           realized @ sizing stop    = {_fmt(risk_orig, dollar=True)}")
    if implied_base is not None:
        print(f"           implied base max_risk     = {_fmt(implied_base, dollar=True)}"
              f"   (risk_amount ÷ {combined:.3f})")
    if rr is not None or reward is not None:
        print(f"           R:R={_fmt(rr)}  potential_reward={_fmt(reward, dollar=True)}")

    # Mismatch flag — stored vs realized @ displayed stop
    if risk_amount and risk_disp:
        diff = abs(risk_amount - risk_disp)
        if diff > 5 and diff > 0.10 * max(risk_amount, risk_disp):
            culprit = ""
            if risk_orig is not None and abs(risk_amount - risk_orig) <= diff:
                culprit = " → matches the SIZING (pre-cap) stop, not displayed"
            print(f"  ⚠️  MISMATCH: stored risk ${risk_amount:.0f} vs "
                  f"realized ${risk_disp:.0f} at displayed stop "
                  f"(Δ ${diff:.0f}).{culprit}")


def main():
    url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    only_symbol = (os.environ.get("SYMBOL") or "").upper().strip()

    client = MongoClient(url, serverSelectionTimeoutMS=5000)
    db = client[db_name]

    query = {"status": {"$in": OPEN_STATUSES}}
    if only_symbol:
        query["symbol"] = only_symbol

    docs = list(db.bot_trades.find(query))
    print(f"[diag_sizing_provenance] {len(docs)} open bot_trades "
          f"(db={db_name}, statuses={OPEN_STATUSES}"
          f"{f', symbol={only_symbol}' if only_symbol else ''})")

    if not docs:
        print("  (none — nothing open right now)")
        return 0

    docs.sort(key=lambda d: d.get("symbol", ""))
    mismatches = 0
    for d in docs:
        dump_trade(d)
        # crude re-detect for the summary
        entry = _f(d.get("entry_price"))
        disp_stop = _f(d.get("stop_price"))
        size_sh = int(_f(d.get("original_shares"), 0) or 0) or int(_f(d.get("shares"), 0) or 0)
        ra = _f(d.get("risk_amount"))
        if entry and disp_stop and size_sh and ra:
            rd = size_sh * abs(entry - disp_stop)
            if abs(ra - rd) > 5 and abs(ra - rd) > 0.10 * max(ra, rd):
                mismatches += 1

    print(f"\n{'═' * 72}")
    print(f"  SUMMARY: {len(docs)} open · {mismatches} risk-display mismatch(es)")
    print(f"{'═' * 72}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
