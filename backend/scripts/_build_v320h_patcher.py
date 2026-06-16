#!/usr/bin/env python3
"""_build_v320h_patcher.py — generator for patch_v320h_oca_close_finalize.py

Reads the canonical position_manager.py (PRE_SHA ee4f3f2e...), splices the
v19.34.320h OCA close-path accounting finalize block in-memory, computes the
POST_SHA256, base64-encodes the (old,new) chunk pair, and emits the AGENTS.md
§2.2-compliant patcher to backend/scripts/patch_v320h_oca_close_finalize.py.

This generator is a DEV-ONLY tool (not deployed to DGX). It exists so the
emitted patcher's base64 chunks are byte-exact and the POST_SHA matches a
real apply.
"""
import base64
import hashlib
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
PM = HERE.parent / "services" / "position_manager.py"
OUT = HERE / "patch_v320h_oca_close_finalize.py"

PRE_SHA = "ee4f3f2ef837391e4b563b0a6dc48b0860c4b6b0fa19e2b4203f226f89117977"

# ---- anchor chunk (exact bytes; verified unique via _trade.remaining_shares) ----
PREFIX = (
    "                                try:\n"
    "                                    _trade.remaining_shares = 0\n"
    "                                except Exception:\n"
    "                                    pass\n"
)
SUFFIX = (
    "                                try:\n"
    "                                    await asyncio.to_thread(bot._persist_trade, _trade)"
)

# ---- the inserted finalize block (32-space base indent) ----
FINALIZE = '''                                # ── v19.34.320h — OCA close-path accounting finalize ── BEGIN ──
                                # The v19.31 external-close sweep above marks the trade CLOSED and
                                # claims realized_pnl, but historically left exit_price unset, net_pnl
                                # stuck at the -$1.00 commission-min sentinel, and pnl_pct stale.
                                # Source exit_price from the matching IB execution (±15m of close),
                                # recompute net_pnl = realized_pnl - total_commissions, and pnl_pct
                                # off the entry basis. Gated by V320H_OCA_FIX_POLICY
                                # (observe|fix|off, default observe).
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
                                        _close_side = "BUY" if _v320h_dir == "short" else "SELL"
                                        _exit_px = None
                                        _exit_src = None
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
                                                _want = int(getattr(_trade, "shares", 0) or 0)
                                                _best = None
                                                _best_score = None
                                                for _ex in _execs:
                                                    _eside = str(_ex.get("side") or _ex.get("action") or "").upper()
                                                    if _close_side == "SELL" and not _eside.startswith(("S",)):
                                                        continue
                                                    if _close_side == "BUY" and not _eside.startswith(("B",)):
                                                        continue
                                                    _epx = float(_ex.get("price") or _ex.get("avg_price")
                                                                 or _ex.get("fill_price") or 0)
                                                    if _epx <= 0:
                                                        continue
                                                    _eqty = int(abs(float(_ex.get("shares") or _ex.get("qty") or 0)))
                                                    _score = abs(_eqty - _want)
                                                    if _best_score is None or _score < _best_score:
                                                        _best_score = _score
                                                        _best = _epx
                                                if _best is not None:
                                                    _exit_px = round(_best, 4)
                                                    _exit_src = "ib_executions"
                                        except Exception as _v320h_lk:
                                            logger.debug("[v19.34.320h] ib_executions probe threw: %s", _v320h_lk)
                                        if _exit_px is None:
                                            _cp = float(getattr(_trade, "current_price", 0) or 0)
                                            if _cp > 0:
                                                _exit_px = round(_cp, 4)
                                                _exit_src = "current_price_fallback"
                                        _new_net = round(float(getattr(_trade, "realized_pnl", 0) or 0)
                                                         - float(getattr(_trade, "total_commissions", 0) or 0), 2)
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
                                                "net_pnl=%.2f pnl_pct=%s trade_id=%s",
                                                _trade.symbol, _v320h_dir.upper(), _exit_px, _exit_src,
                                                _new_net, _new_pct, _trade.id)
                                        else:
                                            logger.info(
                                                "👁️ [v19.34.320h OBSERVE] %s %s would finalize: exit_price=%s (%s) "
                                                "net_pnl=%.2f pnl_pct=%s (cur net_pnl=%s exit_price=%s) trade_id=%s",
                                                _trade.symbol, _v320h_dir.upper(), _exit_px, _exit_src,
                                                _new_net, _new_pct,
                                                getattr(_trade, "net_pnl", None),
                                                getattr(_trade, "exit_price", None), _trade.id)
                                except Exception as _v320h_err:
                                    logger.debug("[v19.34.320h] finalize block threw (non-fatal): %s", _v320h_err)
                                # ── v19.34.320h — OCA close-path accounting finalize ── END ──
'''

OLD = PREFIX + SUFFIX
NEW = PREFIX + FINALIZE + SUFFIX


def main():
    src = PM.read_text(encoding="utf-8")
    pre = hashlib.sha256(src.encode("utf-8")).hexdigest()
    assert pre == PRE_SHA, f"PRE_SHA mismatch: {pre}"
    assert src.count(OLD) == 1, f"OLD chunk not unique: count={src.count(OLD)}"
    new_src = src.replace(OLD, NEW, 1)
    post = hashlib.sha256(new_src.encode("utf-8")).hexdigest()
    # sanity: new content compiles
    compile(new_src, "position_manager.py", "exec")

    old_b64 = base64.b64encode(OLD.encode("utf-8")).decode("ascii")
    new_b64 = base64.b64encode(NEW.encode("utf-8")).decode("ascii")

    patcher = PATCHER_TEMPLATE.format(
        pre_sha=PRE_SHA, post_sha=post, old_b64=old_b64, new_b64=new_b64)
    OUT.write_text(patcher, encoding="utf-8")
    print(f"PRE_SHA  = {PRE_SHA}")
    print(f"POST_SHA = {post}")
    print(f"OLD len  = {len(OLD)}  NEW len = {len(NEW)}")
    print(f"emitted  -> {OUT}  ({len(patcher):,} bytes)")


PATCHER_TEMPLATE = r'''#!/usr/bin/env python3
"""patch_v320h_oca_close_finalize.py  —  v19.34.320h patcher  (2026-06-16)

Finalizes OCA close-path accounting in position_manager.py.

THE BUG (v320h):
  The v19.31 externally-closed phantom sweep (the `oca_closed_externally_v19_31`
  path) marks the trade CLOSED and claims `realized_pnl`, but never finalizes
  `exit_price`, never recomputes `net_pnl` (so it stays at the -$1.00
  commission-min sentinel written by `_apply_commission`), and never refreshes
  `pnl_pct`. Every IB-OCA-closed trade (stops / targets) therefore lands in
  `bot_trades` with corrupt performance metrics (~4 records/hr).

THE FIX:
  Inserts a finalize block immediately BEFORE the `_persist_trade` call in the
  sweep. It:
    1) classifies the close leg (long→SELL, short→BUY),
    2) sources `exit_price` from the matching `ib_executions` fill within ±15m
       of `closed_at` (falls back to last `current_price` mark),
    3) recomputes `net_pnl = realized_pnl - total_commissions`,
    4) recomputes `pnl_pct` off the entry basis (fill_price||entry_price).

  Gated by ENV `V320H_OCA_FIX_POLICY`:
    observe (DEFAULT) — log the would-be finalized values, write nothing.
    fix               — write exit_price / net_pnl / pnl_pct onto the trade.
    off               — skip the block entirely.

AGENTS.md §2.2 COMPLIANCE:
  • PRE_SHA256 guard  : asserts the target file is the canonical baseline.
  • base64 (old,new)  : anchored single-chunk replacement, byte-exact.
  • POST_SHA256 guard : refuses to leave a file whose hash != tested build.
  • auto-backup       : writes a timestamped .bak.* side-file before writing.
  • --check / --apply / --rollback / --status.

LOCAL VALIDATION OVERRIDE:
  Set V320H_PM_TARGET=/path/to/position_manager.py (and/or TAP_REPO_ROOT) to
  point the patcher at a copy for CI/dev validation. On the DGX, leave unset.

DGX DEPLOY (operator):
  curl -sS -o /tmp/patch_v320h.py https://paste.rs/<id>
  .venv/bin/python /tmp/patch_v320h.py --check
  .venv/bin/python /tmp/patch_v320h.py --apply
  # COMMIT BEFORE RESTART (StartTrading.bat git-wipes uncommitted code):
  git add backend/services/position_manager.py && git commit -m "v19.34.320h: OCA close finalize (observe)" && git push origin main
  ./start_backend.sh --force
  # observe a few OCA closes in logs ([v19.34.320h OBSERVE]); when satisfied:
  #   export V320H_OCA_FIX_POLICY=fix   (in the backend env / start script) and restart
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PRE_SHA256 = "{pre_sha}"
POST_SHA256 = "{post_sha}"

REPO_ROOT = Path(os.environ.get("TAP_REPO_ROOT") or (Path.home() / "Trading-and-Analysis-Platform"))
TARGET = Path(os.environ.get("V320H_PM_TARGET") or (REPO_ROOT / "backend" / "services" / "position_manager.py"))

OLD_B64 = "{old_b64}"
NEW_B64 = "{new_b64}"
APPLIED_STAMP = "/tmp/v320h_oca_finalize.applied"

MARKER_OPEN = "# \u2500\u2500 v19.34.320h \u2014 OCA close-path accounting finalize \u2500\u2500 BEGIN \u2500\u2500"
MARKER_CLOSE = "# \u2500\u2500 v19.34.320h \u2014 OCA close-path accounting finalize \u2500\u2500 END \u2500\u2500"


def _old() -> str:
    return base64.b64decode(OLD_B64).decode("utf-8")


def _new() -> str:
    return base64.b64decode(NEW_B64).decode("utf-8")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read() -> str:
    if not TARGET.exists():
        print(f"ERROR: target missing: {{TARGET}}")
        sys.exit(1)
    return TARGET.read_text(encoding="utf-8")


def cmd_check():
    body = _read()
    cur = _sha(body.encode("utf-8"))
    print(f"  target : {{TARGET}}")
    print(f"  size   : {{len(body):,}} chars")
    print(f"  sha    : {{cur}}")
    if MARKER_OPEN in body:
        if cur == POST_SHA256:
            print("  \u2705 ALREADY APPLIED (sha == POST_SHA256). No-op. Use --rollback to revert.")
            sys.exit(0)
        print("  \u26a0\ufe0f  marker present but sha != POST_SHA256 \u2014 file drifted post-apply.")
        sys.exit(4)
    if cur != PRE_SHA256:
        print("  \u274c PRE_SHA256 MISMATCH \u2014 file drifted from canonical baseline.")
        print(f"     expected {{PRE_SHA256}}")
        print(f"     actual   {{cur}}")
        print("     -> ask operator to upload their copy; rebase the patch on it.")
        sys.exit(2)
    old = _old()
    n = body.count(old)
    if n != 1:
        print(f"  \u274c anchor chunk not unique (count={{n}}) \u2014 refusing to write.")
        sys.exit(3)
    projected = body.replace(old, _new(), 1)
    pp = _sha(projected.encode("utf-8"))
    print(f"  \u2713 PRE_SHA256 ok; anchor unique.")
    print(f"  \u2713 projected POST_SHA256 = {{pp}}")
    if pp != POST_SHA256:
        print(f"  \u274c projected sha != embedded POST_SHA256 ({{POST_SHA256}}) \u2014 ABORT.")
        sys.exit(5)
    print("  \u2713 projected hash matches embedded POST_SHA256. Run --apply to write.")


def cmd_apply():
    body = _read()
    cur = _sha(body.encode("utf-8"))
    if MARKER_OPEN in body and cur == POST_SHA256:
        print("  ALREADY APPLIED. No-op.")
        return
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
        print(f"  ABORT: post-patch sha {{pp}} != embedded POST_SHA256. No write.")
        sys.exit(5)
    bak = TARGET.with_suffix(TARGET.suffix + ".bak." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    TARGET.rename(bak)
    TARGET.write_text(new_body, encoding="utf-8")
    Path(APPLIED_STAMP).write_text(
        f"applied_at={{_now_iso()}}\npre={{PRE_SHA256}}\npost={{POST_SHA256}}\nbackup={{bak}}\n")
    print(f"  \u2705 wrote {{TARGET}} ({{len(new_body):,}} chars)")
    print(f"  \u2705 backup at {{bak.name}}")
    print(f"  \u2705 POST_SHA256 verified == {{POST_SHA256}}")
    print("\n  NEXT STEPS:")
    print("    1) COMMIT before any restart (StartTrading.bat git-wipes uncommitted code):")
    print("       git add backend/services/position_manager.py && git commit -m 'v19.34.320h OCA close finalize (observe)' && git push origin main")
    print("    2) ./start_backend.sh --force")
    print("    3) tail logs for [v19.34.320h OBSERVE]; flip V320H_OCA_FIX_POLICY=fix when satisfied")


def cmd_rollback():
    body = _read()
    cur = _sha(body.encode("utf-8"))
    if MARKER_OPEN not in body:
        print("  no v320h marker present \u2014 nothing to roll back.")
        return
    if cur != POST_SHA256:
        print("  \u26a0\ufe0f  file drifted from POST_SHA256; rolling back by exact chunk anyway.")
    new = body.replace(_new(), _old(), 1)
    if new == body:
        print("  WARNING: chunk-revert matched nothing (manual edits?). ABORT.")
        sys.exit(2)
    rp = _sha(new.encode("utf-8"))
    bak = TARGET.with_suffix(TARGET.suffix + ".bak_rollback." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    TARGET.rename(bak)
    TARGET.write_text(new, encoding="utf-8")
    try:
        os.remove(APPLIED_STAMP)
    except FileNotFoundError:
        pass
    print(f"  \u2705 rolled back. patched copy saved at {{bak.name}}")
    print(f"  restored sha = {{rp}}  (PRE_SHA256 == {{PRE_SHA256}}: {{rp == PRE_SHA256}})")


def cmd_status():
    body = _read()
    cur = _sha(body.encode("utf-8"))
    present = MARKER_OPEN in body
    print(f"  target  : {{TARGET}}")
    print(f"  sha     : {{cur}}")
    print(f"  applied : {{present}}  (sha==POST: {{cur == POST_SHA256}}; sha==PRE: {{cur == PRE_SHA256}})")
    print(f"  policy  : V320H_OCA_FIX_POLICY={{os.environ.get('V320H_OCA_FIX_POLICY', 'observe (default)')}}")
    if os.path.exists(APPLIED_STAMP):
        print("  stamp   :\n" + Path(APPLIED_STAMP).read_text())


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    g.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if args.check:
        cmd_check()
    elif args.apply:
        cmd_apply()
    elif args.rollback:
        cmd_rollback()
    elif args.status:
        cmd_status()


if __name__ == "__main__":
    main()
'''


if __name__ == "__main__":
    main()
