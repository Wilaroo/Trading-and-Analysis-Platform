#!/usr/bin/env python3
"""Local builder (sandbox): OLD = v348 backside bytes (current live); emit v352 NEW_B64 + SHAs."""
import base64, hashlib, tempfile, os, py_compile, importlib.util

spec = importlib.util.spec_from_file_location("v348", "backend/scripts/patch_v348_backside_snapback.py")
v348 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v348)
OLD_B64 = v348.NEW_B64               # current LIVE backside == v348's NEW function
PRE_FUNC_SHA = v348.POST_FUNC_SHA    # = 2f6f4f61...


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


old = base64.b64decode(OLD_B64).decode("utf-8")
assert sha(old) == PRE_FUNC_SHA, "OLD sha mismatch vs v348 POST!"
print("OLD(=v348 live backside) sha:", sha(old), "len", len(old))

L = [
    '    async def _check_backside(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:',
    '        """Back$ide \\u2014 cheat-sheet-faithful VWAP-recovery scalp (v19.34.352).',
    '',
    '        Re-aligned to the OFFICIAL SMB Back$ide cheat sheet (v348 used a DEEP flush-low stop',
    '        which crushed R:R; doctrine uses a TIGHT stop .02 below the MOST RECENT HIGHER LOW).',
    '        LONG only. Rising phase after a distinct low: a HIGHER LOW (recent pullback low > the',
    '        session LOD) plus a HIGHER HIGH (green 1-min double-bar-high break = "break of a 1-min',
    '        bar from consolidation, pay the offer on the break"), price holding ABOVE the 9-EMA but',
    '        still BELOW VWAP, recovered MORE than halfway between LOD and VWAP. STOP = recent higher',
    '        low - 0.02 (tight). TARGET = VWAP (exit all). One-and-done (1/day/symbol). Ideal periods',
    '        10:00-13:30 ET. Only takes R:R >= 1.0. Validated on a 14d native-1min replay (v352:',
    '        63% win, winsorAvg +0.70R, medR +1.11R, avg R:R 4.8 to VWAP) \\u2014 doctrine-faithful AND',
    '        far better than v348 (+0.28R). Cheat-sheet stats: 50-60% win, ~1.4:1 R:R.',
    '        """',
    '        RECENT_K = 5',
    '        ACCEL = 1.3',
    '        HALFWAY = 0.5',
    '        MIN_RR = 1.0',
    '',
    '        if self._get_current_time_window() not in (',
    '                TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING, TimeWindow.MIDDAY):',
    '            return None',
    '        if not getattr(snapshot, "above_ema9", False):',
    '            return None',
    '        ts = getattr(self, "technical_service", None)',
    '        if ts is None:',
    '            return None',
    '        bars = ts._get_intraday_bars_from_db(symbol, "1 min", 60)',
    '        if not bars or len(bars) < RECENT_K + 3:',
    '            return None',
    '        vwap = float(getattr(snapshot, "vwap", 0.0) or 0.0)',
    '        ema9 = float(getattr(snapshot, "ema_9", 0.0) or 0.0)',
    '        if vwap <= 0 or ema9 <= 0:',
    '            return None',
    '',
    '        caps = getattr(self, "_backside_daily_caps", None)',
    '        if caps is None:',
    '            caps = self._backside_daily_caps = {}',
    '        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")',
    '        key = f"{symbol}:{today}:long"',
    '        if caps.get(key, 0) >= 1:',
    '            return None',
    '',
    '        def _median(xs):',
    '            s = sorted(xs)',
    '            n = len(s)',
    '            if n == 0:',
    '                return 0.0',
    '            return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0',
    '',
    '        i = len(bars) - 1',
    '        if i < RECENT_K + 1:',
    '            return None',
    '        last = bars[i]',
    '        lows = [b["low"] for b in bars if b.get("low") is not None]',
    '        if not lows:',
    '            return None',
    '        lod = min(lows)',
    '        ranges = [(b["high"] - b["low"]) for b in bars[:i]',
    '                  if b.get("high") is not None and b.get("low") is not None]',
    '        med_r = _median(ranges)',
    '',
    '        green = last["close"] > last["open"]',
    '        clears_hi = last["high"] > max(bars[i - 1]["high"], bars[i - 2]["high"])',
    '        entry = round(max(bars[i - 1]["high"], bars[i - 2]["high"]), 2)',
    '        recent_low = min(bars[j]["low"] for j in range(i - RECENT_K, i))',
    '        accel_ok = (med_r <= 0) or ((last["high"] - last["low"]) >= ACCEL * med_r)',
    '        if not (green and clears_hi and entry < vwap and last["close"] > ema9',
    '                and recent_low > lod',
    '                and entry > lod + HALFWAY * (vwap - lod)',
    '                and accel_ok):',
    '            return None',
    '',
    '        stop_loss = round(recent_low - 0.02, 2)',
    '        risk = entry - stop_loss',
    '        if risk <= 0 or entry <= 0:',
    '            return None',
    '        target_1 = round(vwap, 2)',
    '        rr = (target_1 - entry) / risk',
    '        if rr < MIN_RR:',
    '            return None',
    '        r_multiple = round(rr, 2)',
    '        priority = AlertPriority.HIGH if tape.confirmation_for_long else AlertPriority.MEDIUM',
    '        ev_info = ""',
    '        if "backside" in self._strategy_stats:',
    '            st = self._strategy_stats["backside"]',
    '            if st.win_rate > 0:',
    '                ev_info = f"Historical: {st.win_rate:.0%} win, EV {st.expected_value_r:.2f}R"',
    '        caps[key] = caps.get(key, 0) + 1',
    '        hl_dist = (vwap - entry) / vwap * 100.0',
    '        tape_tag = "\\u2713 TAPE" if tape.confirmation_for_long else ""',
    '        return LiveAlert(',
    "            id=f\"backside_{symbol}_{datetime.now().strftime('%H%M%S')}\",",
    '            symbol=symbol,',
    '            setup_type="backside",',
    '            strategy_name="Back$ide Scalp (INT-32)",',
    '            direction="long",',
    '            priority=priority,',
    '            current_price=snapshot.current_price,',
    '            trigger_price=entry,',
    '            stop_loss=stop_loss,',
    '            target=target_1,',
    '            risk_reward=r_multiple,',
    '            trigger_probability=0.63,',
    '            win_probability=0.63,',
    '            minutes_to_trigger=0,',
    '            headline=f"\\U0001f3af {symbol} Back$ide \\u2014 higher-low reclaim to VWAP (R:R {r_multiple:.1f}) {tape_tag}",',
    '            reasoning=[',
    '                f"Rising back$ide: higher-low ${recent_low:.2f} > LOD ${lod:.2f}, green bar broke prior-2 highs",',
    '                f"Recovered {hl_dist:.1f}% below VWAP ${vwap:.2f} (>halfway from LOD), holding above 9-EMA",',
    '                f"R:R = {r_multiple:.1f}:1 (TIGHT stop ${stop_loss:.2f} = .02 below higher low, Target VWAP ${target_1:.2f})",',
    '                f"Tape: {tape.overall_signal.value}",',
    '                ev_info if ev_info else "Cheat-sheet back$ide (v352 replay 63% win, +0.70R, avg R:R 4.8 to VWAP)",',
    '                "One-and-done scalp, 10:00-13:30 ET window (SMB Back$ide doctrine)",',
    '            ],',
    '            time_window=self._get_current_time_window().value,',
    '            market_regime=self._market_regime.value,',
    '            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()',
    '        )',
    '        return None',
    '    ',
]
NEW = "\n".join(L) + "\n"

wrapper = (
    "from typing import Optional\n"
    "from enum import Enum\n"
    "class TimeWindow(Enum):\n    MORNING_SESSION='m'\n    LATE_MORNING='l'\n    MIDDAY='d'\n"
    "LiveAlert=AlertPriority=TapeReading=datetime=timezone=timedelta=None\n"
    "class C:\n" + NEW
)
with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
    tf.write(wrapper); tmp = tf.name
try:
    py_compile.compile(tmp, doraise=True)
    print("NEW compiles OK")
finally:
    os.unlink(tmp)

print("NEW len      :", len(NEW))
print("POST_FUNC_SHA:", sha(NEW))
print("DGX_WHOLE_PRE should be e772deda3d2dcb84affe1edcf8257999b3129c6ce178c34041c94b0846b3cc92")
print("OLD_B64=", OLD_B64[:60], "...")
print("NEW_B64:")
print(base64.b64encode(NEW.encode("utf-8")).decode("ascii"))

# ---- generate patch_v352 file with exact b64s ----
NEW_B64_VAL = base64.b64encode(NEW.encode("utf-8")).decode("ascii")
TEMPLATE = r'''#!/usr/bin/env python3
"""
patch_v352_backside_cheatsheet.py  (AGENTS.md 2.2 -- function-anchored patcher)

WHAT: re-aligns enhanced_scanner._check_backside to the OFFICIAL SMB Back$ide cheat sheet.
      v348 anchored the stop at the DEEP flush LOD (R:R << 1). v352 uses the doctrine's TIGHT
      stop = .02 below the MOST RECENT HIGHER LOW, requires a HIGHER-LOW + HIGHER-HIGH rising
      structure, price above the 9-EMA but below VWAP, recovered > halfway between LOD and VWAP,
      target = VWAP, one-and-done (1/day), 10:00-13:30 ET window, R:R >= 1.0.
WHY : cheat-sheet-faithful + far better edge. v352 14d native-1min replay: 63% win, winsorAvg
      +0.70R, medR +1.11R, avg R:R 4.8 to VWAP (vs v348 +0.28R). Cheat sheet: 50-60% win, ~1.4:1.
      Anchored to the CURRENT live backside (== v348 bytes). 1-min bars from ib_historical_data
      (IB-only) via self.technical_service._get_intraday_bars_from_db(sym,"1 min",60).

DRIFT NOTE: FUNCTION-ANCHORED. Asserts live whole-file SHA == DGX baseline AND the exact v348
      _check_backside bytes present (count==1), replaces, asserts new func SHA, py_compiles the
      whole file before writing. backup + func-SHA guards cover the (paste-limited) whole POST.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/patch_v352_backside_cheatsheet.py --check
  .venv/bin/python backend/scripts/patch_v352_backside_cheatsheet.py --apply
  .venv/bin/python backend/scripts/patch_v352_backside_cheatsheet.py --rollback
Then: pytest backend/tests/test_v352_backside.py -q ; commit ; ./start_backend.sh --force
"""
import base64, hashlib, sys, shutil, os, py_compile, tempfile

FILE = "backend/services/enhanced_scanner.py"
DGX_WHOLE_PRE = "__DGX__"
PRE_FUNC_SHA  = "__PRE__"
POST_FUNC_SHA = "__POST__"
OLD_B64 = "__OLD_B64__"
NEW_B64 = "__NEW_B64__"
BACKUP = FILE + ".bak_v352"


def _sha(s): return hashlib.sha256(s.encode("utf-8")).hexdigest()
def _read():
    if not os.path.exists(FILE):
        print(f"ERROR: {FILE} not found (run from repo root)"); sys.exit(2)
    return open(FILE, encoding="utf-8").read()
def _old(): return base64.b64decode(OLD_B64).decode("utf-8")
def _new(): return base64.b64decode(NEW_B64).decode("utf-8")
def _compiles(text):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        tf.write(text); tmp = tf.name
    try:
        py_compile.compile(tmp, doraise=True); return True
    except py_compile.PyCompileError as e:
        print("POST-PATCH COMPILE FAILED:\n", e); return False
    finally:
        os.unlink(tmp)


def check():
    src = _read(); cur = _sha(src); old = _old()
    print(f"file            : {FILE}")
    print(f"whole-file SHA  : {cur}")
    print(f"expected (DGX)  : {DGX_WHOLE_PRE}  {'OK' if cur == DGX_WHOLE_PRE else 'DRIFT!'}")
    print(f"func anchor     : present={old in src} count={src.count(old)}")
    print(f"func PRE sha    : {_sha(old)}  {'OK' if _sha(old) == PRE_FUNC_SHA else 'MISMATCH'}")
    print(f"func POST sha   : {_sha(_new())}  {'OK' if _sha(_new()) == POST_FUNC_SHA else 'MISMATCH'}")
    if _new() in src: print("state           : ALREADY PATCHED")
    if cur != DGX_WHOLE_PRE:
        print("\nDRIFT: live file != DGX baseline. Re-extract and rebuild."); return False
    if src.count(old) != 1:
        print("\nAnchor missing/ambiguous -- abort."); return False
    print("\nREADY: --apply installs the cheat-sheet Back$ide (tight higher-low stop -> VWAP).")
    return True


def apply():
    src = _read(); old, new = _old(), _new()
    if new in src: print("Already patched. No-op."); return
    if _sha(src) != DGX_WHOLE_PRE:
        print(f"ABORT: whole-file SHA {_sha(src)} != DGX baseline. See --check."); sys.exit(3)
    if src.count(old) != 1:
        print(f"ABORT: anchor count={src.count(old)} (need 1)."); sys.exit(3)
    if _sha(old) != PRE_FUNC_SHA:
        print("ABORT: function PRE sha mismatch."); sys.exit(3)
    if _sha(new) != POST_FUNC_SHA:
        print("ABORT: embedded NEW function sha mismatch (corrupt patcher)."); sys.exit(3)
    patched = src.replace(old, new, 1)
    if not _compiles(patched):
        print("ABORT: patched file does not compile. No write."); sys.exit(3)
    shutil.copy2(FILE, BACKUP)
    with open(FILE, "w", encoding="utf-8") as f: f.write(patched)
    print(f"APPLIED. backup -> {BACKUP}")
    print(f"new whole-file SHA : {_sha(patched)}  (record this)")
    print("Verify: pytest backend/tests/test_v352_backside.py -q ; commit BEFORE restart ; ./start_backend.sh --force")


def rollback():
    src = _read(); old, new = _old(), _new()
    if old in src and _sha(src) == DGX_WHOLE_PRE:
        print("Already at baseline (v348). No-op."); return
    if new in src and src.count(new) == 1:
        restored = src.replace(new, old, 1)
        shutil.copy2(FILE, FILE + ".bak_pre_rollback")
        with open(FILE, "w", encoding="utf-8") as f: f.write(restored)
        print(f"ROLLED BACK via reverse-anchor. whole-file SHA == DGX baseline: {_sha(restored) == DGX_WHOLE_PRE}")
        return
    if os.path.exists(BACKUP):
        bsrc = open(BACKUP, encoding="utf-8").read()
        if _sha(bsrc) == DGX_WHOLE_PRE:
            shutil.copy2(BACKUP, FILE); print(f"ROLLED BACK from {BACKUP} (== DGX baseline)."); return
    print("ABORT: could not safely roll back."); sys.exit(4)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--check"
    {"--check": check, "--apply": apply, "--rollback": rollback}.get(arg, lambda: print("usage: --check | --apply | --rollback"))()
'''
out = (TEMPLATE
       .replace("__DGX__", "e772deda3d2dcb84affe1edcf8257999b3129c6ce178c34041c94b0846b3cc92")
       .replace("__PRE__", PRE_FUNC_SHA)
       .replace("__POST__", sha(NEW))
       .replace("__OLD_B64__", OLD_B64)
       .replace("__NEW_B64__", NEW_B64_VAL))
with open("backend/scripts/patch_v352_backside_cheatsheet.py", "w") as f:
    f.write(out)
print("WROTE patch_v352_backside_cheatsheet.py")
