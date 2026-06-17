#!/usr/bin/env python3
"""Local builder (sandbox only): validates OLD off_sides anchor, emits NEW_B64 + POST_FUNC_SHA."""
import base64, hashlib, tempfile, os, py_compile
from typing import Optional  # noqa

OLD_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfb2ZmX3NpZGVzKHNlbGYsIHN5bWJvbDogc3RyLCBzbmFwc2hvdCwgdGFwZTogVGFwZVJlYWRpbmcpIC0+IE9wdGlvbmFsW0xpdmVBbGVydF06CiAgICAgICAgIiIiT2ZmIFNpZGVzIC0gUmFuZ2UgYnJlYWsgaW4gZmFkZSBtYXJrZXQiIiIKICAgICAgICBpZiBzZWxmLl9tYXJrZXRfcmVnaW1lIG5vdCBpbiBbTWFya2V0UmVnaW1lLlJBTkdFX0JPVU5ELCBNYXJrZXRSZWdpbWUuRkFERV06CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgCiAgICAgICAgaWYgYWJzKHNuYXBzaG90LmRpc3RfZnJvbV92d2FwKSA8IDEuMCBhbmQgc25hcHNob3QuZGFpbHlfcmFuZ2VfcGN0ID4gMS41OgogICAgICAgICAgICBkaXN0X2Zyb21faG9kID0gKChzbmFwc2hvdC5oaWdoX29mX2RheSAtIHNuYXBzaG90LmN1cnJlbnRfcHJpY2UpIC8gc25hcHNob3QuY3VycmVudF9wcmljZSkgKiAxMDAKICAgICAgICAgICAgCiAgICAgICAgICAgIGlmIGRpc3RfZnJvbV9ob2QgPCAxLjA6CiAgICAgICAgICAgICAgICByZXR1cm4gTGl2ZUFsZXJ0KAogICAgICAgICAgICAgICAgICAgIGlkPWYib2Zmc2lkZXNfc2hvcnRfe3N5bWJvbH1fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclSCVNJVMnKX0iLAogICAgICAgICAgICAgICAgICAgIHN5bWJvbD1zeW1ib2wsCiAgICAgICAgICAgICAgICAgICAgc2V0dXBfdHlwZT0ib2ZmX3NpZGVzX3Nob3J0IiwKICAgICAgICAgICAgICAgICAgICBzdHJhdGVneV9uYW1lPSJPZmYgU2lkZXMgU2NhbHAgKElOVC0zMykiLAogICAgICAgICAgICAgICAgICAgIGRpcmVjdGlvbj0ic2hvcnQiLAogICAgICAgICAgICAgICAgICAgIHByaW9yaXR5PUFsZXJ0UHJpb3JpdHkuTUVESVVNLAogICAgICAgICAgICAgICAgICAgIGN1cnJlbnRfcHJpY2U9c25hcHNob3QuY3VycmVudF9wcmljZSwKICAgICAgICAgICAgICAgICAgICB0cmlnZ2VyX3ByaWNlPXNuYXBzaG90Lmxvd19vZl9kYXksCiAgICAgICAgICAgICAgICAgICAgc3RvcF9sb3NzPXNlbGYuX2F0cl9mbG9vcmVkX3N0b3AoCiAgICAgICAgICAgICAgICAgICAgICAgIGVudHJ5X3ByaWNlPXNuYXBzaG90LmN1cnJlbnRfcHJpY2UsCiAgICAgICAgICAgICAgICAgICAgICAgIHJhd19zdG9wPXNuYXBzaG90LmhpZ2hfb2ZfZGF5ICsgMC4wMSwKICAgICAgICAgICAgICAgICAgICAgICAgYXRyPWdldGF0dHIoc25hcHNob3QsICJhdHIiLCBOb25lKSwKICAgICAgICAgICAgICAgICAgICAgICAgZGlyZWN0aW9uPSJzaG9ydCIsCiAgICAgICAgICAgICAgICAgICAgICAgIG1pbl9hdHJfbXVsdD0wLjUsCiAgICAgICAgICAgICAgICAgICAgKSwKICAgICAgICAgICAgICAgICAgICB0YXJnZXQ9cm91bmQoc25hcHNob3QubG93X29mX2RheSAtIChzbmFwc2hvdC5oaWdoX29mX2RheSAtIHNuYXBzaG90Lmxvd19vZl9kYXkpLCAyKSwKICAgICAgICAgICAgICAgICAgICByaXNrX3Jld2FyZD0xLjUsCiAgICAgICAgICAgICAgICAgICAgdHJpZ2dlcl9wcm9iYWJpbGl0eT0wLjUwLAogICAgICAgICAgICAgICAgICAgIHdpbl9wcm9iYWJpbGl0eT0wLjUyLAogICAgICAgICAgICAgICAgICAgIG1pbnV0ZXNfdG9fdHJpZ2dlcj0yMCwKICAgICAgICAgICAgICAgICAgICBoZWFkbGluZT1mIuKalO+4jyB7c3ltYm9sfSBPZmYgU2lkZXMgU0hPUlQgLSBSYW5nZSBicmVhayIsCiAgICAgICAgICAgICAgICAgICAgcmVhc29uaW5nPVsKICAgICAgICAgICAgICAgICAgICAgICAgZiJSYW5nZTogJHtzbmFwc2hvdC5sb3dfb2ZfZGF5Oi4yZn0gLSAke3NuYXBzaG90LmhpZ2hfb2ZfZGF5Oi4yZn0iLAogICAgICAgICAgICAgICAgICAgICAgICBmIlJlZ2ltZToge3NlbGYuX21hcmtldF9yZWdpbWUudmFsdWV9IiwKICAgICAgICAgICAgICAgICAgICAgICAgZiJUYXBlOiB7dGFwZS5vdmVyYWxsX3NpZ25hbC52YWx1ZX0iCiAgICAgICAgICAgICAgICAgICAgXSwKICAgICAgICAgICAgICAgICAgICB0aW1lX3dpbmRvdz1zZWxmLl9nZXRfY3VycmVudF90aW1lX3dpbmRvdygpLnZhbHVlLAogICAgICAgICAgICAgICAgICAgIG1hcmtldF9yZWdpbWU9c2VsZi5fbWFya2V0X3JlZ2ltZS52YWx1ZSwKICAgICAgICAgICAgICAgICAgICBleHBpcmVzX2F0PShkYXRldGltZS5ub3codGltZXpvbmUudXRjKSArIHRpbWVkZWx0YShob3Vycz0xKSkuaXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAgICByZXR1cm4gTm9uZQogICAgCg=="
PRE_FUNC_SHA = "b7b484db624ed3152defc504b2eb75ce54e8a14ae72c1b6eac7f971b0d630f92"


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


old = base64.b64decode(OLD_B64).decode("utf-8")
assert sha(old) == PRE_FUNC_SHA, "OLD sha mismatch!"
assert len(old) == 2217, f"OLD len {len(old)} != 2217"

L = [
    '    async def _check_off_sides(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:',
    '        """Off Sides \\u2014 range-top fade SHORT snapback (v19.34.350 redesign).',
    '',
    '        Fires on the TRIGGER, not a state: in RANGE_BOUND/FADE regime, when price returns within',
    '        1.0% of the session HOD in a wide (>1.5%) range AND is near VWAP (|dist|<1.0% \\u2014 the zone',
    '        that vwap_fade-short, which needs >1.0% ABOVE VWAP, structurally cannot serve), a RED 1-min',
    '        double-bar-LOW-break rejection must print (accel 1.3x). Validated +EV on a 14d risk-controlled',
    '        native-1min replay (v349 UNIQUE zone: LOD target win58%/+0.129R, VWAP target win78%/+0.140R;',
    '        the old far target LOD-(HOD-LOD) was the weakest at +0.099R \\u2014 hence the closer target). The',
    '        loose live state-detector fired ~94% sub-edge alerts (9659/10296 gated by the 1.0% min-risk',
    '        floor in replay). Requires stop >= 1.0% of entry + 2 fires/day per symbol. Target = the',
    '        nearer-of(VWAP, LOD) below entry (VWAP mean-reversion if there is room, else the range low).',
    '        """',
    '        if self._market_regime not in [MarketRegime.RANGE_BOUND, MarketRegime.FADE]:',
    '            return None',
    '        HOD_PROX = 1.0',
    '        MIN_RANGE = 1.5',
    '        ACCEL = 1.3',
    '        MIN_RISK_PCT = 1.0',
    '',
    '        if abs(snapshot.dist_from_vwap) >= 1.0 or snapshot.daily_range_pct <= MIN_RANGE:',
    '            return None',
    '        cp = snapshot.current_price',
    '        if not cp or cp <= 0:',
    '            return None',
    '        dist_from_hod = ((snapshot.high_of_day - cp) / cp) * 100',
    '        if dist_from_hod >= HOD_PROX:',
    '            return None',
    '        ts = getattr(self, "technical_service", None)',
    '        if ts is None:',
    '            return None',
    '        bars = ts._get_intraday_bars_from_db(symbol, "1 min", 60)',
    '        if not bars or len(bars) < 5:',
    '            return None',
    '        vwap = float(getattr(snapshot, "vwap", 0.0) or 0.0)',
    '        hod = float(snapshot.high_of_day or 0.0)',
    '        lod = float(snapshot.low_of_day or 0.0)',
    '        if vwap <= 0 or hod <= 0 or lod <= 0 or hod <= lod:',
    '            return None',
    '',
    '        caps = getattr(self, "_off_sides_daily_caps", None)',
    '        if caps is None:',
    '            caps = self._off_sides_daily_caps = {}',
    '        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")',
    '        key = f"{symbol}:{today}:short"',
    '        if caps.get(key, 0) >= 2:',
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
    '        if i < 2:',
    '            return None',
    '        last = bars[i]',
    '        ranges = [(b["high"] - b["low"]) for b in bars[:i]',
    '                  if b.get("high") is not None and b.get("low") is not None]',
    '        med_r = _median(ranges)',
    '',
    '        red = last["close"] < last["open"]',
    '        breaks_lo = last["low"] < min(bars[i - 1]["low"], bars[i - 2]["low"])',
    '        accel_ok = (med_r <= 0) or ((last["high"] - last["low"]) >= ACCEL * med_r)',
    '        if not (red and breaks_lo and accel_ok):',
    '            return None',
    '',
    '        entry = round(min(bars[i - 1]["low"], bars[i - 2]["low"]), 2)',
    '        stop_loss = round(hod + 0.02, 2)',
    '        risk = stop_loss - entry',
    '        if risk <= 0 or entry <= 0 or (risk / entry * 100.0) < MIN_RISK_PCT:',
    '            return None',
    '        use_vwap = lod < vwap < entry',
    '        target_1 = round(vwap, 2) if use_vwap else round(lod, 2)',
    '        if target_1 >= entry:',
    '            return None',
    '        reward = entry - target_1',
    '        r_multiple = round(reward / risk, 2) if risk > 0 else 1.5',
    '        priority = AlertPriority.HIGH if tape.confirmation_for_short else AlertPriority.MEDIUM',
    '        ev_info = ""',
    '        if "off_sides" in self._strategy_stats:',
    '            st = self._strategy_stats["off_sides"]',
    '            if st.win_rate > 0:',
    '                ev_info = f"Historical: {st.win_rate:.0%} win, EV {st.expected_value_r:.2f}R"',
    '        caps[key] = caps.get(key, 0) + 1',
    '        tape_tag = "\\u2713 TAPE" if tape.confirmation_for_short else ""',
    '        tgt_label = "VWAP" if use_vwap else "range-low"',
    '        return LiveAlert(',
    "            id=f\"offsides_short_{symbol}_{datetime.now().strftime('%H%M%S')}\",",
    '            symbol=symbol,',
    '            setup_type="off_sides_short",',
    '            strategy_name="Off Sides Scalp (INT-33)",',
    '            direction="short",',
    '            priority=priority,',
    '            current_price=snapshot.current_price,',
    '            trigger_price=entry,',
    '            stop_loss=stop_loss,',
    '            target=target_1,',
    '            risk_reward=r_multiple,',
    '            trigger_probability=0.65,',
    '            win_probability=0.70,',
    '            minutes_to_trigger=0,',
    '            headline=f"\\u2694\\ufe0f {symbol} Off Sides SHORT snapback \\u2014 range-top fade to {tgt_label} {tape_tag}",',
    '            reasoning=[',
    '                f"Faded within {dist_from_hod:.1f}% of HOD ${hod:.2f} in a {snapshot.daily_range_pct:.1f}% range \\u2192 red 2-bar-low-break",',
    '                f"R:R = {r_multiple:.1f}:1 (Stop ${stop_loss:.2f} above HOD, Target {tgt_label} ${target_1:.2f})",',
    '                f"Regime: {self._market_regime.value} | Tape: {tape.overall_signal.value}",',
    '                ev_info if ev_info else "Range-top fade (v349 replay UNIQUE: +0.13R/58% to LOD, +0.14R/78% to VWAP)",',
    '                "Entry: red bar broke prior-2 lows (near-VWAP zone, 1% min-risk, 2/day cap)",',
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
    "LiveAlert=AlertPriority=TapeReading=datetime=timezone=timedelta=MarketRegime=None\n"
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
print("NEW_B64      :")
print(base64.b64encode(NEW.encode("utf-8")).decode("ascii"))
