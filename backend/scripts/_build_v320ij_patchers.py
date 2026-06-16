#!/usr/bin/env python3
"""_build_v320ij_patchers.py — generators for:
  • patch_v320i_target_order_ids_capture.py   (trade_execution.py)   Issue 5
  • patch_v320j_unrealized_pnl_persist.py      (position_manager.py)  Issue 4

DEV-ONLY. Emits AGENTS.md §2.2 multi-chunk patchers (PRE/POST SHA guards,
base64 (old,new) pairs, --check/--apply/--rollback/--status, auto-backup).
Byte-exact chunks are built/verified here against the canonical files.
"""
import base64
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SVC = HERE.parent / "services"

TE = SVC / "trade_execution.py"
TE_PRE = "f8037748a65d4dde4ca2435f6826f837726653fe8c10423702cd0a7c5aa7eeb4"
PM_DGX_PRE = "90c451329b766f369e03bb0bffb2fcc385e604dd765fb49f5ef9431d0503495d"  # v320h.1 applied


# ───────────────────────── Issue 5 (trade_execution.py) ─────────────────────────
TE_C1_OLD = (
    '                    "target_order_id": bracket_result.get("target_order_id"),\n'
    '                    "oca_group": bracket_result.get("oca_group"),\n'
)
TE_C1_NEW = (
    '                    "target_order_id": bracket_result.get("target_order_id"),\n'
    '                    "target_order_ids": bracket_result.get("target_order_ids"),\n'
    '                    "oca_group": bracket_result.get("oca_group"),\n'
)

TE_C2_OLD = (
    "                if result.get('bracket'):\n"
    "                    trade.stop_order_id = result.get('stop_order_id')\n"
    "                    trade.target_order_id = result.get('target_order_id')\n"
    "                    if result.get('oca_group'):\n"
)
TE_C2_NEW = (
    "                if result.get('bracket'):\n"
    "                    trade.stop_order_id = result.get('stop_order_id')\n"
    "                    trade.target_order_id = result.get('target_order_id')\n"
    "                    # v19.34.320i — also populate the plural target_order_ids\n"
    "                    # list (leg-id source for close/EOD cancel paths + the\n"
    "                    # stop-vs-target classifier). Entry historically set only\n"
    "                    # the singular id, leaving target_order_ids=[] (SATS\n"
    "                    # 2026-06: target hit but list empty -> classifier blind).\n"
    "                    _tids_320i = (result.get('target_order_ids')\n"
    "                                  or ([result.get('target_order_id')] if result.get('target_order_id') else []))\n"
    "                    trade.target_order_ids = [str(_x) for _x in _tids_320i if _x]\n"
    "                    if result.get('oca_group'):\n"
)

TE_C3_OLD = (
    '                if oca.get("target_order_id"):\n'
    '                    trade.target_order_id = oca.get("target_order_id")\n'
    '                trade.oca_group = oca.get("oca_group")\n'
)
TE_C3_NEW = (
    '                if oca.get("target_order_id"):\n'
    '                    trade.target_order_id = oca.get("target_order_id")\n'
    '                    # v19.34.320i — keep the plural list in sync (see entry path).\n'
    '                    _tids_320i = (oca.get("target_order_ids")\n'
    '                                  or [oca.get("target_order_id")])\n'
    '                    trade.target_order_ids = [str(_x) for _x in _tids_320i if _x]\n'
    '                trade.oca_group = oca.get("oca_group")\n'
)


# ───────────────────────── Issue 4 (position_manager.py) ─────────────────────────
PM_C1_OLD = (
    "                # Include realized P&L from partial exits\n"
    "                total_value = trade.remaining_shares * trade.fill_price\n"
    "                if total_value > 0:\n"
    "                    trade.pnl_pct = ((trade.unrealized_pnl + trade.realized_pnl) / (trade.original_shares * trade.fill_price)) * 100\n"
    "\n"
    "                # Update trailing stop if enabled\n"
)
PM_C1_NEW = (
    "                # Include realized P&L from partial exits\n"
    "                total_value = trade.remaining_shares * trade.fill_price\n"
    "                if total_value > 0:\n"
    "                    trade.pnl_pct = ((trade.unrealized_pnl + trade.realized_pnl) / (trade.original_shares * trade.fill_price)) * 100\n"
    "\n"
    "                # v19.34.320j — persist live unrealized_pnl/pnl_pct to Mongo so\n"
    "                # open-position P&L is observable at the DB level (was computed\n"
    "                # in-memory only -> DB showed $0 for all opens). Throttled per\n"
    "                # trade (~20s) to avoid a per-tick write storm.\n"
    "                try:\n"
    "                    import time as _t_320j\n"
    "                    from datetime import datetime as _dt_320j, timezone as _tz_320j\n"
    "                    _last_320j = getattr(trade, \"_v320j_last_pnl_sync\", 0) or 0\n"
    "                    if (_t_320j.time() - _last_320j) >= 20:\n"
    "                        _db_320j = (getattr(bot, \"_db\", None)\n"
    "                                    if getattr(bot, \"_db\", None) is not None\n"
    "                                    else getattr(bot, \"db\", None))\n"
    "                        if _db_320j is not None and getattr(trade, \"id\", None):\n"
    "                            await asyncio.to_thread(\n"
    "                                _db_320j.bot_trades.update_one,\n"
    "                                {\"id\": trade.id},\n"
    "                                {\"$set\": {\n"
    "                                    \"unrealized_pnl\": float(getattr(trade, \"unrealized_pnl\", 0) or 0),\n"
    "                                    \"pnl_pct\": float(getattr(trade, \"pnl_pct\", 0) or 0),\n"
    "                                    \"current_price\": float(getattr(trade, \"current_price\", 0) or 0),\n"
    "                                    \"unrealized_pnl_synced_at\": _dt_320j.now(_tz_320j.utc).isoformat(),\n"
    "                                }},\n"
    "                            )\n"
    "                            trade._v320j_last_pnl_sync = _t_320j.time()\n"
    "                except Exception as _e_320j:\n"
    "                    logger.debug(\"[v19.34.320j] unrealized_pnl persist threw: %s\", _e_320j)\n"
    "\n"
    "                # Update trailing stop if enabled\n"
)


TEMPLATE = r'''#!/usr/bin/env python3
"""@@FILENAME@@  —  @@VERSION@@ patcher  (2026-06-16)

@@DOCSTRING@@

AGENTS.md §2.2: PRE_SHA256 + POST_SHA256 guards, base64 (old,new) chunk pairs
applied in order (each must be unique), auto-backup, --check/--apply/--rollback
/--status. Local override via @@TARGET_ENV@@ / TAP_REPO_ROOT.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PRE_SHA256 = "@@PRE_SHA@@"
POST_SHA256 = "@@POST_SHA@@"
SENTINEL = "@@SENTINEL@@"

REPO_ROOT = Path(os.environ.get("TAP_REPO_ROOT") or (Path.home() / "Trading-and-Analysis-Platform"))
TARGET = Path(os.environ.get("@@TARGET_ENV@@") or (REPO_ROOT / "@@TARGET_REL@@"))

# list of [old_b64, new_b64] applied in order
CHUNKS = @@CHUNKS@@
APPLIED_STAMP = "@@STAMP@@"


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _read():
    if not TARGET.exists():
        print("ERROR: target missing:", TARGET)
        sys.exit(1)
    return TARGET.read_text(encoding="utf-8")


def _apply_all(body):
    for old_b64, new_b64 in CHUNKS:
        old = base64.b64decode(old_b64).decode("utf-8")
        new = base64.b64decode(new_b64).decode("utf-8")
        if body.count(old) != 1:
            return None, "anchor not unique (count=%d)" % body.count(old)
        body = body.replace(old, new, 1)
    return body, None


def _revert_all(body):
    for old_b64, new_b64 in reversed(CHUNKS):
        old = base64.b64decode(old_b64).decode("utf-8")
        new = base64.b64decode(new_b64).decode("utf-8")
        if body.count(new) != 1:
            return None, "patched chunk not unique (count=%d)" % body.count(new)
        body = body.replace(new, old, 1)
    return body, None


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
    if cur != PRE_SHA256:
        print("  PRE_SHA256 MISMATCH — file drifted from canonical baseline.")
        print("    expected", PRE_SHA256)
        print("    actual  ", cur)
        print("    -> upload your copy and ask for a rebase.")
        sys.exit(2)
    projected, err = _apply_all(body)
    if err:
        print("  ABORT:", err)
        sys.exit(3)
    pp = _sha(projected.encode("utf-8"))
    print("  PRE_SHA256 ok; all %d anchors unique." % len(CHUNKS))
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
    if cur != PRE_SHA256:
        print("  ABORT: PRE_SHA256 mismatch. Run --check.")
        sys.exit(2)
    new_body, err = _apply_all(body)
    if err:
        print("  ABORT:", err)
        sys.exit(3)
    pp = _sha(new_body.encode("utf-8"))
    if pp != POST_SHA256:
        print("  ABORT: post-patch sha %s != embedded POST_SHA256. No write." % pp)
        sys.exit(5)
    bak = TARGET.with_suffix(TARGET.suffix + ".bak." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    TARGET.rename(bak)
    TARGET.write_text(new_body, encoding="utf-8")
    Path(APPLIED_STAMP).write_text("applied_at=%s\npre=%s\npost=%s\nbackup=%s\n" % (
        datetime.now(timezone.utc).isoformat(), PRE_SHA256, POST_SHA256, bak))
    print("  wrote", TARGET, "(%d chars)" % len(new_body))
    print("  backup at", bak.name)
    print("  POST_SHA256 verified ==", POST_SHA256)
    print("\n  NEXT: git add @@TARGET_REL@@ && git commit -m '@@VERSION@@' && git push origin main")
    print("        ./start_backend.sh --force")


def cmd_rollback():
    body = _read()
    if SENTINEL not in body:
        print("  no @@VERSION@@ sentinel present — nothing to roll back.")
        return
    new, err = _revert_all(body)
    if err:
        print("  ABORT:", err)
        sys.exit(2)
    rp = _sha(new.encode("utf-8"))
    bak = TARGET.with_suffix(TARGET.suffix + ".bak_rollback." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    TARGET.rename(bak)
    TARGET.write_text(new, encoding="utf-8")
    try:
        os.remove(APPLIED_STAMP)
    except FileNotFoundError:
        pass
    print("  rolled back. patched copy at", bak.name)
    print("  restored sha =", rp, " (== PRE_SHA256:", rp == PRE_SHA256, ")")


def cmd_status():
    body = _read()
    cur = _sha(body.encode("utf-8"))
    print("  target  :", TARGET)
    print("  sha     :", cur)
    print("  applied :", SENTINEL in body, " (sha==POST:", cur == POST_SHA256, "; sha==PRE:", cur == PRE_SHA256, ")")
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


def _b64(s):
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def emit(out_name, version, filename, docstring, target_env, target_rel,
         sentinel, stamp, pre_sha, src, chunks):
    assert _sha_str(src) == pre_sha, f"{out_name}: PRE mismatch {_sha_str(src)}"
    body = src
    for old, new in chunks:
        assert body.count(old) == 1, f"{out_name}: chunk not unique"
        body = body.replace(old, new, 1)
    post = _sha_str(body)
    compile(body, filename, "exec")
    chunks_lit = "[\n" + ",\n".join(
        f'    ["{_b64(o)}",\n     "{_b64(n)}"]' for o, n in chunks) + ",\n]"
    out = (TEMPLATE
           .replace("@@FILENAME@@", out_name)
           .replace("@@VERSION@@", version)
           .replace("@@DOCSTRING@@", docstring)
           .replace("@@TARGET_ENV@@", target_env)
           .replace("@@TARGET_REL@@", target_rel)
           .replace("@@SENTINEL@@", sentinel)
           .replace("@@STAMP@@", stamp)
           .replace("@@PRE_SHA@@", pre_sha)
           .replace("@@POST_SHA@@", post)
           .replace("@@CHUNKS@@", chunks_lit))
    (HERE / out_name).write_text(out, encoding="utf-8")
    print(f"{out_name}: PRE={pre_sha[:12]} POST={post[:12]} chunks={len(chunks)} -> {len(out):,}b")
    return post


def _sha_str(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def main():
    # Issue 5
    emit(
        "patch_v320i_target_order_ids_capture.py", "v19.34.320i",
        "patch_v320i_target_order_ids_capture.py",
        ("Issue 5 fix: the entry/bracket path stamped only the SINGULAR\\n"
         "trade.target_order_id and left the PLURAL trade.target_order_ids=[]\\n"
         "(SATS 2026-06: OCA target hit but list empty -> stop-vs-target leg\\n"
         "classifier blind). Carries target_order_ids through the result dict\\n"
         "and populates trade.target_order_ids at both the entry-stamp and the\\n"
         "v322l reclaim sites. trade_execution.py."),
        "V320I_TE_TARGET", "backend/services/trade_execution.py",
        "v19.34.320i", "/tmp/v320i_target_ids.applied",
        TE_PRE, TE.read_text(encoding="utf-8"),
        [(TE_C1_OLD, TE_C1_NEW), (TE_C2_OLD, TE_C2_NEW), (TE_C3_OLD, TE_C3_NEW)],
    )
    # Issue 4 — reconstruct DGX v320h.1 state for position_manager.py
    import _build_v320h_patcher as v0
    import _build_v320h1_patcher as v1
    pm_base = (SVC / "position_manager.py").read_text(encoding="utf-8")
    pm_dgx = pm_base.replace(v0.OLD, v0.NEW, 1).replace(v0.FINALIZE, v1.FINALIZE_V2, 1)
    emit(
        "patch_v320j_unrealized_pnl_persist.py", "v19.34.320j",
        "patch_v320j_unrealized_pnl_persist.py",
        ("Issue 4 fix: manage_open_trades computed trade.unrealized_pnl /\\n"
         "pnl_pct in-memory each tick but never persisted them, so Mongo kept\\n"
         "the creation-time $0 for all open positions. Adds a THROTTLED (~20s/\\n"
         "trade) targeted update_one of {unrealized_pnl, pnl_pct, current_price,\\n"
         "unrealized_pnl_synced_at}. No new asyncio loop. position_manager.py\\n"
         "(targets the v320h.1-applied state, PRE 90c45132)."),
        "V320H_PM_TARGET", "backend/services/position_manager.py",
        "v19.34.320j", "/tmp/v320j_unrealized_persist.applied",
        PM_DGX_PRE, pm_dgx,
        [(PM_C1_OLD, PM_C1_NEW)],
    )


if __name__ == "__main__":
    main()
