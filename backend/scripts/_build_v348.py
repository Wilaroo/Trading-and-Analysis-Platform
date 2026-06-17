#!/usr/bin/env python3
"""Local builder (sandbox only): validates OLD anchor, emits NEW_B64 + POST_FUNC_SHA."""
import base64, hashlib, tempfile, os, py_compile

OLD_B64 = ("ICAgIGFzeW5jIGRlZiBfY2hlY2tfYmFja3NpZGUoc2VsZiwgc3ltYm9sOiBzdHIsIHNuYXBzaG90LCB0YXBlOiBUYXBlUmVhZGluZykgLT4gT3B0aW9uYWxbTGl2ZUFsZXJ0XToKICAgICAgICAiIiJCYWNrJGlkZSAtIFJlY292ZXJ5IGZyb20gTE9EIiIiCiAgICAgICAgaWYgKHNuYXBzaG90LnRyZW5kID09ICJ1cHRyZW5kIiBhbmQKICAgICAgICAgICAgc25hcHNob3QuYWJvdmVfZW1hOSBhbmQKICAgICAgICAgICAgbm90IHNuYXBzaG90LmFib3ZlX3Z3YXAgYW5kCiAgICAgICAgICAgIHNuYXBzaG90LmRpc3RfZnJvbV92d2FwID4gLTIuMCBhbmQKICAgICAgICAgICAgc25hcHNob3QucnZvbCA+PSAxLjIpOgogICAgICAgICAgICAKICAgICAgICAgICAgcmV0dXJuIExpdmVBbGVydCgKICAgICAgICAgICAgICAgIGlkPWYiYmFja3NpZGVfe3N5bWJvbH1fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclSCVNJVMnKX0iLAogICAgICAgICAgICAgICAgc3ltYm9sPXN5bWJvbCwKICAgICAgICAgICAgICAgIHNldHVwX3R5cGU9ImJhY2tzaWRlIiwKICAgICAgICAgICAgICAgIHN0cmF0ZWd5X25hbWU9IkJhY2skaWRlIFNjYWxwIChJTlQtMzIpIiwKICAgICAgICAgICAgICAgIGRpcmVjdGlvbj0ibG9uZyIsCiAgICAgICAgICAgICAgICAjIHYxOS4zNC4zMjByIOKAlCB0YXBlLWdhdGVkIEhJR0ggYnJhbmNoICh3YXMgaGFyZGNvZGVkIE1FRElVTSwgd2hpY2ggY2FwcGVkCiAgICAgICAgICAgICAgICAjIHRoaXMgaW50cmFkYXkgc2NhbHAgYmVsb3cgdGhlIGF1dG8tZmlyZSBiYXIgcmVnYXJkbGVzcyBvZiBzaWduYWwKICAgICAgICAgICAgICAgICMgcXVhbGl0eTsgc2VlIHYzMjBxICsgdjMyMHItcHJlY2hlY2spLiBPbmx5IHRoZSB0YXBlLWNvbmZpcm1lZAogICAgICAgICAgICAgICAgIyBzdWJzZXQgcHJvbW90ZXM7IEVWL3dpbi1yYXRlIGdhdGUgc3RpbGwgZ292ZXJucyBhdXRvLWZpcmUuCiAgICAgICAgICAgICAgICBwcmlvcml0eT1BbGVydFByaW9yaXR5LkhJR0ggaWYgdGFwZS5jb25maXJtYXRpb25fZm9yX2xvbmcgZWxzZSBBbGVydFByaW9yaXR5Lk1FRElVTSwKICAgICAgICAgICAgICAgIGN1cnJlbnRfcHJpY2U9c25hcHNob3QuY3VycmVudF9wcmljZSwKICAgICAgICAgICAgICAgIHRyaWdnZXJfcHJpY2U9c25hcHNob3QuY3VycmVudF9wcmljZSwKICAgICAgICAgICAgICAgIHN0b3BfbG9zcz1zZWxmLl9hdHJfZmxvb3JlZF9zdG9wKAogICAgICAgICAgICAgICAgICAgIGVudHJ5X3ByaWNlPXNuYXBzaG90LmN1cnJlbnRfcHJpY2UsCiAgICAgICAgICAgICAgICAgICAgcmF3X3N0b3A9c25hcHNob3QuZW1hXzkgLSAwLjAyLAogICAgICAgICAgICAgICAgICAgIGF0cj1nZXRhdHRyKHNuYXBzaG90LCAiYXRyIiwgTm9uZSksCiAgICAgICAgICAgICAgICAgICAgZGlyZWN0aW9uPSJsb25nIiwKICAgICAgICAgICAgICAgICAgICBtaW5fYXRyX211bHQ9MC41LAogICAgICAgICAgICAgICAgKSwKICAgICAgICAgICAgICAgIHRhcmdldD1yb3VuZChzbmFwc2hvdC52d2FwLCAyKSwKICAgICAgICAgICAgICAgIHJpc2tfcmV3YXJkPTIuMCwKICAgICAgICAgICAgICAgIHRyaWdnZXJfcHJvYmFiaWxpdHk9MC41NSwKICAgICAgICAgICAgICAgIHdpbl9wcm9iYWJpbGl0eT0wLjU1LAogICAgICAgICAgICAgICAgbWludXRlc190b190cmlnZ2VyPTE1LAogICAgICAgICAgICAgICAgaGVhZGxpbmU9ZiLihpfvuI8ge3N5bWJvbH0gQmFjayRpZGUgLSBSZWNvdmVyaW5nIHRvIFZXQVAiLAogICAgICAgICAgICAgICAgcmVhc29uaW5nPVsKICAgICAgICAgICAgICAgICAgICAiSGlnaGVyIGhpZ2hzL2xvd3MgYWJvdmUgOS1FTUEiLAogICAgICAgICAgICAgICAgICAgIGYiVGFwZToge3RhcGUub3ZlcmFsbF9zaWduYWwudmFsdWV9IiwKICAgICAgICAgICAgICAgICAgICBmIlRhcmdldDogVldBUCAke3NuYXBzaG90LnZ3YXA6LjJmfSIKICAgICAgICAgICAgICAgIF0sCiAgICAgICAgICAgICAgICB0aW1lX3dpbmRvdz1zZWxmLl9nZXRfY3VycmVudF90aW1lX3dpbmRvdygpLnZhbHVlLAogICAgICAgICAgICAgICAgbWFya2V0X3JlZ2ltZT1zZWxmLl9tYXJrZXRfcmVnaW1lLnZhbHVlLAogICAgICAgICAgICAgICAgZXhwaXJlc19hdD0oZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykgKyB0aW1lZGVsdGEoaG91cnM9MSkpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICkKICAgICAgICByZXR1cm4gTm9uZQogICAgCg==")

PRE_FUNC_SHA = "c89eef207feb4d2ea2e1e72975b5915481d5e6888c251ac7831330daeb4edb48"


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


old = base64.b64decode(OLD_B64).decode("utf-8")
assert sha(old) == PRE_FUNC_SHA, "OLD sha mismatch!"
assert len(old) == 2215, f"OLD len {len(old)} != 2215"

L = [
    '    async def _check_backside(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:',
    '        """Back$ide \\u2014 shallow VWAP-recovery snapback (v19.34.348 redesign, LONG-only).',
    '',
    '        Fires on the TRIGGER, not a dist_from_vwap STATE: after a SHALLOW dip BELOW session',
    '        VWAP (the [0.3%, 1.0%) band that vwap_fade \\u2014 which floors at 1.0% \\u2014 structurally',
    '        cannot serve), price must reclaim the 9-EMA and a 1-min double-bar-HIGH-break snapback',
    '        prints within +1..+4 bars of the dip-low, snapping back UP to VWAP. Validated +EV on a',
    '        14d risk-controlled native-1min replay (v347: 0-0.5% band win93%/+0.11R, 0.5-1% band',
    '        win88%/+0.41R; n=32/33 UNIQUE vs vwap_fade \\u2014 a distinct shallow-dip recovery edge,',
    '        NOT a duplicate). Requires stop >= 1.0% of entry (the min-risk floor that gated ~96% of',
    '        the loose state fires) + RVOL >= 1.2 + price above the 9-EMA + 2 fires/day per symbol.',
    '        """',
    '        DIP_FLOOR = 0.3',
    "        DIP_CEIL = 1.0          # >= 1.0% is vwap_fade's band \\u2014 keep backside complementary (zero overlap)",
    '        TRIGGER_WIN = 4',
    '        ACCEL = 1.3',
    '        MIN_RVOL = 1.2',
    '        MIN_RISK_PCT = 1.0',
    '',
    '        if not getattr(snapshot, "above_ema9", False):',
    '            return None',
    '        ts = getattr(self, "technical_service", None)',
    '        if ts is None:',
    '            return None',
    '        bars = ts._get_intraday_bars_from_db(symbol, "1 min", 60)',
    '        if not bars or len(bars) < 5:',
    '            return None',
    '        rvol = float(getattr(snapshot, "rvol", 0.0) or 0.0)',
    '        if rvol < MIN_RVOL:',
    '            return None',
    '        vwap = float(getattr(snapshot, "vwap", 0.0) or 0.0)',
    '        if vwap <= 0:',
    '            return None',
    '',
    '        caps = getattr(self, "_backside_daily_caps", None)',
    '        if caps is None:',
    '            caps = self._backside_daily_caps = {}',
    '        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")',
    '',
    '        def _median(xs):',
    '            s = sorted(xs)',
    '            n = len(s)',
    '            if n == 0:',
    '                return 0.0',
    '            return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0',
    '',
    '        i = len(bars) - 1',
    '        last = bars[i]',
    '        ranges = [(b["high"] - b["low"]) for b in bars[:i]',
    '                  if b.get("high") is not None and b.get("low") is not None]',
    '        med_r = _median(ranges)',
    '',
    '        lows = [(j, b["low"]) for j, b in enumerate(bars) if b.get("low") is not None]',
    '        if lows:',
    '            lod = min(v for _, v in lows)',
    '            lod_idx = max(j for j, v in lows if v == lod)',
    '            dip = (vwap - lod) / vwap * 100.0',
    '            accel_ok = (med_r <= 0) or ((bars[lod_idx]["high"] - bars[lod_idx]["low"]) >= ACCEL * med_r)',
    '            green = last["close"] > last["open"]',
    '            clears_hi = i >= 2 and last["high"] > max(bars[i - 1]["high"], bars[i - 2]["high"])',
    '            if (DIP_FLOOR <= dip < DIP_CEIL and accel_ok and green and clears_hi',
    '                    and 1 <= (i - lod_idx) <= TRIGGER_WIN):',
    '                key = f"{symbol}:{today}:long"',
    '                if caps.get(key, 0) >= 2:',
    '                    return None',
    '                entry = round(max(bars[i - 1]["high"], bars[i - 2]["high"]), 2)',
    '                if entry >= vwap:',
    '                    return None',
    '                stop_loss = round(min(lod - 0.02, snapshot.support - (snapshot.atr * 0.25)), 2)',
    '                risk = entry - stop_loss',
    '                if risk <= 0 or entry <= 0 or (risk / entry * 100.0) < MIN_RISK_PCT:',
    '                    return None',
    '                target_1 = round(vwap, 2)',
    '                reward = target_1 - entry',
    '                r_multiple = round(reward / risk, 2) if risk > 0 else 2.0',
    '                priority = AlertPriority.HIGH if tape.confirmation_for_long else AlertPriority.MEDIUM',
    '                ev_info = ""',
    '                if "backside" in self._strategy_stats:',
    '                    st = self._strategy_stats["backside"]',
    '                    if st.win_rate > 0:',
    '                        ev_info = f"Historical: {st.win_rate:.0%} win, EV {st.expected_value_r:.2f}R"',
    '                caps[key] = caps.get(key, 0) + 1',
    '                tape_tag = "\\u2713 TAPE" if tape.confirmation_for_long else ""',
    '                return LiveAlert(',
    "                    id=f\"backside_{symbol}_{datetime.now().strftime('%H%M%S')}\",",
    '                    symbol=symbol,',
    '                    setup_type="backside",',
    '                    strategy_name="Back$ide Scalp (INT-32)",',
    '                    direction="long",',
    '                    priority=priority,',
    '                    current_price=snapshot.current_price,',
    '                    trigger_price=entry,',
    '                    stop_loss=stop_loss,',
    '                    target=target_1,',
    '                    risk_reward=r_multiple,',
    '                    trigger_probability=0.65,',
    '                    win_probability=0.73,',
    '                    minutes_to_trigger=0,',
    '                    headline=f"\\U0001f3af {symbol} Back$ide snapback \\u2014 {dip:.1f}% dip reclaim to VWAP {tape_tag}",',
    '                    reasoning=[',
    '                        f"Shallow {dip:.1f}% dip below VWAP ${vwap:.2f} \\u2192 1-min double-bar-break reclaim",',
    '                        f"Snapback {i - lod_idx} bar(s) after LOD ${lod:.2f} (flush range >= {ACCEL:g}x median), above 9-EMA",',
    '                        f"R:R = {r_multiple:.1f}:1 (Stop ${stop_loss:.2f} below LOD, Target VWAP ${target_1:.2f})",',
    '                        f"RVOL {rvol:.1f}x | Tape: {tape.overall_signal.value}",',
    '                        ev_info if ev_info else "Shallow VWAP-recovery (v347 replay +0.28R, 91% win, 0.3-1% band)",',
    '                        "Entry: green bar reclaimed prior-2 highs (0.3-1% band, complementary to vwap_fade, 2/day cap)",',
    '                    ],',
    '                    time_window=self._get_current_time_window().value,',
    '                    market_regime=self._market_regime.value,',
    '                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()',
    '                )',
    '        return None',
    '    ',
]
NEW = "\n".join(L) + "\n"

# compile NEW inside a dummy class to verify syntax (names not resolved by py_compile)
wrapper = (
    "from typing import Optional\n"
    "class _T:\n"
    "    pass\n"
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
print("NEW_B64      :")
print(base64.b64encode(NEW.encode("utf-8")).decode("ascii"))
