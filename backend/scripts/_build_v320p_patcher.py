#!/usr/bin/env python3
"""Dev-only generator for the v19.34.320p A+→multi_day horizon-hijack fix patcher.

enhanced_scanner.py L748-750 force-stamped trade_style="multi_day" + 5R on ANY
A+ alert, hijacking intraday/scalp-natured setups into overnight carries
(v320n/v320o diag: ~97 intraday setups/day relabeled, INTRADAY smbA+=0%
vs CARRY smbA+=43%). Fix (option A): only promote to multi_day when the setup
is ALREADY carry-natured; intraday/scalp setups keep their natural horizon +
target so A+ scalps stay intraday and flatten at EOD.

Emits /tmp/patch_v320p.py (§2.2: PRE/POST SHA, base64 anchored chunk,
auto-backup, --check/--apply/--rollback/--status, py_compile gate).

Run from /app/backend:  python3 scripts/_build_v320p_patcher.py
"""
import base64
import hashlib
import os
import sys

REL_TARGET = "services/enhanced_scanner.py"

OLD = (
    '                    if smb_score.is_a_plus:\n'
    '                        self.trade_style = "multi_day"\n'
    '                        self.target_r_multiple = 5.0'
)

NEW = (
    '                    if smb_score.is_a_plus:\n'
    '                        # v19.34.320p — A+ is a QUALITY flag, NOT a HORIZON\n'
    '                        # flag. Previously ANY A+ alert was force-stamped\n'
    '                        # trade_style="multi_day" + 5R, which hijacked\n'
    '                        # intraday/scalp-natured setups (gap_fade,\n'
    '                        # second_chance, backside, opening_drive, ...) into\n'
    '                        # 5R OVERNIGHT carries — simultaneously inflating the\n'
    '                        # multi-day count AND draining the best signals out of\n'
    '                        # the intraday book before they could fire intraday\n'
    '                        # (v320n/v320o diag: ~97 intraday setups/day relabeled;\n'
    '                        # INTRADAY smbA+=0% vs CARRY smbA+=43%). Now we only\n'
    '                        # promote to a multi-day hold when the setup is ALREADY\n'
    '                        # carry-natured; intraday/scalp setups keep their\n'
    '                        # natural horizon + target (option A) so A+ scalps stay\n'
    '                        # intraday and flatten at EOD per the intraday mandate.\n'
    '                        # smb_is_a_plus (quality/priority benefit) still flows.\n'
    '                        _natural_style = (self.trade_style or "").strip().lower()\n'
    '                        if _natural_style in ("multi_day", "swing", "position", "investment"):\n'
    '                            self.trade_style = "multi_day"\n'
    '                            self.target_r_multiple = 5.0'
)


def main():
    # Drift-rebase mode: --pre <sha> uses the operator's baseline; POST is left
    # empty (deterministic given exact PRE + unique anchor; py_compile-gated).
    pre_override = None
    if "--pre" in sys.argv:
        pre_override = sys.argv[sys.argv.index("--pre") + 1].strip()

    if pre_override:
        pre_sha = pre_override
        post_sha = ""  # unknown without the full drifted file; PRE guard suffices
    else:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target = os.path.join(here, REL_TARGET)
        src = open(target, "r", encoding="utf-8").read()
        if src.count(OLD) != 1:
            print(f"ABORT: OLD anchor found {src.count(OLD)} times (need 1)", file=sys.stderr)
            sys.exit(2)
        pre_sha = hashlib.sha256(src.encode()).hexdigest()
        post_src = src.replace(OLD, NEW, 1)
        post_sha = hashlib.sha256(post_src.encode()).hexdigest()
        import py_compile
        tmpf = "/tmp/_v320p_post_check.py"
        open(tmpf, "w").write(post_src)
        py_compile.compile(tmpf, doraise=True)

    patcher = TEMPLATE.format(
        rel_target=REL_TARGET, pre_sha=pre_sha, post_sha=post_sha,
        old_b64=base64.b64encode(OLD.encode()).decode(),
        new_b64=base64.b64encode(NEW.encode()).decode(),
    )
    open("/tmp/patch_v320p.py", "w").write(patcher)
    print(f"PRE_SHA256  = {pre_sha}")
    print(f"POST_SHA256 = {post_sha or '(unset — deterministic via PRE+anchor)'}")
    print(f"wrote /tmp/patch_v320p.py ({len(patcher)} bytes); NEW compiles OK")


TEMPLATE = r'''#!/usr/bin/env python3
"""v19.34.320p — A+ quality flag no longer hijacks intraday horizon.

Target: backend/{rel_target}  (LiveAlert._populate_smb_fields, the
smb_score.is_a_plus branch ~L748).

BUG: any A+ alert was force-stamped trade_style="multi_day" + target 5R,
converting intraday/scalp-natured setups (gap_fade, second_chance, backside,
opening_drive, ...) into 5R OVERNIGHT carries. v320n/v320o diag: ~97 intraday
setups/day relabeled; INTRADAY group showed smbA+=0%% (impossible by nature)
while CARRY showed 43%% — proof the A+ branch was moving intraday winners into
the multi_day bucket BEFORE they could fire intraday. One bug, both symptoms
("too many multi-day" + "not enough scalp/intraday").

FIX (option A): only promote to a multi-day hold when the setup is ALREADY
carry-natured (natural style in multi_day/swing/position/investment). Intraday
/scalp setups keep their natural horizon + target and flatten at EOD. The
smb_is_a_plus quality/priority benefit still flows (set earlier, untouched).

SAFETY: alert-stamping only (LiveAlert.trade_style / target_r_multiple at
creation). Does NOT touch close_trade / submit_with_bracket /
_cancel_ib_bracket_orders / kill-switch / _open_trades. Net effect is FEWER
overnight carries (the safe direction for an intraday mandate). §2.2: PRE/POST
SHA guards, base64 anchored chunk, auto-backup, --check/--apply/--rollback/
--status, py_compile gate.

USAGE (DGX):
  curl -sS -o /tmp/patch_v320p.py https://paste.rs/<id>
  .venv/bin/python /tmp/patch_v320p.py --check
  .venv/bin/python /tmp/patch_v320p.py --apply
  git add backend/{rel_target} && git commit -m "v19.34.320p: A+ no longer hijacks intraday horizon" && git push origin main
  ./start_backend.sh --force
  # rollback: .venv/bin/python /tmp/patch_v320p.py --rollback
"""
import base64, hashlib, os, sys

REL_TARGET = "{rel_target}"
PRE_SHA256 = "{pre_sha}"
POST_SHA256 = "{post_sha}"
OLD_B64 = "{old_b64}"
NEW_B64 = "{new_b64}"


def _resolve_target():
    o = os.environ.get("V320P_TARGET")
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


_NEW_MARKER = "_natural_style = (self.trade_style or"


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    t = _resolve_target()
    old = base64.b64decode(OLD_B64).decode()
    new = base64.b64decode(NEW_B64).decode()
    have_post = bool(POST_SHA256)

    if mode == "--status":
        if not os.path.isfile(t):
            print(f"target NOT FOUND: {{t}}"); sys.exit(1)
        body = open(t, encoding="utf-8").read()
        cur = _sha(body)
        print(f"target : {{t}}")
        print(f"current: {{cur}}")
        print(f"PRE    : {{PRE_SHA256}}  {{'<= UNPATCHED' if cur==PRE_SHA256 else ''}}")
        if have_post:
            print(f"POST   : {{POST_SHA256}}  {{'<= PATCHED' if cur==POST_SHA256 else ''}}")
        else:
            print(f"POST   : (deterministic via PRE+anchor)  "
                  f"{{'<= PATCHED (marker present)' if _NEW_MARKER in body else ''}}")
        sys.exit(0)

    if mode == "--rollback":
        bak = t + ".bak_v320p"
        if not os.path.isfile(bak):
            print(f"ABORT: no backup at {{bak}}"); sys.exit(1)
        data = open(bak, encoding="utf-8").read()
        if _sha(data) != PRE_SHA256:
            print("ABORT: backup hash != PRE_SHA256"); sys.exit(1)
        open(t, "w", encoding="utf-8").write(data)
        print(f"ROLLED BACK from {{bak}}"); sys.exit(0)

    if not os.path.isfile(t):
        print(f"ABORT: target NOT FOUND: {{t}}"); sys.exit(1)
    src = open(t, encoding="utf-8").read()
    cur = _sha(src)
    if have_post and cur == POST_SHA256:
        print("ALREADY PATCHED. No-op."); sys.exit(0)
    if (not have_post) and _NEW_MARKER in src and cur != PRE_SHA256:
        print("ALREADY PATCHED (marker present). No-op."); sys.exit(0)
    if cur != PRE_SHA256:
        print("ABORT: PRE_SHA256 mismatch — DGX file has drifted.")
        print(f"  expected PRE: {{PRE_SHA256}}")
        print(f"  current     : {{cur}}")
        print("  Re-confirm the file with: sha256sum backend/" + REL_TARGET)
        print("  and paste it so the patcher can be rebased.")
        sys.exit(3)
    if src.count(old) != 1:
        print(f"ABORT: anchor found {{src.count(old)}} times (need 1)"); sys.exit(4)
    patched = src.replace(old, new, 1)
    if have_post and _sha(patched) != POST_SHA256:
        print("ABORT: post hash != POST_SHA256"); sys.exit(5)

    if mode == "--check":
        print("CHECK OK: PRE matches, anchor unique"
              + (", POST hash verified." if have_post else ", POST deterministic (PRE+anchor)."))
        print(f"  target: {{t}}")
        print(f"  PRE  : {{PRE_SHA256}}")
        print(f"  POST : {{POST_SHA256 or _sha(patched) + ' (computed)'}}")
        sys.exit(0)

    if mode == "--apply":
        bak = t + ".bak_v320p"
        if not os.path.isfile(bak):
            open(bak, "w", encoding="utf-8").write(src)
        open(t, "w", encoding="utf-8").write(patched)
        import py_compile
        try:
            py_compile.compile(t, doraise=True)
        except py_compile.PyCompileError as e:
            open(t, "w", encoding="utf-8").write(src)
            print(f"ABORT: py_compile failed, reverted. {{e}}"); sys.exit(6)
        print(f"APPLIED. backup at {{bak}}. resulting sha256 = {{_sha(patched)}}; compiles OK.")
        sys.exit(0)

    print(f"unknown mode {{mode}}"); sys.exit(99)


if __name__ == "__main__":
    main()
'''


if __name__ == "__main__":
    main()
