#!/usr/bin/env python3
"""Generator for v19.34.320u — completes the A+→multi_day horizon-hijack fix.

v320p fixed the override in enhanced_scanner.py, but smb_integration.
get_default_trade_style() has a SECOND A+ branch (`if is_a_plus: return
MULTI_DAY`) that enhanced_scanner L723-725 applies BEFORE the v320p guard runs
— so for config-bearing intraday/scalp setups (gap_fade, squeeze, second_chance,
...) A+ STILL forced multi_day and v320p's guard then saw "multi_day" and kept
it. This patches that second path with the SAME option-A logic.

Default mode computes PRE+POST from /app. Drift-rebase mode: --pre <sha> pins
the operator's baseline (POST left deterministic via PRE+anchor; py_compile-gated).

Run from /app/backend:  python3 scripts/_build_v320u_patcher.py [--pre <sha>]
"""
import base64
import hashlib
import os
import sys

REL_TARGET = "services/smb_integration.py"

OLD = (
    '            if smb_score.is_a_plus:\n'
    '                return TradeStyle.MULTI_DAY\n'
    '            elif smb_score.total_score >= 35:\n'
    '                return TradeStyle.INTRADAY'
)

NEW = (
    '            # v19.34.320u — A+ is a QUALITY grade, NOT a horizon (see this\n'
    '            # enum\'s own docstring: "A scalp can be A+ quality"). The old\n'
    '            # `if is_a_plus: return MULTI_DAY` hijacked EVERY intraday/scalp\n'
    '            # setup (gap_fade, squeeze, second_chance, ...) into an overnight\n'
    '            # carry. This path runs at LiveAlert populate (enhanced_scanner\n'
    '            # L723-725) BEFORE the v320p guard, so it silently NEUTRALIZED\n'
    '            # v320p. Now A+ only promotes when the setup is ALREADY carry-\n'
    '            # natured; intraday/scalp keep their horizon. (A+ quality/priority\n'
    '            # still flows via smb_is_a_plus.)\n'
    '            if smb_score.is_a_plus:\n'
    '                if str(default_style.value).lower() in (\n'
    '                    "multi_day", "swing", "position", "investment"\n'
    '                ):\n'
    '                    return TradeStyle.MULTI_DAY\n'
    '                return default_style\n'
    '            elif smb_score.total_score >= 35:\n'
    '                return TradeStyle.INTRADAY'
)


def main():
    pre_override = sys.argv[sys.argv.index("--pre") + 1].strip() if "--pre" in sys.argv else None
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target = os.path.join(here, REL_TARGET)

    if pre_override:
        pre_sha, post_sha = pre_override, ""
    else:
        src = open(target, encoding="utf-8").read()
        if src.count(OLD) != 1:
            print(f"ABORT: OLD anchor found {src.count(OLD)} times (need 1)", file=sys.stderr)
            sys.exit(2)
        pre_sha = hashlib.sha256(src.encode()).hexdigest()
        post = src.replace(OLD, NEW, 1)
        post_sha = hashlib.sha256(post.encode()).hexdigest()
        import py_compile
        open("/tmp/_v320u_post.py", "w").write(post)
        py_compile.compile("/tmp/_v320u_post.py", doraise=True)

    patcher = TEMPLATE.format(
        rel_target=REL_TARGET, pre_sha=pre_sha, post_sha=post_sha,
        old_b64=base64.b64encode(OLD.encode()).decode(),
        new_b64=base64.b64encode(NEW.encode()).decode(),
    )
    open("/tmp/patch_v320u.py", "w").write(patcher)
    print(f"PRE_SHA256  = {pre_sha}")
    print(f"POST_SHA256 = {post_sha or '(unset — deterministic via PRE+anchor)'}")
    print(f"wrote /tmp/patch_v320u.py ({len(patcher)} bytes)")


TEMPLATE = r'''#!/usr/bin/env python3
"""v19.34.320u — completes the A+→multi_day horizon-hijack fix (2nd path).

Target: backend/{rel_target}  (get_default_trade_style, the smb_score.is_a_plus
branch). Mirrors v320p (enhanced_scanner) with the SAME option-A logic: A+ is a
QUALITY grade, not a horizon. A+ only promotes to multi_day when the setup's
default_style is ALREADY carry-natured; intraday/scalp setups keep their horizon.
This path runs at LiveAlert populate BEFORE the v320p guard, so without this fix
v320p was silently neutralized for config-bearing intraday/scalp setups.

SAFETY: pure style-resolution; alert-stamping only. No close/bracket/kill-switch
paths. Net = fewer overnight carries. §2.2: PRE (+POST when known) SHA guards,
base64 anchored chunk, auto-backup, --check/--apply/--rollback/--status,
py_compile gate.

USAGE (DGX):
  curl -sS -o /tmp/patch_v320u.py https://paste.rs/<id>
  .venv/bin/python /tmp/patch_v320u.py --check
  .venv/bin/python /tmp/patch_v320u.py --apply
  git add backend/{rel_target} && git commit -m "v19.34.320u: A+ horizon-hijack fix (get_default_trade_style)" && git push origin main
  ./start_backend.sh --force
  # rollback: .venv/bin/python /tmp/patch_v320u.py --rollback
"""
import base64, hashlib, os, sys

REL_TARGET = "{rel_target}"
PRE_SHA256 = "{pre_sha}"
POST_SHA256 = "{post_sha}"
OLD_B64 = "{old_b64}"
NEW_B64 = "{new_b64}"
_MARKER = "v19.34.320u"


def _resolve_target():
    o = os.environ.get("V320U_TARGET")
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


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    t = _resolve_target()
    old = base64.b64decode(OLD_B64).decode()
    new = base64.b64decode(NEW_B64).decode()
    have_post = bool(POST_SHA256)

    if mode == "--status":
        if not os.path.isfile(t):
            print(f"target NOT FOUND: {{t}}"); sys.exit(1)
        body = open(t, encoding="utf-8").read(); cur = _sha(body)
        print(f"target : {{t}}\ncurrent: {{cur}}")
        print(f"PRE    : {{PRE_SHA256}}  {{'<= UNPATCHED' if cur==PRE_SHA256 else ''}}")
        print("POST   : " + (POST_SHA256 + ("  <= PATCHED" if cur == POST_SHA256 else "")
              if have_post else "(deterministic)  " + ("<= PATCHED (marker)" if _MARKER in body else "")))
        sys.exit(0)

    if mode == "--rollback":
        bak = t + ".bak_v320u"
        if not os.path.isfile(bak):
            print(f"ABORT: no backup at {{bak}}"); sys.exit(1)
        data = open(bak, encoding="utf-8").read()
        if _sha(data) != PRE_SHA256:
            print("ABORT: backup hash != PRE_SHA256"); sys.exit(1)
        open(t, "w", encoding="utf-8").write(data)
        print(f"ROLLED BACK from {{bak}}"); sys.exit(0)

    if not os.path.isfile(t):
        print(f"ABORT: target NOT FOUND: {{t}}"); sys.exit(1)
    src = open(t, encoding="utf-8").read(); cur = _sha(src)
    if have_post and cur == POST_SHA256:
        print("ALREADY PATCHED. No-op."); sys.exit(0)
    if (not have_post) and _MARKER in src and cur != PRE_SHA256:
        print("ALREADY PATCHED (marker present). No-op."); sys.exit(0)
    if cur != PRE_SHA256:
        print("ABORT: PRE_SHA256 mismatch — DGX file has drifted.")
        print(f"  expected PRE: {{PRE_SHA256}}")
        print(f"  current     : {{cur}}")
        print("  Re-confirm: sha256sum backend/" + REL_TARGET + "  (paste it to rebase)")
        sys.exit(3)
    if src.count(old) != 1:
        print(f"ABORT: anchor found {{src.count(old)}} times (need 1)"); sys.exit(4)
    patched = src.replace(old, new, 1)
    if have_post and _sha(patched) != POST_SHA256:
        print("ABORT: post hash != POST_SHA256"); sys.exit(5)

    if mode == "--check":
        print("CHECK OK: PRE matches, anchor unique"
              + (", POST verified." if have_post else ", POST deterministic (PRE+anchor)."))
        print(f"  PRE  : {{PRE_SHA256}}\n  POST : {{POST_SHA256 or _sha(patched) + ' (computed)'}}")
        sys.exit(0)

    if mode == "--apply":
        bak = t + ".bak_v320u"
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
