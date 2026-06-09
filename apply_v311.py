#!/usr/bin/env python3
"""
apply_v311.py — self-verifying patcher for v19.34.311
=====================================================
TFT/CNN-LSTM deep-learning collapse + OOM fix.

Why a script (not a .patch): the DGX tree diverged from the patch base in the
module headers (inline TB_* constants vs a triple_barrier_config import), which
broke `git apply` context. This patcher edits by EXACT anchor strings that are
confirmed present on the DGX, plus one function-boundary replacement — so it is
immune to header drift and line-number shifts.

Behaviour: it validates EVERY anchor first (counts occurrences). If anything is
missing or ambiguous it ABORTS and writes NOTHING. Idempotent: re-running on an
already-patched tree is a no-op (detects the v19.34.311 tag).

Usage (from repo root, on the DGX):
    python apply_v311.py            # apply
    python apply_v311.py --check    # dry-run: report what would change
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
TAG = "v19.34.311"
DRY = "--check" in sys.argv

TFT = "backend/services/ai_modules/temporal_fusion_transformer.py"
CNN = "backend/services/ai_modules/cnn_lstm_model.py"
AIT = "backend/routers/ai_training.py"
SCAN = "backend/services/market_scanner_service.py"
MON = "documents/scripts/monitor_training.sh"
TESTF = "backend/tests/test_tft_alignment.py"


class Abort(Exception):
    pass


def _read(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        raise Abort(f"file not found: {rel}")
    with open(p, "r") as f:
        return f.read()


def _write(rel, content):
    p = os.path.join(ROOT, rel)
    with open(p, "w") as f:
        f.write(content)


def replace_once(content, old, new, label):
    n = content.count(old)
    if n != 1:
        raise Abort(f"[{label}] expected exactly 1 match, found {n}. Anchor:\n---\n{old[:200]}\n---")
    return content.replace(old, new)


def insert_after_line_containing(content, needle, block, label):
    lines = content.splitlines(keepends=True)
    hits = [i for i, ln in enumerate(lines) if needle in ln]
    if len(hits) != 1:
        raise Abort(f"[{label}] expected exactly 1 line containing {needle!r}, found {len(hits)}")
    i = hits[0]
    lines.insert(i + 1, block)
    return "".join(lines)


# ───────────────────────── new code blocks ─────────────────────────

NEW_EXTRACT = '''    def extract_multi_tf_features(self, symbol: str, bars_by_tf: Dict[str, List[Dict]]) -> Optional[np.ndarray]:
        """
        Extract features for a single symbol across multiple timeframes —
        DAILY-ANCHORED and TIMESTAMP-ALIGNED. (v19.34.311 — collapse root-cause fix.)

        For each daily bar (the prediction anchor at date D), the intraday-
        timeframe feature block is the most recent intraday bar AS OF date D
        (as-of join, no look-ahead). Missing/short timeframes are zero-filled.

        This replaces the previous end-index concatenation, which had two fatal
        bugs that caused the majority-class collapse (val_acc ≈ baseline):
          1. It paired position-matched rows across timeframes, so a daily bar
             from years ago could sit on the same row as a 1-min bar from today.
          2. Whenever any intraday timeframe was shorter than the daily history
             (i.e. ALWAYS), it returned the *recent* daily rows while the caller's
             label loop assumed row i ↔ daily bar (20 + i) — so the features and
             their triple-barrier labels were misaligned → effectively random
             targets → the model could only learn "predict the majority class".

        Returns:
            np.ndarray of shape (n_daily_rows, TOTAL_INPUT_DIM) aligned so that
            row i corresponds to daily bar (i + 20), or None.
        """
        daily_bars = bars_by_tf.get("1 day")
        if not daily_bars or len(daily_bars) < 30:
            return None

        def _to_epoch(d) -> float:
            if isinstance(d, bool):
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
                return float("nan")

        def _tf_feature_matrix(bars):
            """Return (feats[n-20, 12], epochs[n-20]) for a timeframe, or (None, None)."""
            if not bars or len(bars) < 21:
                return None, None
            closes = np.array([b["close"] for b in bars], dtype=np.float32)
            highs = np.array([b["high"] for b in bars], dtype=np.float32)
            lows = np.array([b["low"] for b in bars], dtype=np.float32)
            volumes = np.array([b.get("volume", 0) for b in bars], dtype=np.float32)
            n = len(closes)
            feats = np.zeros((n - 20, FEATURES_PER_TF), dtype=np.float32)
            for i in range(20, n):
                idx = i - 20
                # Returns (all scale-free %)
                feats[idx, 0] = (closes[i] / closes[i - 1] - 1) * 100
                feats[idx, 1] = (closes[i] / closes[max(0, i - 5)] - 1) * 100
                feats[idx, 2] = (closes[i] / closes[max(0, i - 10)] - 1) * 100
                feats[idx, 3] = (closes[i] / closes[max(0, i - 20)] - 1) * 100
                # Volatility
                ret_window = np.diff(np.log(closes[max(0, i - 10):i + 1]))
                feats[idx, 4] = np.std(ret_window) * 100 if len(ret_window) > 1 else 0
                # RSI-14
                window = closes[max(0, i - 14):i + 1]
                deltas = np.diff(window)
                gains = np.maximum(deltas, 0)
                losses = np.maximum(-deltas, 0)
                avg_gain = np.mean(gains) if len(gains) > 0 else 0
                avg_loss = np.mean(losses) if len(losses) > 0 else 0.001
                feats[idx, 5] = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 50
                # High-Low range %
                feats[idx, 6] = (highs[i] - lows[i]) / closes[i] * 100 if closes[i] > 0 else 0
                # Close position in range
                hl_range = highs[i] - lows[i]
                feats[idx, 7] = (closes[i] - lows[i]) / hl_range if hl_range > 0 else 0.5
                # Volume ratio
                vol_5 = np.mean(volumes[max(0, i - 5):i + 1])
                vol_20 = np.mean(volumes[max(0, i - 20):i + 1])
                feats[idx, 8] = vol_5 / vol_20 if vol_20 > 0 else 1.0
                # SMA distance %
                sma20 = np.mean(closes[max(0, i - 20):i + 1])
                feats[idx, 9] = (closes[i] / sma20 - 1) * 100 if sma20 > 0 else 0
                # feat 10: SCALE-FREE 50-bar return (was raw price delta
                # closes[i]-closes[i-10], which dwarfed every other feature for
                # high-priced names and injected noise under the global scaler).
                feats[idx, 10] = (closes[i] / closes[max(0, i - 50)] - 1) * 100
                # Trend strength (ADX-like, scale-free)
                feats[idx, 11] = abs(feats[idx, 3]) / (feats[idx, 4] + 0.01)
            epochs = np.array([_to_epoch(b.get("date")) for b in bars[20:]], dtype=np.float64)
            return feats, epochs

        daily_feats, daily_epochs = _tf_feature_matrix(daily_bars)
        if daily_feats is None or len(daily_feats) < 10:
            return None

        n_rows = len(daily_feats)
        out = np.zeros((n_rows, TOTAL_INPUT_DIM), dtype=np.float32)
        daily_epochs_ok = bool(np.all(np.isfinite(daily_epochs)))

        for p, tf in enumerate(TFT_TIMEFRAMES):
            col0 = p * FEATURES_PER_TF
            col1 = col0 + FEATURES_PER_TF
            if tf == "1 day":
                out[:, col0:col1] = daily_feats
                continue
            tf_feats, tf_epochs = _tf_feature_matrix(bars_by_tf.get(tf, []))
            if tf_feats is None:
                continue  # timeframe unavailable for this symbol → leave zeros
            if (not daily_epochs_ok) or (not np.all(np.isfinite(tf_epochs))):
                continue  # cannot time-align safely → leave zeros (no look-ahead)
            # As-of join: latest intraday bar with epoch <= the daily anchor epoch.
            pos = np.searchsorted(tf_epochs, daily_epochs, side="right") - 1
            valid = pos >= 0
            if np.any(valid):
                out[valid, col0:col1] = tf_feats[pos[valid]]
        return out

    async def train'''

OLD_EXTRACT_HEAD = '''    def extract_multi_tf_features(self, symbol: str, bars_by_tf: Dict[str, List[Dict]]) -> Optional[np.ndarray]:'''
OLD_EXTRACT_TAIL = '''        # Concatenate: (n_samples, 5 * 12 = 60)
        return np.hstack(aligned)

    async def train'''


def patch_tft(c):
    # 1. VAL_CHUNK constant
    c = replace_once(
        c,
        "TOTAL_INPUT_DIM = len(TFT_TIMEFRAMES) * FEATURES_PER_TF  # 60",
        "TOTAL_INPUT_DIM = len(TFT_TIMEFRAMES) * FEATURES_PER_TF  # 60\n"
        "\n"
        "# v19.34.311 — Validation forward-pass chunk size. Running the full val set\n"
        "# (450k+ rows) through the model in ONE forward call builds multi-GB activation\n"
        "# tensors per epoch, which OOM-kills the subprocess on the DGX Spark's unified\n"
        "# memory. Chunking keeps the transient footprint flat.\n"
        "VAL_CHUNK = 16384",
        "tft.VAL_CHUNK",
    )
    # 2. extract_multi_tf_features — full-function replace by boundaries
    start = c.find(OLD_EXTRACT_HEAD)
    if start == -1:
        raise Abort("tft.extract: signature not found")
    tail = c.find(OLD_EXTRACT_TAIL, start)
    if tail == -1:
        raise Abort("tft.extract: end boundary (return np.hstack(aligned) + async def train) not found")
    end = tail + len(OLD_EXTRACT_TAIL)
    if c.count(OLD_EXTRACT_TAIL) != 1:
        raise Abort("tft.extract: end boundary not unique")
    c = c[:start] + NEW_EXTRACT + c[end:]
    # 3. coverage diagnostic (best-effort but verified-present line)
    c = insert_after_line_containing(
        c,
        '[TFT] Training data:',
        "\n        # v19.34.311 — Multi-timeframe coverage diagnostic — fraction of rows with any\n"
        "        # non-zero value per timeframe block (reveals real intraday coverage).\n"
        "        try:\n"
        "            _cov = []\n"
        "            for _p, _tf in enumerate(TFT_TIMEFRAMES):\n"
        "                _blk = X[:, _p * FEATURES_PER_TF:(_p + 1) * FEATURES_PER_TF]\n"
        "                _frac = float(np.mean(np.any(_blk != 0.0, axis=1))) if len(X) else 0.0\n"
        "                _cov.append(f\"{_tf}={_frac:.1%}\")\n"
        "            logger.info(f\"[TFT] Timeframe coverage (non-zero rows): {', '.join(_cov)}\")\n"
        "        except Exception:\n"
        "            pass\n",
        "tft.coverage",
    )
    # 4. chunked validation
    c = replace_once(
        c,
        "            # Validate\n"
        "            self._model.eval()\n"
        "            with torch.no_grad():\n"
        "                val_dir, val_conf, _, _ = self._model(X_val_t)\n"
        "                val_pred = torch.argmax(val_dir, dim=-1)\n"
        "                val_acc = (val_pred == y_val_t).float().mean().item()",
        "            # v19.34.311 — Validate CHUNKED to avoid a multi-GB activation spike on\n"
        "            # unified memory (the all-at-once forward over the full val set was\n"
        "            # OOM-killing the subprocess; SIGKILL, no traceback).\n"
        "            self._model.eval()\n"
        "            correct = 0\n"
        "            with torch.no_grad():\n"
        "                for vs in range(0, len(X_val_t), VAL_CHUNK):\n"
        "                    vd, _, _, _ = self._model(X_val_t[vs:vs + VAL_CHUNK])\n"
        "                    vp = torch.argmax(vd, dim=-1)\n"
        "                    correct += (vp == y_val_t[vs:vs + VAL_CHUNK]).sum().item()\n"
        "            val_acc = correct / len(X_val_t) if len(X_val_t) else 0.0\n"
        "            if torch.cuda.is_available():\n"
        "                torch.cuda.empty_cache()",
        "tft.val_chunked",
    )
    return c


def patch_cnn(c):
    # 1. VAL_CHUNK constant
    c = replace_once(
        c,
        'DIRECTIONS = ["down", "flat", "up"]  # Triple-barrier class order: -1/0/+1',
        'DIRECTIONS = ["down", "flat", "up"]  # Triple-barrier class order: -1/0/+1\n'
        "\n"
        "# v19.34.311 — Validation forward-pass chunk size — see temporal_fusion_transformer.py.\n"
        "# The sequence dim makes the all-at-once val forward even heavier here, so we chunk\n"
        "# it to avoid OOM-killing the subprocess on unified memory.\n"
        "VAL_CHUNK = 8192",
        "cnn.VAL_CHUNK",
    )
    # 2. feat[15] scale-free
    c = replace_once(
        c,
        "            feat[15] = closes[i] - np.mean(closes[max(0, i - 20):i + 1])  # distance from SMA20",
        "            # feat 15: v19.34.311 — SCALE-FREE 50-bar return (was raw $ distance from\n"
        "            # SMA20, which dwarfed other features for high-priced names under the\n"
        "            # single global scaler).\n"
        "            feat[15] = (closes[i] / closes[max(0, i - 50)] - 1) * 100  # 50-bar return",
        "cnn.feat15",
    )
    # 3. chunked validation
    c = replace_once(
        c,
        "            # Validate\n"
        "            self._model.eval()\n"
        "            with torch.no_grad():\n"
        "                val_dir, _val_win, _ = self._model(X_val_t)\n"
        "                val_pred = torch.argmax(val_dir, dim=-1)\n"
        "                val_acc = (val_pred == y_val_t).float().mean().item()",
        "            # v19.34.311 — Validate CHUNKED (sequence dim makes this the heaviest\n"
        "            # all-at-once op; was OOM-killing the subprocess on unified memory).\n"
        "            self._model.eval()\n"
        "            correct = 0\n"
        "            with torch.no_grad():\n"
        "                for vs in range(0, len(X_val_t), VAL_CHUNK):\n"
        "                    vd, _, _ = self._model(X_val_t[vs:vs + VAL_CHUNK])\n"
        "                    vp = torch.argmax(vd, dim=-1)\n"
        "                    correct += (vp == y_val_t[vs:vs + VAL_CHUNK]).sum().item()\n"
        "            val_acc = correct / len(X_val_t) if len(X_val_t) else 0.0\n"
        "            if torch.cuda.is_available():\n"
        "                torch.cuda.empty_cache()",
        "cnn.val_chunked",
    )
    return c


def patch_ait(c):
    c = replace_once(
        c,
        '    # Read result from MongoDB and restore focus mode\n'
        '    logger.info("[TRAINING] Restoring LIVE mode")\n'
        '    try:\n'
        '        from server import db as mongo_db\n'
        '        if mongo_db is not None:\n'
        '            result_doc = await asyncio.to_thread(\n'
        '                mongo_db["training_pipeline_result"].find_one,\n'
        '                {"_id": "latest"}, {"_id": 0}\n'
        '            )\n'
        '            if result_doc:\n'
        '                _last_result = result_doc.get("result")\n'
        '    except Exception as e:\n'
        '        logger.warning(f"[TRAINING] Failed to read result: {e}")',
        '    # Read result from MongoDB and restore focus mode\n'
        '    logger.info("[TRAINING] Restoring LIVE mode")\n'
        '    try:\n'
        '        from server import db as mongo_db\n'
        '        if mongo_db is not None:\n'
        '            result_doc = await asyncio.to_thread(\n'
        '                mongo_db["training_pipeline_result"].find_one,\n'
        '                {"_id": "latest"}, {"_id": 0}\n'
        '            )\n'
        '            if result_doc:\n'
        '                _last_result = result_doc.get("result")\n'
        '\n'
        '            # v19.34.311 — Honest status. A SIGKILL/segfault (e.g. OOM kill,\n'
        '            # exit_code < 0) cannot be caught by the subprocess try/except, so it\n'
        '            # never writes a failure status — leaving the dashboard stuck on the\n'
        '            # last RUNNING phase. Detect an abnormal exit with no success result\n'
        '            # and mark the pipeline FAILED so the UI reflects reality.\n'
        '            succeeded = bool(isinstance(_last_result, dict) and not _last_result.get("error"))\n'
        '            if exit_code is not None and exit_code != 0 and not succeeded:\n'
        '                if exit_code < 0:\n'
        '                    sig = -exit_code\n'
        '                    if sig == 9:\n'
        '                        err_msg = ("Training process was OOM-killed (SIGKILL/-9): ran out of "\n'
        '                                   "unified memory. Lower batch size / symbol cap and retry.")\n'
        '                    else:\n'
        '                        err_msg = (f"Training process terminated by signal {sig} "\n'
        '                                   f"(no traceback — killed by the OS, not a Python error).")\n'
        '                else:\n'
        '                    err_msg = (f"Training process exited abnormally (code {exit_code}). "\n'
        '                               f"See training_subprocess.log.")\n'
        '                logger.error(f"[TRAINING] {err_msg}")\n'
        '                await asyncio.to_thread(\n'
        '                    mongo_db["training_pipeline_status"].update_one,\n'
        '                    {"_id": "pipeline"},\n'
        '                    {"$set": {\n'
        '                        "phase": "error",\n'
        '                        "status": "failed",\n'
        '                        "error": err_msg,\n'
        '                        "current_model": "",\n'
        '                        "current_phase_progress": 0,\n'
        '                        "updated_at": datetime.now(timezone.utc).isoformat(),\n'
        '                    }},\n'
        '                    upsert=True,\n'
        '                )\n'
        '    except Exception as e:\n'
        '        logger.warning(f"[TRAINING] Failed to read result / write failure status: {e}")',
        "ait.honest_status",
    )
    return c


def patch_scan(c):
    return replace_once(
        c,
        "    max_price: float = 500.0",
        "    max_price: float = 1000.0  # v19.34.311 — widened $500→$1000 (operator: trade up to $1k)",
        "scan.max_price",
    )


def patch_mon(c):
    return replace_once(
        c,
        "    local n_procs=$(pgrep -fc training_subprocess 2>/dev/null || echo 0)",
        "    # v19.34.311 — sanitize n_procs (pgrep -fc can emit empty/multiline → integer-expr error)\n"
        "    local n_procs=$(pgrep -fc training_subprocess 2>/dev/null | head -n1)\n"
        '    [[ "$n_procs" =~ ^[0-9]+$ ]] || n_procs=0',
        "mon.n_procs",
    )


TEST_FILE = '''"""
Unit tests for the v19.34.311 daily-anchored, timestamp-aligned TFT features.
Guards the fix for the majority-class collapse (feature/label misalignment).
"""
import os
import sys
from datetime import datetime, timezone, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ai_modules.temporal_fusion_transformer import (
    TFTModel, TFT_TIMEFRAMES, FEATURES_PER_TF, TOTAL_INPUT_DIM,
)


def _daily_bars(n, start_price=100.0, day0=None):
    day0 = day0 or datetime(2020, 1, 1, tzinfo=timezone.utc)
    bars = []
    p = start_price
    rng = np.random.default_rng(7)
    for i in range(n):
        p *= (1 + rng.normal(0, 0.01))
        bars.append({"close": float(p), "high": float(p * 1.01), "low": float(p * 0.99),
                     "volume": 1_000_000, "date": day0 + timedelta(days=i)})
    return bars


def _intraday_bars(n, start_price=100.0, t0=None, step_min=5):
    t0 = t0 or datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    bars = []
    p = start_price
    rng = np.random.default_rng(11)
    for i in range(n):
        p *= (1 + rng.normal(0, 0.002))
        bars.append({"close": float(p), "high": float(p * 1.002), "low": float(p * 0.998),
                     "volume": 50_000, "date": t0 + timedelta(minutes=step_min * i)})
    return bars


def test_shape_and_daily_axis_alignment():
    m = TFTModel()
    daily = _daily_bars(300)
    out = m.extract_multi_tf_features("TEST", {"1 day": daily})
    assert out is not None and out.shape == (len(daily) - 20, TOTAL_INPUT_DIM)
    for p, tf in enumerate(TFT_TIMEFRAMES):
        block = out[:, p * FEATURES_PER_TF:(p + 1) * FEATURES_PER_TF]
        if tf == "1 day":
            assert np.any(block != 0.0)
        else:
            assert np.all(block == 0.0)
    print("PASS: shape + daily-axis alignment + zero-padding")


def test_scale_free():
    m = TFTModel()
    cheap = m.extract_multi_tf_features("CHEAP", {"1 day": _daily_bars(300, 5.0)})
    pricey = m.extract_multi_tf_features("PRICEY", {"1 day": _daily_bars(300, 900.0)})
    dp = TFT_TIMEFRAMES.index("1 day")
    c = cheap[:, dp * FEATURES_PER_TF:(dp + 1) * FEATURES_PER_TF]
    p = pricey[:, dp * FEATURES_PER_TF:(dp + 1) * FEATURES_PER_TF]
    ratio = (np.nanmax(np.abs(p)) + 1e-9) / (np.nanmax(np.abs(c)) + 1e-9)
    assert 0.05 < ratio < 20, f"scales diverge with price (ratio={ratio:.2f})"
    print(f"PASS: scale-free (ratio={ratio:.2f})")


def test_as_of_no_lookahead():
    m = TFTModel()
    daily = _daily_bars(1600, day0=datetime(2020, 1, 1, tzinfo=timezone.utc))
    intraday = _intraday_bars(2000, t0=datetime(2024, 1, 2, 9, 30, tzinfo=timezone.utc))
    out = m.extract_multi_tf_features("TEST", {"1 day": daily, "5 mins": intraday})
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
    test_shape_and_daily_axis_alignment()
    test_scale_free()
    test_as_of_no_lookahead()
    test_none_guards()
    print("\\nALL TFT ALIGNMENT TESTS PASSED")
'''


def main():
    targets = [
        (TFT, patch_tft),
        (CNN, patch_cnn),
        (AIT, patch_ait),
        (SCAN, patch_scan),
        (MON, patch_mon),
    ]
    # Idempotency / pre-flight: read all, compute new content, abort on any error.
    results = {}
    already = []
    for rel, fn in targets:
        c = _read(rel)
        if TAG in c:
            already.append(rel)
            continue
        results[rel] = fn(c)

    if already and not results:
        print(f"Already patched ({TAG}); nothing to do for: {', '.join(already)}")
        # still ensure the test file exists
    if already and results:
        raise Abort(f"Partial state: {already} already patched but others not. "
                    f"Manual review needed before re-running.")

    if DRY:
        for rel in results:
            print(f"[check] would patch: {rel}")
        print(f"[check] would (re)write test: {TESTF}")
        print("DRY-RUN OK — all anchors matched.")
        return

    for rel, new_c in results.items():
        _write(rel, new_c)
        print(f"patched: {rel}")
    _write(TESTF, TEST_FILE)
    print(f"wrote:   {TESTF}")
    print(f"\\n{TAG} applied. Next:")
    print("  source .venv/bin/activate && python backend/tests/test_tft_alignment.py")
    print("  ./start_backend.sh --force")


if __name__ == "__main__":
    try:
        main()
    except Abort as e:
        print(f"\\nABORTED — nothing written.\\n{e}", file=sys.stderr)
        sys.exit(1)
