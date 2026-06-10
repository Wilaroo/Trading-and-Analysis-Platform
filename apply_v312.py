#!/usr/bin/env python3
"""
apply_v312.py — self-verifying patcher for v19.34.312
=====================================================
TFT: train on the intraday-dense era + drop the near-empty 1-min timeframe.

Path A from the data audit: your 247M intraday bars exist, but the TFT was
anchoring on a ~20-25yr daily axis while intraday only reaches ~2020 (1h) /
~2024 (5m/15m), so ~90% of training rows had EMPTY multi-TF blocks (coverage
1m=0.2%, 5m=2.7%, 15m=10.5%, 1h=21.2%). This patch:

  1. Drops "1 min" (4 months / 0.2% = pure noise). TFT_TIMEFRAMES -> 4 TFs,
     input dim 60 -> 48.
  2. Fixes the model instantiation to use the dynamic timeframe count
     (was hardcoded TFT() => n_timeframes=5 => would crash on 48-dim input).
  3. Adds a configurable training window (default 2020-03-27, the start of
     hourly history; override via TFT_MIN_DATE env var) so the multi-TF
     features are actually populated.

Edits ONLY backend/services/ai_modules/temporal_fusion_transformer.py and
rewrites backend/tests/test_tft_alignment.py.

Self-verifying: validates every anchor first; writes NOTHING on any miss.
Idempotent (detects the v19.34.312 tag). Header-agnostic (works whether your
tree imports TB_* from triple_barrier_config or defines them inline).

Usage (from repo root, on the DGX):
    python apply_v312.py --check     # dry-run
    python apply_v312.py             # apply
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
TAG = "v19.34.312"
DRY = "--check" in sys.argv

TFT = "backend/services/ai_modules/temporal_fusion_transformer.py"
TESTF = "backend/tests/test_tft_alignment.py"


class Abort(Exception):
    pass


def _read(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        raise Abort(f"file not found: {rel}")
    return open(p).read()


def _write(rel, content):
    open(os.path.join(ROOT, rel), "w").write(content)


def replace_once(c, old, new, label):
    n = c.count(old)
    if n != 1:
        raise Abort(f"[{label}] expected exactly 1 match, found {n}.\nAnchor:\n---\n{old[:240]}\n---")
    return c.replace(old, new)


WINDOW_HELPER = '''VAL_CHUNK = 16384

# v19.34.312 — Training window. The daily axis spans ~20yr but intraday history only
# reaches ~2020 (1h) / ~2024 (5m/15m), so older daily rows have empty multi-TF blocks.
# Restricting training to the intraday-dense era (default 2020-03-27, the start of
# hourly history) makes the multi-timeframe features actually populated. Override via
# the TFT_MIN_DATE env var ("" / "none" / "off" disables windowing).
TFT_MIN_DATE_DEFAULT = "2020-03-27"


def _date_to_epoch(d) -> float:
    """Convert a bar 'date' (datetime / ISO str / epoch) to UTC epoch seconds; NaN if unknown."""
    if d is None or isinstance(d, bool):
        return float("nan")
    if isinstance(d, (int, float)):
        return float(d)
    if isinstance(d, datetime):
        return d.timestamp()
    if isinstance(d, str):
        try:
            return datetime.fromisoformat(d.replace("Z", "+00:00")).timestamp()
        except Exception:
            pass
    try:
        return float(np.datetime64(d).astype("datetime64[s]").astype("int64"))
    except Exception:
        return float("nan")'''


def patch_tft(c):
    # 1. import os — robust (idempotent, anchored on the sole 'import logging' line)
    if "\nimport os\n" not in c and not c.startswith("import os\n"):
        lines = c.splitlines(keepends=True)
        for i, ln in enumerate(lines):
            if ln.strip() == "import logging":
                lines.insert(i + 1, "import os\n")
                c = "".join(lines)
                break
        else:
            raise Abort("os: could not find 'import logging' to anchor os import")

    # 2. drop "1 min" timeframe (60 -> 48)
    c = replace_once(
        c,
        '# Timeframes used by TFT (ordered from fastest to slowest)\n'
        'TFT_TIMEFRAMES = ["1 min", "5 mins", "15 mins", "1 hour", "1 day"]\n'
        'FEATURES_PER_TF = 12  # Features extracted per timeframe\n'
        'TOTAL_INPUT_DIM = len(TFT_TIMEFRAMES) * FEATURES_PER_TF  # 60',
        '# Timeframes used by TFT (ordered from fastest to slowest).\n'
        '# v19.34.312 — dropped "1 min": only ~4 months of history (0.2% coverage) made it\n'
        '# pure noise. Kept 5m/15m/1h/1d, densely populated by the 2020+ training window.\n'
        'TFT_TIMEFRAMES = ["5 mins", "15 mins", "1 hour", "1 day"]\n'
        'FEATURES_PER_TF = 12  # Features extracted per timeframe\n'
        'TOTAL_INPUT_DIM = len(TFT_TIMEFRAMES) * FEATURES_PER_TF  # 48 (4 timeframes × 12)',
        "tft.timeframes",
    )

    # 3. window helper + TFT_MIN_DATE (anchored ONLY on the VAL_CHUNK line so it works
    #    whether your header follows VAL_CHUNK with a TB import or with def _try_import_torch)
    c = replace_once(c, "VAL_CHUNK = 16384", WINDOW_HELPER, "tft.window_helper")

    # 4. model instantiation — use dynamic timeframe count (was hardcoded TFT())
    c = replace_once(
        c,
        "        self._model = TFT().to(self._device)",
        "        self._model = TFT(n_timeframes=len(TFT_TIMEFRAMES), features_per_tf=FEATURES_PER_TF).to(self._device)  # v19.34.312",
        "tft.model_instantiation",
    )

    # 5. train() signature — add min_date kwarg
    c = replace_once(
        c,
        "    async def train(self, db=None, max_symbols: int = 500, epochs: int = 50, batch_size: int = 512) -> Dict[str, Any]:",
        "    async def train(self, db=None, max_symbols: int = 500, epochs: int = 50, batch_size: int = 512, min_date: Optional[str] = None) -> Dict[str, Any]:",
        "tft.train_signature",
    )

    # 6. window resolution after the Starting log
    c = replace_once(
        c,
        '        logger.info("[TFT] Starting multi-timeframe training...")',
        '        logger.info("[TFT] Starting multi-timeframe training...")\n'
        '\n'
        '        # v19.34.312 — resolve training window (intraday-dense era). Older daily rows\n'
        '        # (pre-intraday history) have empty multi-TF blocks and dilute the signal.\n'
        '        _win = min_date if min_date is not None else os.environ.get("TFT_MIN_DATE", TFT_MIN_DATE_DEFAULT)\n'
        '        min_epoch = None\n'
        '        if _win and str(_win).strip().lower() not in ("", "none", "off", "0"):\n'
        '            _me = _date_to_epoch(str(_win).strip())\n'
        '            if np.isfinite(_me):\n'
        '                min_epoch = _me\n'
        '                logger.info(f"[TFT] Training window: samples on/after {_win} (intraday-dense era)")\n'
        '            else:\n'
        '                logger.warning(f"[TFT] Could not parse TFT_MIN_DATE={_win!r}; using full history")\n'
        '        if min_epoch is None:\n'
        '            logger.info("[TFT] Training window: full history (windowing disabled)")',
        "tft.window_resolution",
    )

    # 7. label-loop window filter
    c = replace_once(
        c,
        "            for i in range(usable):\n"
        "                current_idx = 20 + i\n"
        "                if current_idx >= len(atr_series):\n"
        "                    keep_mask.append(False)\n"
        "                    continue\n"
        "                atr_val = atr_series[current_idx]",
        "            for i in range(usable):\n"
        "                current_idx = 20 + i\n"
        "                if current_idx >= len(atr_series):\n"
        "                    keep_mask.append(False)\n"
        "                    continue\n"
        "                # v19.34.312 — restrict training samples to the intraday-dense window\n"
        "                if min_epoch is not None and current_idx < len(daily_bars):\n"
        "                    if _date_to_epoch(daily_bars[current_idx].get(\"date\")) < min_epoch:\n"
        "                        keep_mask.append(False)\n"
        "                        continue\n"
        "                atr_val = atr_series[current_idx]",
        "tft.label_window_filter",
    )
    return c


TEST_FILE = r'''"""
Unit tests for the TFT feature/window pipeline (v19.34.311 alignment + v19.34.312
intraday-dense window / 1-min drop). Pure numpy — no torch/DB needed.
"""
import os
import sys
from datetime import datetime, timezone, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ai_modules.temporal_fusion_transformer import (
    TFTModel, TFT_TIMEFRAMES, FEATURES_PER_TF, TOTAL_INPUT_DIM, _date_to_epoch,
)


def test_timeframes_v312():
    assert "1 min" not in TFT_TIMEFRAMES
    assert TFT_TIMEFRAMES == ["5 mins", "15 mins", "1 hour", "1 day"]
    assert TOTAL_INPUT_DIM == 48
    e1 = _date_to_epoch(datetime(2020, 3, 27, tzinfo=timezone.utc))
    e2 = _date_to_epoch("2020-03-27T00:00:00+00:00")
    assert abs(e1 - e2) < 1.0 and e1 > 0
    assert _date_to_epoch(None) != _date_to_epoch(None)  # NaN
    print("PASS: v312 timeframes (4 TFs, 48-dim) + date helper")


def _daily_bars(n, start_price=100.0, day0=None):
    day0 = day0 or datetime(2020, 1, 1, tzinfo=timezone.utc)
    bars, p, rng = [], start_price, np.random.default_rng(7)
    for i in range(n):
        p *= (1 + rng.normal(0, 0.01))
        bars.append({"close": float(p), "high": float(p * 1.01), "low": float(p * 0.99),
                     "volume": 1_000_000, "date": day0 + timedelta(days=i)})
    return bars


def _intraday_bars(n, start_price=100.0, t0=None, step_min=5):
    t0 = t0 or datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    bars, p, rng = [], start_price, np.random.default_rng(11)
    for i in range(n):
        p *= (1 + rng.normal(0, 0.002))
        bars.append({"close": float(p), "high": float(p * 1.002), "low": float(p * 0.998),
                     "volume": 50_000, "date": t0 + timedelta(minutes=step_min * i)})
    return bars


def test_shape_and_daily_axis_alignment():
    out = TFTModel().extract_multi_tf_features("TEST", {"1 day": _daily_bars(300)})
    assert out is not None and out.shape == (280, TOTAL_INPUT_DIM)
    for p, tf in enumerate(TFT_TIMEFRAMES):
        block = out[:, p * FEATURES_PER_TF:(p + 1) * FEATURES_PER_TF]
        if tf == "1 day":
            assert np.any(block != 0.0)
        else:
            assert np.all(block == 0.0)
    print("PASS: shape + daily-axis alignment + zero-padding")


def test_scale_free():
    m = TFTModel()
    c = m.extract_multi_tf_features("CHEAP", {"1 day": _daily_bars(300, 5.0)})
    p = m.extract_multi_tf_features("PRICEY", {"1 day": _daily_bars(300, 900.0)})
    dp = TFT_TIMEFRAMES.index("1 day")
    cb = c[:, dp * FEATURES_PER_TF:(dp + 1) * FEATURES_PER_TF]
    pb = p[:, dp * FEATURES_PER_TF:(dp + 1) * FEATURES_PER_TF]
    ratio = (np.nanmax(np.abs(pb)) + 1e-9) / (np.nanmax(np.abs(cb)) + 1e-9)
    assert 0.05 < ratio < 20, f"scales diverge with price (ratio={ratio:.2f})"
    print(f"PASS: scale-free (ratio={ratio:.2f})")


def test_as_of_no_lookahead():
    daily = _daily_bars(1600, day0=datetime(2020, 1, 1, tzinfo=timezone.utc))
    intraday = _intraday_bars(2000, t0=datetime(2024, 1, 2, 9, 30, tzinfo=timezone.utc))
    out = TFTModel().extract_multi_tf_features("TEST", {"1 day": daily, "5 mins": intraday})
    p5 = TFT_TIMEFRAMES.index("5 mins")
    blk = out[:, p5 * FEATURES_PER_TF:(p5 + 1) * FEATURES_PER_TF]
    dates = [b["date"] for b in daily[20:]]
    first = intraday[0]["date"]
    pre = [i for i, d in enumerate(dates) if d < first]
    post = [i for i, d in enumerate(dates) if d >= first]
    assert pre and np.all(blk[pre] == 0.0), "look-ahead leak"
    assert post and np.any(blk[post] != 0.0), "intraday not populated post-history"
    print(f"PASS: as-of join ({len(pre)} pre zeroed, {len(post)} post filled)")


def test_none_guards():
    m = TFTModel()
    assert m.extract_multi_tf_features("X", {"1 day": _daily_bars(10)}) is None
    assert m.extract_multi_tf_features("X", {}) is None
    print("PASS: None guards")


if __name__ == "__main__":
    test_timeframes_v312()
    test_shape_and_daily_axis_alignment()
    test_scale_free()
    test_as_of_no_lookahead()
    test_none_guards()
    print("\nALL TFT TESTS PASSED")
'''


def main():
    c = _read(TFT)
    if TAG in c:
        print(f"Already patched ({TAG}); ensuring test file is current.")
        if not DRY:
            _write(TESTF, TEST_FILE)
        return
    new_c = patch_tft(c)
    if DRY:
        print(f"[check] would patch: {TFT}")
        print(f"[check] would (re)write test: {TESTF}")
        print("DRY-RUN OK — all anchors matched.")
        return
    _write(TFT, new_c)
    print(f"patched: {TFT}")
    _write(TESTF, TEST_FILE)
    print(f"wrote:   {TESTF}")
    print(f"\n{TAG} applied. Next:")
    print("  source .venv/bin/activate && python backend/tests/test_tft_alignment.py")
    print("  ./start_backend.sh --force")
    print("  # then re-run:  curl -sS -X POST http://localhost:8001/api/ai-training/start "
          "-H 'Content-Type: application/json' -d '{\"phases\":[\"dl\"],\"force_retrain\":true}'")


if __name__ == "__main__":
    try:
        main()
    except Abort as e:
        print(f"\nABORTED — nothing written.\n{e}", file=sys.stderr)
        sys.exit(1)
