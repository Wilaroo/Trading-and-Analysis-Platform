#!/usr/bin/env python3
"""Dev-only generator for the v19.34.320r intraday priority-ceiling fix patcher.

CONTEXT (v320q + v320r-precheck diags):
  enhanced_scanner.py hard-codes priority=AlertPriority.MEDIUM in several intraday
  scalp detectors → they can NEVER reach HIGH (the auto-fire bar), regardless of
  signal quality. v320q proved 66.8% of intraday's non-HIGH population is this
  structural ceiling; intraday TQS/in-play/tape are equal-or-better than carry, so
  it's NOT a quality gap. v320r-precheck confirmed the EV gate lets these fire
  (cold-start grace) and correctly blocks proven losers (rs_leader_break).

OPTION B (operator-approved): give the tape-gated HIGH branch to the 3 setups with
neutral-or-better early EV — second_chance, backside, fashionably_late. (big_dog
EXCLUDED: -2.12R/20% over 5; gap_pick_roll EXCLUDED: DGX form unconfirmed / may
already be HIGH-capable — separate follow-up.)

The new branch mirrors the EXISTING intraday pattern exactly:
    priority = AlertPriority.HIGH if tape.confirmation_for_long else AlertPriority.MEDIUM
Only the tape-confirmed subset promotes (the rest stay MEDIUM, unchanged). alert.
tape_confirmation is set from tape.confirmation_for_long (L3985), so the v320q tape
rates (~52-62%) ARE the promotion rates. Auto-fire STILL requires the EV/win-rate
gate, so this is not a force-fire — it removes an artificial priority ceiling.

SAFETY: alert-stamping only. Does NOT touch close_trade / submit_with_bracket /
_cancel_ib_bracket_orders / kill-switch / _open_trades / sizing / brackets.

§2.2: PRE_SHA256 hard guard (DGX v320p baseline 89555e59…), base64 anchored chunks
(each uniquely keyed by setup_type, count==1 asserted), auto-backup,
--check/--apply/--rollback/--status, py_compile gate, marker-based idempotency.

Run from /app/backend:  python3 scripts/_build_v320r_patcher.py
Emits /tmp/patch_v320r.py
"""
import base64

REL_TARGET = "services/enhanced_scanner.py"
# DGX current baseline (from operator sha256sum; == v320p POST). HARD PRE guard.
PRE_SHA256 = "89555e5993e3e7a0c923101c660921ce13342c6d6f53890f092910b655a6ab61"

_CMT = ("# v19.34.320r — tape-gated HIGH branch (was hardcoded MEDIUM, which capped\n"
        "                # this intraday scalp below the auto-fire bar regardless of signal\n"
        "                # quality; see v320q + v320r-precheck). Only the tape-confirmed\n"
        "                # subset promotes; EV/win-rate gate still governs auto-fire.")

# --- second_chance: standalone priority var feeds priority=priority ---
SC_OLD = (
    "            priority = AlertPriority.MEDIUM\n"
    "            \n"
    "            return LiveAlert(\n"
    "                id=f\"second_chance_{symbol}_{datetime.now().strftime('%H%M%S')}\",\n"
    "                symbol=symbol,\n"
    "                setup_type=\"second_chance\",\n"
    "                strategy_name=\"Second Chance Scalp (INT-24)\",\n"
    "                direction=\"long\",\n"
    "                priority=priority,"
)
SC_NEW = (
    "            # v19.34.320r — tape-gated HIGH branch (was hardcoded MEDIUM, which\n"
    "            # capped this intraday scalp below the auto-fire bar regardless of\n"
    "            # signal quality; see v320q + v320r-precheck). Only the tape-confirmed\n"
    "            # subset promotes; EV/win-rate gate still governs auto-fire.\n"
    "            priority = AlertPriority.HIGH if tape.confirmation_for_long else AlertPriority.MEDIUM\n"
    "            \n"
    "            return LiveAlert(\n"
    "                id=f\"second_chance_{symbol}_{datetime.now().strftime('%H%M%S')}\",\n"
    "                symbol=symbol,\n"
    "                setup_type=\"second_chance\",\n"
    "                strategy_name=\"Second Chance Scalp (INT-24)\",\n"
    "                direction=\"long\",\n"
    "                priority=priority,"
)

# --- backside: inline priority=AlertPriority.MEDIUM, in the LiveAlert ---
BS_OLD = (
    "                setup_type=\"backside\",\n"
    "                strategy_name=\"Back$ide Scalp (INT-32)\",\n"
    "                direction=\"long\",\n"
    "                priority=AlertPriority.MEDIUM,"
)
BS_NEW = (
    "                setup_type=\"backside\",\n"
    "                strategy_name=\"Back$ide Scalp (INT-32)\",\n"
    "                direction=\"long\",\n"
    "                " + _CMT + "\n"
    "                priority=AlertPriority.HIGH if tape.confirmation_for_long else AlertPriority.MEDIUM,"
)

# --- fashionably_late: inline priority=AlertPriority.MEDIUM, in the LiveAlert ---
FL_OLD = (
    "                setup_type=\"fashionably_late\",\n"
    "                strategy_name=\"Fashionably Late (INT-26)\",\n"
    "                direction=\"long\",\n"
    "                priority=AlertPriority.MEDIUM,"
)
FL_NEW = (
    "                setup_type=\"fashionably_late\",\n"
    "                strategy_name=\"Fashionably Late (INT-26)\",\n"
    "                direction=\"long\",\n"
    "                " + _CMT + "\n"
    "                priority=AlertPriority.HIGH if tape.confirmation_for_long else AlertPriority.MEDIUM,"
)

CHUNKS = [
    ("second_chance", SC_OLD, SC_NEW),
    ("backside", BS_OLD, BS_NEW),
    ("fashionably_late", FL_OLD, FL_NEW),
]


def main():
    chunk_lits = []
    for name, old, new in CHUNKS:
        chunk_lits.append(
            "    {\n"
            f"        \"name\": {name!r},\n"
            f"        \"old_b64\": {base64.b64encode(old.encode()).decode()!r},\n"
            f"        \"new_b64\": {base64.b64encode(new.encode()).decode()!r},\n"
            "    },"
        )
    chunks_block = "CHUNKS = [\n" + "\n".join(chunk_lits) + "\n]"
    patcher = TEMPLATE.replace("__REL_TARGET__", REL_TARGET) \
                      .replace("__PRE_SHA__", PRE_SHA256) \
                      .replace("# __CHUNKS__", chunks_block)
    open("/tmp/patch_v320r.py", "w").write(patcher)
    # local self-validation of the template python
    import py_compile
    py_compile.compile("/tmp/patch_v320r.py", doraise=True)
    print(f"PRE_SHA256 = {PRE_SHA256}")
    print(f"chunks = {len(CHUNKS)} ({', '.join(c[0] for c in CHUNKS)})")
    print(f"wrote /tmp/patch_v320r.py ({len(patcher)} bytes); patcher compiles OK")


TEMPLATE = r'''#!/usr/bin/env python3
"""v19.34.320r — intraday scalp priority-ceiling fix (tape-gated HIGH branch).

Target: backend/__REL_TARGET__

Three intraday scalp detectors (_check_second_chance, _check_backside,
_check_fashionably_late) hard-coded priority=AlertPriority.MEDIUM, so they could
NEVER reach HIGH — the auto-fire bar (_auto_execute_min_priority = HIGH) — no
matter how strong the signal. v320q proved this structural ceiling is 66.8% of
intraday's non-HIGH population, while intraday TQS/in-play/tape are equal-or-better
than carry (NOT a quality gap). This gives those 3 setups the SAME tape-gated HIGH
branch the other intraday setups already use:

    priority = AlertPriority.HIGH if tape.confirmation_for_long else AlertPriority.MEDIUM

Only the tape-confirmed subset promotes (the rest stay MEDIUM, unchanged). Auto-
execution STILL requires the EV/win-rate gate (verified: it passes these on the
cold-start grace window and auto-blocks proven losers), so this is NOT a force-fire
— it removes an artificial priority ceiling so the existing quality gates can
decide. Net effect: more tape-confirmed intraday scalps become auto-fire-eligible
(the operator's stated goal: more intraday, fewer multi-day).

EXCLUDED from this patch (operator option B): big_dog (-2.12R/20% over 5 trades),
gap_pick_roll (DGX form unconfirmed). Revisit separately.

SAFETY: alert-stamping only (LiveAlert.priority at creation). Does NOT touch
close_trade / submit_with_bracket / _cancel_ib_bracket_orders / kill-switch /
_open_trades / sizing / brackets.

§2.2: PRE_SHA256 hard guard, base64 anchored chunks (each uniquely keyed by
setup_type, count==1 asserted), auto-backup, --check/--apply/--rollback/--status,
py_compile gate, marker-based idempotency.

USAGE (DGX):
  curl -sS -o /tmp/patch_v320r.py https://paste.rs/<id>
  .venv/bin/python /tmp/patch_v320r.py --check
  .venv/bin/python /tmp/patch_v320r.py --apply
  git add backend/__REL_TARGET__ && git commit -m "v19.34.320r: intraday scalp priority-ceiling fix" && git push origin main
  ./start_backend.sh --force
  # rollback: .venv/bin/python /tmp/patch_v320r.py --rollback
"""
import base64, hashlib, os, sys

REL_TARGET = "__REL_TARGET__"
PRE_SHA256 = "__PRE_SHA__"

# __CHUNKS__

_MARKER = "v19.34.320r"


def _resolve_target():
    o = os.environ.get("V320R_TARGET")
    if o and os.path.isfile(o):
        return o
    cwd = os.getcwd()
    cands = [os.path.join(cwd, "backend", REL_TARGET), os.path.join(cwd, REL_TARGET)]
    p = cwd
    for _ in range(6):
        cands.append(os.path.join(p, "backend", REL_TARGET)); p = os.path.dirname(p)
    for c in cands:
        if os.path.isfile(c):
            return c
    return os.path.join(cwd, "backend", REL_TARGET)


def _sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def _decoded():
    out = []
    for c in CHUNKS:
        out.append((c["name"],
                    base64.b64decode(c["old_b64"]).decode(),
                    base64.b64decode(c["new_b64"]).decode()))
    return out


def _chunk_states(src):
    """For each chunk: ('old' | 'new' | 'missing' | 'ambiguous')."""
    states = []
    for name, old, new in _decoded():
        oc, nc = src.count(old), src.count(new)
        if oc == 1:
            states.append((name, "old"))
        elif oc == 0 and nc >= 1:
            states.append((name, "new"))
        elif oc == 0 and nc == 0:
            states.append((name, "missing"))
        else:
            states.append((name, "ambiguous"))
    return states


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    t = _resolve_target()

    if mode == "--status":
        if not os.path.isfile(t):
            print(f"target NOT FOUND: {t}"); sys.exit(1)
        body = open(t, encoding="utf-8").read()
        print(f"target : {t}")
        print(f"current: {_sha(body)}")
        print(f"PRE    : {PRE_SHA256}  {'<= UNPATCHED baseline' if _sha(body)==PRE_SHA256 else ''}")
        for name, st in _chunk_states(body):
            print(f"  chunk {name:<18} -> {st}")
        sys.exit(0)

    if mode == "--rollback":
        bak = t + ".bak_v320r"
        if not os.path.isfile(bak):
            print(f"ABORT: no backup at {bak}"); sys.exit(1)
        data = open(bak, encoding="utf-8").read()
        if _sha(data) != PRE_SHA256:
            print("ABORT: backup hash != PRE_SHA256 (refusing to restore an unexpected file)")
            sys.exit(1)
        open(t, "w", encoding="utf-8").write(data)
        print(f"ROLLED BACK from {bak} (restored PRE_SHA256)"); sys.exit(0)

    if not os.path.isfile(t):
        print(f"ABORT: target NOT FOUND: {t}"); sys.exit(1)
    src = open(t, encoding="utf-8").read()
    cur = _sha(src)
    states = _chunk_states(src)

    # idempotency: every chunk already in NEW form
    if all(st == "new" for _, st in states):
        print("ALREADY PATCHED (all chunks in NEW form). No-op."); sys.exit(0)

    # any ambiguous/missing anchor -> abort (safe)
    bad = [n for n, st in states if st in ("missing", "ambiguous")]
    if bad:
        print("ABORT: anchor problem on chunk(s): " + ", ".join(bad))
        for n, st in states:
            print(f"  {n:<18} {st}")
        print("  → DGX file differs from the reviewed baseline for these blocks.")
        print("  Re-send the detector context so the patcher can be rebased.")
        sys.exit(4)

    # all anchors are OLD and unique -> require exact PRE baseline
    if cur != PRE_SHA256:
        print("ABORT: PRE_SHA256 mismatch — DGX file has drifted from the reviewed baseline.")
        print(f"  expected PRE: {PRE_SHA256}")
        print(f"  current     : {cur}")
        print("  Re-confirm with: sha256sum backend/" + REL_TARGET + "  and re-send so it can be rebased.")
        sys.exit(3)

    patched = src
    for name, old, new in _decoded():
        if patched.count(old) != 1:
            print(f"ABORT: chunk {name} anchor count {patched.count(old)} (need 1)"); sys.exit(5)
        patched = patched.replace(old, new, 1)
    post = _sha(patched)

    if mode == "--check":
        print("CHECK OK: PRE matches, all 3 anchors unique. POST deterministic via PRE+anchors.")
        print(f"  target: {t}")
        print(f"  PRE  : {PRE_SHA256}")
        print(f"  POST : {post} (computed)")
        for name, _o, _n in _decoded():
            print(f"  chunk {name:<18} ready")
        sys.exit(0)

    if mode == "--apply":
        bak = t + ".bak_v320r"
        if not os.path.isfile(bak):
            open(bak, "w", encoding="utf-8").write(src)
        open(t, "w", encoding="utf-8").write(patched)
        import py_compile
        try:
            py_compile.compile(t, doraise=True)
        except py_compile.PyCompileError as e:
            open(t, "w", encoding="utf-8").write(src)
            print(f"ABORT: py_compile failed, reverted to PRE. {e}"); sys.exit(6)
        print(f"APPLIED 3 chunks. backup at {bak}. resulting sha256 = {post}; compiles OK.")
        print("Next: git add/commit/push, then ./start_backend.sh --force")
        sys.exit(0)

    print(f"unknown mode {mode}"); sys.exit(99)


if __name__ == "__main__":
    main()
'''


if __name__ == "__main__":
    main()
