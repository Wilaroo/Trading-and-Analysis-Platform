#!/usr/bin/env python3
"""_build_v320h1_patcher.py — generator for patch_v320h1_oca_implied_primary.py

Builds a §2.2 patcher that upgrades the ALREADY-DEPLOYED v320h finalize block
(implied-primary). It targets the current DGX file (PRE_SHA = e5cec8f9..., the
v320h-applied state), swaps the v320h finalize block for the v320h.1 block, and
guards POST_SHA.

DEV-ONLY tool. Reconstructs the DGX content from the /app baseline + the v320h
transform so chunks are byte-exact.
"""
import base64
import hashlib
from pathlib import Path

import _build_v320h_patcher as v0  # PREFIX, SUFFIX, FINALIZE, OLD, NEW

HERE = Path(__file__).resolve().parent
PM = HERE.parent / "services" / "position_manager.py"
OUT = HERE / "patch_v320h1_oca_implied_primary.py"

PRE_SHA_BASE = "ee4f3f2ef837391e4b563b0a6dc48b0860c4b6b0fa19e2b4203f226f89117977"
PRE_SHA = "e5cec8f958e9a26477d8d3fb1f0e7814e9b268c39013d49cf31640c161787d0e"  # v320h applied

SENTINEL = "v320h.1: implied_from_realized is PRIMARY"

# v320h.1 finalize block — implied-primary, ib_executions as logged cross-check.
FINALIZE_V2 = '''                                # ── v19.34.320h — OCA close-path accounting finalize ── BEGIN ──
                                # v320h.1: implied_from_realized is PRIMARY (internally consistent —
                                # exit_price / pnl_pct always agree with net_pnl). ib_executions is a
                                # logged cross-check only; it is used as the exit_price source ONLY
                                # when the realized-implied basis is unavailable. Recomputes
                                # net_pnl = realized_pnl - total_commissions. Gated by
                                # V320H_OCA_FIX_POLICY (observe|fix|off, default observe).
                                try:
                                    import os as _os_v320h
                                    _v320h_policy = (_os_v320h.environ.get(
                                        "V320H_OCA_FIX_POLICY", "observe")
                                        or "observe").lower().strip()
                                    if _v320h_policy not in ("observe", "fix", "off"):
                                        _v320h_policy = "observe"
                                    if _v320h_policy != "off":
                                        _entry_basis = float(
                                            getattr(_trade, "fill_price", None)
                                            or getattr(_trade, "entry_price", 0) or 0)
                                        _v320h_dir = _dir
                                        _realized = float(getattr(_trade, "realized_pnl", 0) or 0)
                                        _shares_v = int(getattr(_trade, "shares", 0) or 0)
                                        # PRIMARY: implied exit from realized_pnl (consistent by construction).
                                        _implied = None
                                        if _entry_basis > 0 and _shares_v:
                                            if _v320h_dir == "short":
                                                _implied = round(_entry_basis - _realized / _shares_v, 4)
                                            else:
                                                _implied = round(_entry_basis + _realized / _shares_v, 4)
                                        # CROSS-CHECK: best-qty-match ib_executions close-side fill ±15m.
                                        _ib_px = None
                                        _close_side = "BUY" if _v320h_dir == "short" else "SELL"
                                        try:
                                            from datetime import datetime as _dt_v320h, timezone as _tz_v320h, timedelta as _td_v320h
                                            _closed_raw = getattr(_trade, "closed_at", None)
                                            if isinstance(_closed_raw, str):
                                                _closed_dt = _dt_v320h.fromisoformat(_closed_raw.replace("Z", "+00:00"))
                                            elif _closed_raw is not None:
                                                _closed_dt = _closed_raw
                                            else:
                                                _closed_dt = _dt_v320h.now(_tz_v320h.utc)
                                            if _closed_dt.tzinfo is None:
                                                _closed_dt = _closed_dt.replace(tzinfo=_tz_v320h.utc)
                                            _lo = (_closed_dt - _td_v320h(minutes=15)).isoformat()
                                            _hi = (_closed_dt + _td_v320h(minutes=15)).isoformat()
                                            _db_v320h = (getattr(bot, "_db", None)
                                                         if getattr(bot, "_db", None) is not None
                                                         else getattr(bot, "db", None))
                                            if _db_v320h is not None:
                                                _q = {
                                                    "symbol": (_trade.symbol or "").upper(),
                                                    "$or": [
                                                        {"time": {"$gte": _lo, "$lte": _hi}},
                                                        {"timestamp": {"$gte": _lo, "$lte": _hi}},
                                                        {"exec_time": {"$gte": _lo, "$lte": _hi}},
                                                    ],
                                                }
                                                _execs = await asyncio.to_thread(
                                                    lambda: list(_db_v320h["ib_executions"].find(_q, {"_id": 0})))
                                                _best = None
                                                _best_score = None
                                                for _ex in _execs:
                                                    _eside = str(_ex.get("side") or _ex.get("action") or "").upper()
                                                    if _close_side == "SELL" and not _eside.startswith("S"):
                                                        continue
                                                    if _close_side == "BUY" and not _eside.startswith("B"):
                                                        continue
                                                    _epx = float(_ex.get("price") or _ex.get("avg_price")
                                                                 or _ex.get("fill_price") or 0)
                                                    if _epx <= 0:
                                                        continue
                                                    _eqty = int(abs(float(_ex.get("shares") or _ex.get("qty") or 0)))
                                                    _score = abs(_eqty - _shares_v)
                                                    if _best_score is None or _score < _best_score:
                                                        _best_score = _score
                                                        _best = _epx
                                                if _best is not None:
                                                    _ib_px = round(_best, 4)
                                        except Exception as _v320h_lk:
                                            logger.debug("[v19.34.320h] ib_executions cross-check threw: %s", _v320h_lk)
                                        # Resolve exit_price: implied (primary) > ib_executions > current_price.
                                        if _implied is not None:
                                            _exit_px, _exit_src = _implied, "implied_from_realized"
                                        elif _ib_px is not None:
                                            _exit_px, _exit_src = _ib_px, "ib_executions"
                                        else:
                                            _cp = float(getattr(_trade, "current_price", 0) or 0)
                                            _exit_px = round(_cp, 4) if _cp > 0 else None
                                            _exit_src = "current_price_fallback" if _cp > 0 else None
                                        _xdelta = (round(abs(_ib_px - _implied), 4)
                                                   if (_ib_px is not None and _implied is not None) else None)
                                        _new_net = round(_realized - float(getattr(_trade, "total_commissions", 0) or 0), 2)
                                        _new_pct = None
                                        if _exit_px is not None and _entry_basis > 0:
                                            if _v320h_dir == "short":
                                                _new_pct = round((_entry_basis - _exit_px) / _entry_basis * 100, 4)
                                            else:
                                                _new_pct = round((_exit_px - _entry_basis) / _entry_basis * 100, 4)
                                        if _v320h_policy == "fix":
                                            if _exit_px is not None:
                                                _trade.exit_price = _exit_px
                                            _trade.net_pnl = _new_net
                                            if _new_pct is not None:
                                                _trade.pnl_pct = _new_pct
                                            logger.info(
                                                "🔧 [v19.34.320h FIX] %s %s finalized: exit_price=%s (%s) "
                                                "net_pnl=%.2f pnl_pct=%s ib_xcheck=%s d=%s trade_id=%s",
                                                _trade.symbol, _v320h_dir.upper(), _exit_px, _exit_src,
                                                _new_net, _new_pct, _ib_px, _xdelta, _trade.id)
                                        else:
                                            logger.info(
                                                "👁️ [v19.34.320h OBSERVE] %s %s would finalize: exit_price=%s (%s) "
                                                "net_pnl=%.2f pnl_pct=%s ib_xcheck=%s d=%s (cur net_pnl=%s) trade_id=%s",
                                                _trade.symbol, _v320h_dir.upper(), _exit_px, _exit_src,
                                                _new_net, _new_pct, _ib_px, _xdelta,
                                                getattr(_trade, "net_pnl", None), _trade.id)
                                except Exception as _v320h_err:
                                    logger.debug("[v19.34.320h] finalize block threw (non-fatal): %s", _v320h_err)
                                # ── v19.34.320h — OCA close-path accounting finalize ── END ──
'''

TEMPLATE = r'''#!/usr/bin/env python3
"""patch_v320h1_oca_implied_primary.py  —  v19.34.320h.1 patcher  (2026-06-16)

UPGRADES the already-deployed v320h finalize block in position_manager.py to be
implied-primary.

WHY: the v320h diag (paste.rs/ip7Bb) showed ib_executions best-qty-match can
contradict realized_pnl on STACKED closes (e.g., DVN: ib exit 43.69 implies a
loss while realized_pnl=+301.94). implied_from_realized (entry +/- realized/
shares) is internally CONSISTENT — exit_price / pnl_pct always agree with
net_pnl. So v320h.1 makes implied the PRIMARY source and keeps ib_executions as
a logged cross-check (delta `d=` in the FIX/OBSERVE log line); ib_executions is
only used as the exit_price source when the implied basis is unavailable.

TARGET STATE: the v320h-applied file (PRE_SHA256 e5cec8f9...). Run patch_v320h
FIRST if the file is still the original baseline (@@PRE_SHA_BASE@@).

AGENTS.md §2.2: PRE_SHA256 + POST_SHA256 guards, base64 (old,new) single-chunk
swap, auto-backup, --check/--apply/--rollback/--status. Local override via
V320H_PM_TARGET / TAP_REPO_ROOT.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PRE_SHA256 = "@@PRE_SHA@@"          # v320h applied
PRE_SHA256_BASE = "@@PRE_SHA_BASE@@"  # original baseline (v320h NOT yet applied)
POST_SHA256 = "@@POST_SHA@@"
SENTINEL = "@@SENTINEL@@"

REPO_ROOT = Path(os.environ.get("TAP_REPO_ROOT") or (Path.home() / "Trading-and-Analysis-Platform"))
TARGET = Path(os.environ.get("V320H_PM_TARGET") or (REPO_ROOT / "backend" / "services" / "position_manager.py"))

OLD_B64 = "@@OLD_B64@@"
NEW_B64 = "@@NEW_B64@@"
APPLIED_STAMP = "/tmp/v320h1_implied_primary.applied"


def _old():
    return base64.b64decode(OLD_B64).decode("utf-8")


def _new():
    return base64.b64decode(NEW_B64).decode("utf-8")


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _read():
    if not TARGET.exists():
        print("ERROR: target missing:", TARGET)
        sys.exit(1)
    return TARGET.read_text(encoding="utf-8")


def cmd_check():
    body = _read()
    cur = _sha(body.encode("utf-8"))
    print("  target :", TARGET)
    print("  sha    :", cur)
    if SENTINEL in body:
        if cur == POST_SHA256:
            print("  ALREADY APPLIED (sha == POST_SHA256). No-op. Use --rollback to revert.")
            sys.exit(0)
        print("  marker present but sha != POST_SHA256 — file drifted post-apply.")
        sys.exit(4)
    if cur == PRE_SHA256_BASE:
        print("  ABORT: file is the ORIGINAL baseline — v320h not applied yet.")
        print("         Run patch_v320h --apply FIRST, then this patcher.")
        sys.exit(6)
    if cur != PRE_SHA256:
        print("  PRE_SHA256 MISMATCH — file drifted from the v320h-applied state.")
        print("    expected", PRE_SHA256)
        print("    actual  ", cur)
        sys.exit(2)
    old = _old()
    n = body.count(old)
    if n != 1:
        print("  anchor chunk not unique (count=%d) — refusing to write." % n)
        sys.exit(3)
    pp = _sha(body.replace(old, _new(), 1).encode("utf-8"))
    print("  PRE_SHA256 ok; anchor unique.")
    print("  projected POST_SHA256 =", pp)
    if pp != POST_SHA256:
        print("  projected sha != embedded POST_SHA256 — ABORT.")
        sys.exit(5)
    print("  projected hash matches embedded POST_SHA256. Run --apply to write.")


def cmd_apply():
    body = _read()
    cur = _sha(body.encode("utf-8"))
    if SENTINEL in body and cur == POST_SHA256:
        print("  ALREADY APPLIED. No-op.")
        return
    if cur == PRE_SHA256_BASE:
        print("  ABORT: v320h not applied yet. Run patch_v320h --apply first.")
        sys.exit(6)
    if cur != PRE_SHA256:
        print("  ABORT: PRE_SHA256 mismatch. Run --check.")
        sys.exit(2)
    old = _old()
    if body.count(old) != 1:
        print("  ABORT: anchor chunk not unique. Run --check.")
        sys.exit(3)
    new_body = body.replace(old, _new(), 1)
    pp = _sha(new_body.encode("utf-8"))
    if pp != POST_SHA256:
        print("  ABORT: post-patch sha %s != embedded POST_SHA256. No write." % pp)
        sys.exit(5)
    bak = TARGET.with_suffix(TARGET.suffix + ".bak." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    TARGET.rename(bak)
    TARGET.write_text(new_body, encoding="utf-8")
    Path(APPLIED_STAMP).write_text("applied_at=%s\npre=%s\npost=%s\nbackup=%s\n" % (_now(), PRE_SHA256, POST_SHA256, bak))
    print("  wrote", TARGET, "(%d chars)" % len(new_body))
    print("  backup at", bak.name)
    print("  POST_SHA256 verified ==", POST_SHA256)
    print("\n  NEXT: git add backend/services/position_manager.py && git commit -m 'v19.34.320h.1 implied-primary' && git push origin main")
    print("        ./start_backend.sh --force")


def cmd_rollback():
    body = _read()
    if SENTINEL not in body:
        print("  no v320h.1 sentinel present — nothing to roll back.")
        return
    new = body.replace(_new(), _old(), 1)
    if new == body:
        print("  WARNING: chunk-revert matched nothing. ABORT.")
        sys.exit(2)
    rp = _sha(new.encode("utf-8"))
    bak = TARGET.with_suffix(TARGET.suffix + ".bak_rollback." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    TARGET.rename(bak)
    TARGET.write_text(new, encoding="utf-8")
    try:
        os.remove(APPLIED_STAMP)
    except FileNotFoundError:
        pass
    print("  rolled back to v320h state. patched copy at", bak.name)
    print("  restored sha =", rp, " (== v320h PRE_SHA256:", rp == PRE_SHA256, ")")


def cmd_status():
    body = _read()
    cur = _sha(body.encode("utf-8"))
    print("  target  :", TARGET)
    print("  sha     :", cur)
    print("  v320h.1 applied:", SENTINEL in body, " (sha==POST:", cur == POST_SHA256, ")")
    print("  policy  : V320H_OCA_FIX_POLICY=" + os.environ.get("V320H_OCA_FIX_POLICY", "observe (default)"))
    if os.path.exists(APPLIED_STAMP):
        print("  stamp   :\n" + Path(APPLIED_STAMP).read_text())


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    g.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.check:
        cmd_check()
    elif a.apply:
        cmd_apply()
    elif a.rollback:
        cmd_rollback()
    elif a.status:
        cmd_status()


if __name__ == "__main__":
    main()
'''


def main():
    base = PM.read_text(encoding="utf-8")
    assert _sha_str(base) == PRE_SHA_BASE, "baseline drift"
    # reconstruct the v320h-applied DGX content
    dgx = base.replace(v0.OLD, v0.NEW, 1)
    assert _sha_str(dgx) == PRE_SHA, f"v320h reconstruct sha mismatch: {_sha_str(dgx)}"
    old = v0.FINALIZE
    assert dgx.count(old) == 1, f"v320h FINALIZE not unique in dgx: {dgx.count(old)}"
    new_src = dgx.replace(old, FINALIZE_V2, 1)
    post = _sha_str(new_src)
    assert SENTINEL in new_src and SENTINEL not in dgx
    compile(new_src, "position_manager.py", "exec")

    out = (TEMPLATE
           .replace("@@PRE_SHA@@", PRE_SHA)
           .replace("@@PRE_SHA_BASE@@", PRE_SHA_BASE)
           .replace("@@POST_SHA@@", post)
           .replace("@@SENTINEL@@", SENTINEL)
           .replace("@@OLD_B64@@", base64.b64encode(old.encode()).decode())
           .replace("@@NEW_B64@@", base64.b64encode(FINALIZE_V2.encode()).decode()))
    OUT.write_text(out, encoding="utf-8")
    print("PRE_SHA (v320h applied) =", PRE_SHA)
    print("POST_SHA (v320h.1)      =", post)
    print("emitted ->", OUT, f"({len(out):,} bytes)")


def _sha_str(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    main()
