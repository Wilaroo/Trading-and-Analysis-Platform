#!/usr/bin/env python3
"""
diag_exit_decode.py  (READ-ONLY)
================================
Decodes the "94% non-edge" exits using v263's OWN tested logic
(`services.trade_outcome_hygiene.classify_close` / `reclassify_external_exit`)
to answer the pivotal question:

  How much of the non-`stop_loss`/`target` close churn is actually
  DECODABLE GENUINE bracket fills (a cheap LABELING fix — just apply the
  v263 decoder in the grading path), vs TRUE lifecycle churn / artifacts
  (a deep state-integrity fix)?

Outputs:
  1. classify_close() verdict across all 30d closes — genuine vs artifact,
     broken down by tag (external_target / external_stop_loss /
     external_partial / instant_external_unwind / corrupt_r / artifact_*).
  2. For the OCA/external-bracket reasons specifically — decode outcome
     (target / stop_loss / external_partial / corrupt_r / unresolved).
  3. Hold-time distribution (executed_at->closed_at, since hold_seconds is
     unpopulated) for genuine vs artifact — seconds=phantom race,
     minutes/hours=real trade.
  4. PER-SETUP regrade: current win/avg_r (ALL closes, current behavior)
     vs GENUINE-ONLY win/median_r (what the F-gate WOULD see if it applied
     the v263 decoder). The delta is the prize.

Imports the live service, so run from repo root on the DGX with the venv:
    .venv/bin/python backend/scripts/diag_exit_decode.py --days 30
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _bootstrap_path():
    # Ensure `backend/` is importable so we can reuse the live decoder.
    for cand in (Path.cwd() / "backend",
                 Path.cwd(),):
        if (cand / "services" / "trade_outcome_hygiene.py").exists():
            sys.path.insert(0, str(cand))
            return
    try:
        here = Path(__file__).resolve().parents[1]  # backend/
        if (here / "services" / "trade_outcome_hygiene.py").exists():
            sys.path.insert(0, str(here))
    except NameError:
        pass


def _load_env():
    cands = [Path.cwd() / "backend" / ".env", Path.cwd() / ".env"]
    try:
        cands.append(Path(__file__).resolve().parents[1] / ".env")
    except NameError:
        pass
    for c in cands:
        if c.exists():
            for line in c.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _db():
    from pymongo import MongoClient
    url, name = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or not name:
        print("ERROR: MONGO_URL / DB_NAME not set.")
        sys.exit(1)
    return MongoClient(url, serverSelectionTimeoutMS=4000)[name]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _entry(t):
    return _num(t.get("entry_price")) or _num(t.get("fill_price"))


def _exit(t):
    return (_num(t.get("exit_price")) or _num(t.get("close_price"))
            or _num(t.get("avg_exit_price")))


def _stop(t):
    return _num(t.get("stop_price")) or _num(t.get("stop_loss"))


def _targets(t):
    tp = t.get("target_prices")
    if isinstance(tp, list) and tp:
        return tp
    one = t.get("target_price")
    return [one] if one is not None else []


def _holds(t):
    ex, cl = t.get("executed_at") or t.get("entry_time"), t.get("closed_at") or t.get("exit_time")
    try:
        a = datetime.fromisoformat(str(ex).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(cl).replace("Z", "+00:00"))
        s = (b - a).total_seconds()
        return s if s >= 0 else None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    _bootstrap_path()
    _load_env()
    try:
        from services.trade_outcome_hygiene import classify_close, reclassify_external_exit
    except Exception as e:
        print(f"ERROR importing v263 decoder: {e}")
        print("Run from repo root with the venv: .venv/bin/python backend/scripts/diag_exit_decode.py")
        sys.exit(1)
    db = _db()
    cutoff_str = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=args.days)
    print(f"\n{'#'*100}\n#  EXIT DECODE (v263 logic)   window={args.days}d (since {cutoff_str})\n{'#'*100}")

    proj = {"_id": 0, "setup_type": 1, "direction": 1, "entered_by": 1,
            "entry_price": 1, "fill_price": 1, "exit_price": 1, "close_price": 1,
            "avg_exit_price": 1, "stop_price": 1, "stop_loss": 1, "target_price": 1,
            "target_prices": 1, "realized_pnl": 1, "shares": 1, "risk_amount": 1,
            "close_reason": 1, "exit_reason": 1, "executed_at": 1, "closed_at": 1,
            "entry_time": 1, "exit_time": 1, "learning_only": 1, "entry_context": 1}
    rows = list(db["bot_trades"].find(
        {"status": "closed", "closed_at": {"$gte": cutoff_str}}, proj))
    if not rows:
        rows = list(db["bot_trades"].find(
            {"status": "closed", "closed_at": {"$gte": cutoff_dt}}, proj))
    rows = [t for t in rows if not (t.get("learning_only") is True
            or (t.get("entry_context") or {}).get("learning_only") is True)]
    print(f"\nClosed non-learning trades: {len(rows)}")
    if not rows:
        return

    # ── 1. classify_close verdict ───────────────────────────────────────
    genuine_tags, artifact_tags = Counter(), Counter()
    decoded = []  # (is_genuine, tag, trade)
    for t in rows:
        cr = t.get("close_reason") or t.get("exit_reason")
        is_gen, tag = classify_close(
            cr, entered_by=t.get("entered_by", ""), entry_price=_entry(t),
            exit_price=_exit(t), net_pnl=_num(t.get("realized_pnl")),
            hold_seconds=_holds(t), setup_type=t.get("setup_type", ""),
            direction=t.get("direction"), stop_price=_stop(t),
            target_prices=_targets(t), realized_pnl=_num(t.get("realized_pnl")),
            shares=_num(t.get("shares")))
        decoded.append((is_gen, tag, t))
        (genuine_tags if is_gen else artifact_tags)[tag.split(":")[0]] += 1
    ng = sum(1 for d in decoded if d[0])
    print(f"\n[1] classify_close() verdict (v263 logic applied to ALL closes)")
    print(f"    GENUINE : {ng:>5} ({100.0*ng/len(rows):.1f}%)")
    print(f"    ARTIFACT: {len(rows)-ng:>5} ({100.0*(len(rows)-ng)/len(rows):.1f}%)")
    print(f"\n    GENUINE tags:")
    for tag, n in genuine_tags.most_common():
        print(f"      {n:>5}  {tag}")
    print(f"    ARTIFACT tags:")
    for tag, n in artifact_tags.most_common():
        print(f"      {n:>5}  {tag}")

    # ── 2. external-bracket decode outcome ──────────────────────────────
    print(f"\n[2] OCA / external-bracket reasons → reclassify_external_exit outcome")
    method_ct, eff_ct = Counter(), Counter()
    for t in rows:
        cr = t.get("close_reason") or t.get("exit_reason")
        eff, method, _x, _r = reclassify_external_exit(
            close_reason=cr, direction=t.get("direction"), entry_price=_entry(t),
            exit_price=_exit(t), stop_price=_stop(t), target_prices=_targets(t),
            realized_pnl=_num(t.get("realized_pnl")), shares=_num(t.get("shares")))
        if method != "not_external":
            method_ct[method] += 1
            eff_ct[eff or "none"] += 1
    total_ext = sum(method_ct.values())
    print(f"    external-bracket rows decoded: {total_ext}")
    print(f"    by method : " + "  ".join(f"{k}={v}" for k, v in method_ct.most_common()))
    print(f"    by outcome: " + "  ".join(f"{k}={v}" for k, v in eff_ct.most_common()))
    resolved = eff_ct.get("target", 0) + eff_ct.get("stop_loss", 0) + eff_ct.get("external_partial", 0)
    if total_ext:
        print(f"    >>> {resolved}/{total_ext} ({100.0*resolved/total_ext:.0f}%) of external-bracket "
              f"closes DECODE to a real target/stop/partial → recoverable as GENUINE by LABELING.")

    # ── 3. hold-time distribution ───────────────────────────────────────
    print(f"\n[3] Hold-time (executed_at→closed_at) — genuine vs artifact")
    buckets = [("<60s", 0, 60), ("1-5m", 60, 300), ("5-30m", 300, 1800),
               ("30m-4h", 1800, 14400), (">4h", 14400, 9e9)]
    gh, ah = Counter(), Counter()
    for is_gen, _tag, t in decoded:
        h = _holds(t)
        if h is None:
            (gh if is_gen else ah)["no-ts"] += 1
            continue
        for name, lo, hi in buckets:
            if lo <= h < hi:
                (gh if is_gen else ah)[name] += 1
                break
    order = [b[0] for b in buckets] + ["no-ts"]
    print(f"      {'bucket':<8}{'genuine':>9}{'artifact':>10}")
    for b in order:
        print(f"      {b:<8}{gh.get(b,0):>9}{ah.get(b,0):>10}")

    # ── 4. per-setup regrade: current vs genuine-only ───────────────────
    print(f"\n[4] PER-SETUP REGRADE — current (ALL closes) vs GENUINE-ONLY (v263 decoder)")
    by_setup = defaultdict(lambda: {"all_r": [], "gen_r": []})
    for is_gen, _tag, t in decoded:
        st = t.get("setup_type")
        if not st:
            continue
        ra = _num(t.get("risk_amount"))
        pnl = _num(t.get("realized_pnl"))
        if ra is None or ra < 1 or pnl is None:   # clamp the tiny-denominator corruption
            continue
        r = pnl / ra
        if abs(r) > 10:        # drop the externally-flattened windfalls/disasters
            continue
        by_setup[st]["all_r"].append(r)
        if is_gen:
            by_setup[st]["gen_r"].append(r)

    def wr(rs):
        return 100.0 * sum(1 for r in rs if r > 0) / len(rs) if rs else float("nan")
    print(f"      {'setup':<22}{'n_all':>6}{'wr_all':>8}{'avgR_all':>9}"
          f"{'n_gen':>7}{'wr_gen':>8}{'medR_gen':>9}")
    for st, d in sorted(by_setup.items(), key=lambda x: -len(x[1]["all_r"])):
        a, g = d["all_r"], d["gen_r"]
        if len(a) < 3:
            continue
        ar = statistics.fmean(a)
        gwr = wr(g)
        gmed = statistics.median(g) if g else float("nan")
        gwr_s = f"{gwr:6.0f}%" if gwr == gwr else "   n/a"
        gmed_s = f"{gmed:+.2f}" if gmed == gmed else "  n/a"
        print(f"      {st:<22}{len(a):>6}{wr(a):>7.0f}%{ar:>9.2f}"
              f"{len(g):>7}{gwr_s:>8}{gmed_s:>9}")

    print(f"\n{'='*100}\nINTERPRETATION\n{'='*100}")
    print(f"• [2] If a HIGH % of external-bracket closes decode to target/stop → the '94% "
          f"non-edge' is mostly a LABELING problem. Fix = make setup_grading_service apply "
          f"classify_close (cheap, days).")
    print(f"• [3] If artifact holds are mostly <60s → phantom/race churn (state-integrity, "
          f"deep). If genuine holds span minutes/hours → those are real trades to grade on.")
    print(f"• [4] Where wr_gen / medR_gen differs a lot from wr_all/avgR_all → the current "
          f"F-gate is judging setups on the WRONG (un-decoded) sample.")
    print(f"\nDone (read-only).")


if __name__ == "__main__":
    main()
