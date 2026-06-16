#!/usr/bin/env python3
"""Dev-only generator for the v19.34.320m PATCH-L2a event-loop-spam patcher.

Emits a self-contained, §2.2-compliant patcher (PRE/POST SHA256 guards,
base64 anchored chunk replacements, auto-backup,
--check/--apply/--rollback/--status) to /tmp/patch_v320m.py.

Two chunks — both wrap the SYNC ib_async reqAllOpenOrders() in
asyncio.to_thread(), which runs it in a worker thread that has no event
loop, so ib_async's internal util.run()/get_event_loop() raised
"no current event loop in thread 'ThreadPoolExecutor-N'":
  1. get_open_orders()                  (the recurring [v19.34.28 PATCH-L2a] spam)
  2. cancel_all_open_orders_for_symbol() (v19.34.46 — same bug, order-cancel path)

Run from /app/backend:  .venv/bin/python scripts/_build_v320m_patcher.py
"""
import base64
import hashlib
import os
import sys

REL_TARGET = "services/ib_direct_service.py"

OLD1 = (
    '            try:\n'
    '                await asyncio.to_thread(self._ib.reqAllOpenOrders)\n'
    '                # Brief settle for openOrder callbacks to land in cache.\n'
    '                await asyncio.sleep(0.5)\n'
    '            except Exception as e:\n'
    '                logger.warning(\n'
    '                    "[v19.34.28 PATCH-L2a] get_open_orders reqAllOpenOrders "\n'
    '                    "soft-failed (continuing with cached trades): %s", e,\n'
    '                )'
)

NEW1 = (
    '            try:\n'
    '                # v19.34.320m — call the NATIVE async coroutine ON the event\n'
    '                # loop. The previous code wrapped the SYNC reqAllOpenOrders()\n'
    '                # in asyncio.to_thread(), running it in a worker thread that\n'
    '                # has NO event loop, so ib_async\'s internal util.run() /\n'
    '                # get_event_loop() raised "no current event loop in thread\n'
    '                # \'ThreadPoolExecutor-N\'" on EVERY call (recurring log spam,\n'
    '                # and the working-orders refresh silently no-op\'d).\n'
    '                _req_async = getattr(self._ib, "reqAllOpenOrdersAsync", None)\n'
    '                if _req_async is not None:\n'
    '                    await _req_async()\n'
    '                    # Brief settle for openOrder callbacks to land in cache.\n'
    '                    await asyncio.sleep(0.5)\n'
    '                else:\n'
    '                    logger.warning(\n'
    '                        "[v19.34.320m PATCH-L2a] reqAllOpenOrdersAsync missing "\n'
    '                        "on this ib_async build; using cached trades (the sync "\n'
    '                        "reqAllOpenOrders() is unsafe inside a running loop)"\n'
    '                    )\n'
    '            except Exception as e:\n'
    '                logger.warning(\n'
    '                    "[v19.34.28 PATCH-L2a] get_open_orders reqAllOpenOrders "\n'
    '                    "soft-failed (continuing with cached trades): %s", e,\n'
    '                )'
)

OLD2 = (
    '            try:\n'
    '                await asyncio.to_thread(self._ib.reqAllOpenOrders)\n'
    '                # Brief settle so callbacks populate self._ib.trades()\n'
    '                await asyncio.sleep(0.5)\n'
    '            except Exception as e:\n'
    '                logger.warning(\n'
    '                    "v19.34.46 [IB-DIRECT] reqAllOpenOrders failed for %s: %s",\n'
    '                    symbol, e,\n'
    '                )'
)

NEW2 = (
    '            try:\n'
    '                # v19.34.320m — native async coroutine on the loop (was a\n'
    '                # SYNC reqAllOpenOrders() wrapped in asyncio.to_thread, which\n'
    '                # ran in a worker thread with no event loop -> RuntimeError\n'
    '                # "no current event loop in thread \'ThreadPoolExecutor-N\'").\n'
    '                _req_async = getattr(self._ib, "reqAllOpenOrdersAsync", None)\n'
    '                if _req_async is not None:\n'
    '                    await _req_async()\n'
    '                    # Brief settle so callbacks populate self._ib.trades()\n'
    '                    await asyncio.sleep(0.5)\n'
    '                else:\n'
    '                    logger.warning(\n'
    '                        "v19.34.320m [IB-DIRECT] reqAllOpenOrdersAsync missing "\n'
    '                        "for %s; using cached trades", symbol,\n'
    '                    )\n'
    '            except Exception as e:\n'
    '                logger.warning(\n'
    '                    "v19.34.46 [IB-DIRECT] reqAllOpenOrders failed for %s: %s",\n'
    '                    symbol, e,\n'
    '                )'
)

CHUNKS = [(OLD1, NEW1), (OLD2, NEW2)]


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # /app/backend
    target = os.path.join(here, REL_TARGET)
    src = open(target, "r", encoding="utf-8").read()

    for i, (old, _new) in enumerate(CHUNKS, 1):
        n = src.count(old)
        if n != 1:
            print(f"ABORT: chunk {i} OLD anchor found {n} times (need exactly 1)", file=sys.stderr)
            sys.exit(2)

    pre_sha = hashlib.sha256(src.encode("utf-8")).hexdigest()
    post_src = src
    for old, new in CHUNKS:
        post_src = post_src.replace(old, new, 1)
    post_sha = hashlib.sha256(post_src.encode("utf-8")).hexdigest()

    chunks_b64 = [
        (base64.b64encode(o.encode()).decode(), base64.b64encode(n.encode()).decode())
        for o, n in CHUNKS
    ]
    chunks_repr = "[\n" + "".join(
        f'    ("{o}", "{n}"),\n' for o, n in chunks_b64
    ) + "]"

    patcher = PATCHER_TEMPLATE.format(
        rel_target=REL_TARGET,
        pre_sha=pre_sha,
        post_sha=post_sha,
        chunks_repr=chunks_repr,
    )
    out = "/tmp/patch_v320m.py"
    with open(out, "w", encoding="utf-8") as f:
        f.write(patcher)
    print(f"PRE_SHA256  = {pre_sha}")
    print(f"POST_SHA256 = {post_sha}")
    print(f"chunks      = {len(CHUNKS)}")
    print(f"wrote {out} ({len(patcher)} bytes)")


PATCHER_TEMPLATE = r'''#!/usr/bin/env python3
"""v19.34.320m — PATCH-L2a "no current event loop" log-spam + cancel-path fix.

Target: backend/{rel_target}

ROOT CAUSE
----------
Two methods refreshed IB's working-order cache with
    await asyncio.to_thread(self._ib.reqAllOpenOrders)
reqAllOpenOrders() is a SYNC ib_async method; internally it calls
util.run()/asyncio.get_event_loop(). asyncio.to_thread runs it in a
ThreadPoolExecutor worker thread that has NO event loop, so every call
raised RuntimeError "no current event loop in thread 'ThreadPoolExecutor-N'":
  1. get_open_orders()  -> logged "[v19.34.28 PATCH-L2a] get_open_orders
     reqAllOpenOrders soft-failed ..." multiple times per minute (naked-sweep /
     working-order audit cadence); the authoritative refresh silently no-op'd.
  2. cancel_all_open_orders_for_symbol() -> same failure on the order-cancel
     refresh (v19.34.46); silently fell back to the per-clientId trades cache.

FIX
---
Call the NATIVE coroutine self._ib.reqAllOpenOrdersAsync() directly on the
running loop (same convention as get_positions_fresh -> reqPositionsAsync and
get_account_summary -> accountSummaryAsync already in this file). Defensive
getattr fallback logs once if the async variant is absent.

SAFETY
------
Read/refresh + diagnostic paths. Does NOT touch close_trade,
submit_with_bracket, _cancel_ib_bracket_orders, the kill-switch, or any
_open_trades write. §2.2: PRE/POST SHA256 guards, base64 anchored chunks,
auto-backup, --check/--apply/--rollback/--status, py_compile gate.

USAGE (DGX)
-----------
  curl -sS -o /tmp/patch_v320m.py https://paste.rs/<id>
  .venv/bin/python /tmp/patch_v320m.py --check
  .venv/bin/python /tmp/patch_v320m.py --apply
  git add backend/{rel_target} && git commit -m "v19.34.320m: PATCH-L2a event-loop spam fix" && git push origin main
  ./start_backend.sh --force
  # rollback if needed:
  .venv/bin/python /tmp/patch_v320m.py --rollback
"""
import base64
import hashlib
import os
import sys

REL_TARGET = "{rel_target}"
PRE_SHA256 = "{pre_sha}"
POST_SHA256 = "{post_sha}"
CHUNKS_B64 = {chunks_repr}


def _resolve_target():
    override = os.environ.get("V320M_TARGET")
    if override and os.path.isfile(override):
        return override
    cwd = os.getcwd()
    candidates = [os.path.join(cwd, "backend", REL_TARGET), os.path.join(cwd, REL_TARGET)]
    p = cwd
    for _ in range(6):
        candidates.append(os.path.join(p, "backend", REL_TARGET))
        p = os.path.dirname(p)
    for c in candidates:
        if os.path.isfile(c):
            return c
    return os.path.join(cwd, "backend", REL_TARGET)


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _chunks():
    return [(base64.b64decode(o).decode("utf-8"), base64.b64decode(n).decode("utf-8"))
            for o, n in CHUNKS_B64]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    target = _resolve_target()
    chunks = _chunks()

    if mode == "--status":
        if not os.path.isfile(target):
            print(f"target NOT FOUND: {{target}}"); sys.exit(1)
        cur = _sha(open(target, encoding="utf-8").read())
        print(f"target : {{target}}")
        print(f"current: {{cur}}")
        print(f"PRE    : {{PRE_SHA256}}  {{'<= UNPATCHED' if cur == PRE_SHA256 else ''}}")
        print(f"POST   : {{POST_SHA256}}  {{'<= PATCHED' if cur == POST_SHA256 else ''}}")
        sys.exit(0)

    if mode == "--rollback":
        bak = target + ".bak_v320m"
        if not os.path.isfile(bak):
            print(f"ABORT: no backup at {{bak}}"); sys.exit(1)
        data = open(bak, encoding="utf-8").read()
        if _sha(data) != PRE_SHA256:
            print("ABORT: backup hash != PRE_SHA256 (refusing to restore drift)"); sys.exit(1)
        with open(target, "w", encoding="utf-8") as f:
            f.write(data)
        print(f"ROLLED BACK from {{bak}} (restored PRE_SHA256)"); sys.exit(0)

    if not os.path.isfile(target):
        print(f"ABORT: target NOT FOUND: {{target}}"); sys.exit(1)
    src = open(target, encoding="utf-8").read()
    cur = _sha(src)

    if cur == POST_SHA256:
        print("ALREADY PATCHED (current == POST_SHA256). No-op."); sys.exit(0)
    if cur != PRE_SHA256:
        print("ABORT: PRE_SHA256 mismatch — DGX file has drifted.")
        print(f"  expected PRE: {{PRE_SHA256}}")
        print(f"  current     : {{cur}}")
        print("  Upload your copy:  curl --data-binary @backend/" + REL_TARGET + " https://paste.rs/")
        print("  and the agent will rebase the patcher on your baseline.")
        sys.exit(3)
    for i, (old, _new) in enumerate(chunks, 1):
        n = src.count(old)
        if n != 1:
            print(f"ABORT: chunk {{i}} anchor found {{n}} times (need exactly 1)"); sys.exit(4)

    patched = src
    for old, new in chunks:
        patched = patched.replace(old, new, 1)
    if _sha(patched) != POST_SHA256:
        print("ABORT: post-replacement hash != POST_SHA256 (would not match tested build)"); sys.exit(5)

    if mode == "--check":
        print("CHECK OK: PRE matches, both anchors unique, POST hash verified.")
        print(f"  target: {{target}}")
        print(f"  PRE  : {{PRE_SHA256}}")
        print(f"  POST : {{POST_SHA256}}")
        sys.exit(0)

    if mode == "--apply":
        bak = target + ".bak_v320m"
        if not os.path.isfile(bak):
            with open(bak, "w", encoding="utf-8") as f:
                f.write(src)
        with open(target, "w", encoding="utf-8") as f:
            f.write(patched)
        import py_compile
        try:
            py_compile.compile(target, doraise=True)
        except py_compile.PyCompileError as e:
            with open(target, "w", encoding="utf-8") as f:
                f.write(src)
            print(f"ABORT: py_compile failed, reverted. {{e}}"); sys.exit(6)
        print(f"APPLIED ({{len(chunks)}} chunks). backup at {{bak}}. POST_SHA256 verified + compiles.")
        sys.exit(0)

    print(f"unknown mode {{mode}} (use --check/--apply/--rollback/--status)"); sys.exit(99)


if __name__ == "__main__":
    main()
'''


if __name__ == "__main__":
    main()
