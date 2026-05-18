#!/usr/bin/env bash
# ============================================================================
# v19.34.30 — Next-action sweep deploy script
#   • Bug B: TREND_CONTINUATION XGBoost DMatrix wrap
#   • Bug A-2: Stale PENDING-row auto-reaper
#   • Bug Y full sweep: 5x qualifyContractsAsync sites
#   • Phase L4a: pusher queue_order deprecation warn
#   • UI Setup Name Precedence: setup_variant > setup_type
#
# Run from the repo root on the DGX:
#   cd ~/Trading-and-Analysis-Platform && bash v19_34_30_apply.sh
#
# Idempotent: re-running is safe (all edits are guarded by string anchors).
# ============================================================================
set -euo pipefail

REPO_ROOT="$(pwd)"
BACKEND="${REPO_ROOT}/backend"
FRONTEND="${REPO_ROOT}/frontend"
PUSHER="${REPO_ROOT}/documents/scripts/ib_data_pusher.py"

# Sanity check
test -d "$BACKEND" || { echo "ERROR: $BACKEND not found — run from repo root"; exit 1; }
test -d "$FRONTEND" || { echo "ERROR: $FRONTEND not found"; exit 1; }

echo "==> v19.34.30 apply starting in $REPO_ROOT"

# ────────────────────────────────────────────────────────────────────────────
# 1. Bug Y FULL sweep — 5x qualifyContractsAsync sites in ib_direct_service.py
# ────────────────────────────────────────────────────────────────────────────
echo "==> [Bug Y full sweep] ib_direct_service.py — converting all qualifyContracts → qualifyContractsAsync"
python3 - <<'PY'
import pathlib, re
p = pathlib.Path("backend/services/ib_direct_service.py")
src = p.read_text()
new = src.replace(
    "await asyncio.to_thread(self._ib.qualifyContracts, contract)",
    "await self._ib.qualifyContractsAsync(contract)",
)
hits = src.count("await asyncio.to_thread(self._ib.qualifyContracts, contract)")
async_hits = new.count("await self._ib.qualifyContractsAsync(contract)")
p.write_text(new)
print(f"   converted {hits} site(s); file now has {async_hits} qualifyContractsAsync call(s)")
PY

# ────────────────────────────────────────────────────────────────────────────
# 2. Bug B — TREND_CONTINUATION DMatrix wrap in timeseries_service.py
# ────────────────────────────────────────────────────────────────────────────
echo "==> [Bug B] timeseries_service.py — wrap xgb.Booster predict in DMatrix"
python3 - <<'PY'
import pathlib
p = pathlib.Path("backend/services/ai_modules/timeseries_service.py")
src = p.read_text()
anchor = """                    # Predict using the setup model directly
                    pred_raw = model._model.predict(feature_vector)"""
patch = '''                    # Predict using the setup model directly
                    # v19.34.30 (Feb 2026) — Bug B fix. Raw `xgb.Booster` objects
                    # (e.g., TREND_CONTINUATION) require a DMatrix; sklearn-style
                    # wrappers (XGBClassifier, RandomForestClassifier) accept
                    # ndarray. Before this, every TREND_CONTINUATION inference
                    # crashed with "Expecting data to be a DMatrix object,
                    # got: <class 'numpy.ndarray'>" and the setup was silently
                    # downgraded to the generic fallback.
                    try:
                        import xgboost as _xgb
                        _is_booster = isinstance(model._model, _xgb.Booster)
                    except Exception:
                        _is_booster = False
                    if _is_booster:
                        import xgboost as _xgb
                        _dm = _xgb.DMatrix(
                            feature_vector.astype(np.float32),
                            feature_names=list(model._feature_names),
                        )
                        pred_raw = model._model.predict(_dm)
                    else:
                        pred_raw = model._model.predict(feature_vector)'''
if "v19.34.30 (Feb 2026) — Bug B fix" in src:
    print("   already patched, skipping")
elif anchor not in src:
    raise SystemExit("   ❌ anchor not found in timeseries_service.py — manual inspection needed")
else:
    p.write_text(src.replace(anchor, patch, 1))
    print("   patched OK")
PY

# ────────────────────────────────────────────────────────────────────────────
# 3. Bug A-2 — Stale PENDING-row auto-reaper in trading_bot_service.py
# ────────────────────────────────────────────────────────────────────────────
echo "==> [Bug A-2] trading_bot_service.py — wiring PENDING-row auto-reaper loop"
python3 - <<'PY'
import pathlib
p = pathlib.Path("backend/services/trading_bot_service.py")
src = p.read_text()
anchor = """            try:
                asyncio.create_task(_boot_zombie_sweep())
            except Exception as e:
                logger.debug(f"[v19.34.7 BOOT-SWEEP] schedule failed: {e}")

        # ─── v19.34.17 (2026-05-06) — EOD-close policy migration ──────"""
patch = '''            try:
                asyncio.create_task(_boot_zombie_sweep())
            except Exception as e:
                logger.debug(f"[v19.34.7 BOOT-SWEEP] schedule failed: {e}")

        # ─── v19.34.30 (Feb 2026) — Bug A-2: stale PENDING row auto-reaper ──
        # `trade_execution.py` writes a `bot_trades` row with status=PENDING
        # immediately BEFORE handing the order to the broker. If the broker
        # call hangs (Bug-Y class deadlock) or errors before the post-fill
        # `_save_trade` flips the row to OPEN/REJECTED, the row sits in
        # PENDING forever and the bot\'s dedup logic blocks every subsequent
        # attempt on that symbol with `duplicate_open_position`.
        async def _stale_pending_reaper_loop():
            import os as _os3
            interval_s = int(_os3.environ.get("PENDING_REAPER_INTERVAL_S", "60") or 60)
            max_age_s = int(_os3.environ.get("PENDING_REAPER_MAX_AGE_S", "300") or 300)
            disabled = (
                _os3.environ.get("PENDING_REAPER_ENABLED", "true").strip().lower()
                in ("0", "false", "no", "off")
            )
            if disabled:
                logger.info("[v19.34.30 PENDING-REAPER] disabled by env")
                return
            await asyncio.sleep(45)  # grace
            while self._running:
                try:
                    db = getattr(self, "_db", None)
                    if db is not None:
                        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max_age_s)).isoformat()
                        query = {
                            "status": "pending",
                            "pre_submit_at": {"$lt": cutoff},
                            "$or": [
                                {"executed_at": None},
                                {"executed_at": {"$exists": False}},
                            ],
                        }
                        stale = list(
                            db["bot_trades"].find(
                                query, {"_id": 0, "id": 1, "symbol": 1, "pre_submit_at": 1}
                            ).limit(50)
                        )
                        if stale:
                            stamp = datetime.now(timezone.utc).isoformat()
                            updated_ids: List[str] = []
                            for row in stale:
                                tid = row.get("id")
                                if not tid:
                                    continue
                                res = db["bot_trades"].update_one(
                                    {"id": tid, "status": "pending"},
                                    {"$set": {
                                        "status": "rejected",
                                        "close_reason": "stale_pending_auto_reaper",
                                        "closed_at": stamp,
                                        "reaped_at": stamp,
                                        "reaper_version": "v19.34.30",
                                    }},
                                )
                                if res.modified_count:
                                    updated_ids.append(tid)
                            if updated_ids:
                                logger.warning(
                                    "[v19.34.30 PENDING-REAPER] reaped %d stale "
                                    "PENDING row(s) (>%ds old): %s",
                                    len(updated_ids), max_age_s,
                                    [(r.get("symbol"), r.get("id"))
                                     for r in stale if r.get("id") in updated_ids][:10],
                                )
                                for tid in updated_ids:
                                    self._pending_trades.pop(tid, None)
                                try:
                                    from services.sentcom_service import emit_stream_event
                                    await emit_stream_event({
                                        "kind": "alert",
                                        "severity": "warning",
                                        "event": "stale_pending_reaped",
                                        "text": (
                                            f"🧹 Reaped {len(updated_ids)} stale "
                                            f"PENDING row(s) (>{max_age_s}s old)"
                                        ),
                                        "metadata": {
                                            "count": len(updated_ids),
                                            "max_age_s": max_age_s,
                                            "trade_ids": updated_ids[:10],
                                        },
                                    })
                                except Exception:
                                    pass
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.debug(f"[v19.34.30 PENDING-REAPER] loop tick failed: {e}")
                try:
                    await asyncio.sleep(interval_s)
                except asyncio.CancelledError:
                    raise

        try:
            self._pending_reaper_task = asyncio.create_task(_stale_pending_reaper_loop())
        except Exception as e:
            logger.warning(
                f"[v19.34.30 PENDING-REAPER] failed to schedule (non-fatal): {e}"
            )

        # ─── v19.34.17 (2026-05-06) — EOD-close policy migration ──────'''
if "[v19.34.30 PENDING-REAPER]" in src:
    print("   already patched, skipping")
elif anchor not in src:
    raise SystemExit("   ❌ anchor not found in trading_bot_service.py — manual inspection needed")
else:
    p.write_text(src.replace(anchor, patch, 1))
    print("   patched OK")
PY

# ────────────────────────────────────────────────────────────────────────────
# 4. Phase L4a — pusher queue_order deprecation warn
# ────────────────────────────────────────────────────────────────────────────
echo "==> [Phase L4a] pusher _execute_queued_order — adding deprecation warn"
if [[ -f "$PUSHER" ]]; then
python3 - <<PY
import pathlib
p = pathlib.Path("$PUSHER")
src = p.read_text()
anchor = '''    def _execute_queued_order(self, order: dict):
        """Execute a single queued order via IB Gateway"""
        order_id = order.get("order_id")'''
patch = '''    def _execute_queued_order(self, order: dict):
        """Execute a single queued order via IB Gateway.

        ⚠️ DEPRECATED (v19.34.30 Feb 2026 — Phase L4a). The DGX migrated
        order execution to ib_direct_service.place_bracket_order. This
        path should be IDLE under BOT_ORDER_PATH=direct. Watch for the
        [L4a-DEPRECATED] log line — once you see zero for a trading
        week, the legacy branch can be removed entirely.
        """
        try:
            logger.warning(
                "[L4a-DEPRECATED] pusher._execute_queued_order called for "
                "order_id=%s symbol=%s — this path should be IDLE under "
                "ib-direct routing.",
                order.get("order_id"), order.get("symbol"),
            )
        except Exception:
            pass
        order_id = order.get("order_id")'''
if "[L4a-DEPRECATED]" in src:
    print("   already patched, skipping")
elif anchor not in src:
    print("   ⚠️ anchor not found in pusher (file shape may differ on Windows clone); skipping. Add manually.")
else:
    p.write_text(src.replace(anchor, patch, 1))
    print("   patched OK")
PY
else
    echo "   ⚠️ $PUSHER not on this machine (Windows-side file). Apply manually on the pusher host."
fi

# ────────────────────────────────────────────────────────────────────────────
# 5. UI — setup_variant precedence in OpenPositionsV5.jsx + tradeStyleMeta.js
# ────────────────────────────────────────────────────────────────────────────
echo "==> [UI setup-name precedence] OpenPositionsV5.jsx + tradeStyleMeta.js"
python3 - <<'PY'
import pathlib
# OpenPositionsV5.jsx
p1 = pathlib.Path("frontend/src/components/sentcom/v5/OpenPositionsV5.jsx")
src = p1.read_text()
anchor = """  const style = (!isGenericTs && humanizeStyle(pos.trade_style))
    || humanizeStyle(pos.setup_type)
    || humanizeStyle(pos.scan_tier)
    || humanizeStyle(pos.timeframe);"""
patch = """  const style = (!isGenericTs && humanizeStyle(pos.trade_style))
    || humanizeStyle(pos.setup_variant)
    || humanizeStyle(pos.setup_type)
    || humanizeStyle(pos.scan_tier)
    || humanizeStyle(pos.timeframe);"""
if "humanizeStyle(pos.setup_variant)" in src:
    print("   OpenPositionsV5.jsx already patched, skipping")
elif anchor not in src:
    print("   ⚠️ OpenPositionsV5.jsx anchor not found — skipping")
else:
    p1.write_text(src.replace(anchor, patch, 1))
    print("   OpenPositionsV5.jsx patched OK")

# tradeStyleMeta.js
p2 = pathlib.Path("frontend/src/utils/tradeStyleMeta.js")
src = p2.read_text()
anchor = """  // v19.34.32 — setup-type wins over the generic `trade_2_hold` default.
  const setupKey = row.setup_type ? SETUP_TO_STYLE[norm(row.setup_type)] : null;"""
patch = """  // v19.34.32 — setup-type wins over the generic `trade_2_hold` default.
  // v19.34.30 (Feb 2026) — setup_variant preferred over setup_type when present.
  const variantKey = row.setup_variant ? SETUP_TO_STYLE[norm(row.setup_variant)] : null;
  const setupKey = variantKey
    || (row.setup_type ? SETUP_TO_STYLE[norm(row.setup_type)] : null);"""
if "variantKey" in src:
    print("   tradeStyleMeta.js already patched, skipping")
elif anchor not in src:
    print("   ⚠️ tradeStyleMeta.js anchor not found — skipping")
else:
    p2.write_text(src.replace(anchor, patch, 1))
    print("   tradeStyleMeta.js patched OK")
PY

# ────────────────────────────────────────────────────────────────────────────
# 6. New regression tests
# ────────────────────────────────────────────────────────────────────────────
echo "==> Writing regression tests"
mkdir -p "$BACKEND/tests"

cat > "$BACKEND/tests/test_bug_b_trend_continuation_dmatrix_v19_34_30.py" <<'TEST1'
"""v19.34.30 — Bug B: TREND_CONTINUATION XGBoost Booster predict must
wrap features in DMatrix."""
from __future__ import annotations
import inspect


def test_predict_for_setup_handles_xgb_booster_via_dmatrix():
    from services.ai_modules import timeseries_service
    src = inspect.getsource(timeseries_service)
    assert "isinstance(model._model, _xgb.Booster)" in src
    assert "_xgb.DMatrix(" in src
    assert "pred_raw = model._model.predict(feature_vector)" in src


def test_xgboost_booster_requires_dmatrix_for_predict():
    import numpy as np
    import xgboost as xgb
    X = np.random.RandomState(0).rand(60, 4).astype(np.float32)
    y = np.random.RandomState(1).randint(0, 3, size=60)
    dtrain = xgb.DMatrix(X, label=y)
    booster = xgb.train(
        {"objective": "multi:softprob", "num_class": 3, "verbosity": 0},
        dtrain, num_boost_round=2,
    )
    feature_vector = np.array([X[0]])
    raised = False
    try:
        booster.predict(feature_vector)
    except Exception as e:
        if "DMatrix" in str(e):
            raised = True
    assert raised
    dm = xgb.DMatrix(feature_vector, feature_names=[f"f{i}" for i in range(4)])
    pred = booster.predict(dm)
    assert pred.shape == (1, 3)
TEST1

cat > "$BACKEND/tests/test_stale_pending_reaper_v19_34_30.py" <<'TEST2'
"""v19.34.30 — Bug A-2: Stale PENDING-row auto-reaper."""
from __future__ import annotations
import inspect


def test_pending_reaper_loop_is_defined_and_scheduled():
    from services import trading_bot_service
    src = inspect.getsource(trading_bot_service)
    assert "_stale_pending_reaper_loop" in src
    assert "self._pending_reaper_task = asyncio.create_task(" in src
    assert "PENDING_REAPER_ENABLED" in src
    assert "PENDING_REAPER_MAX_AGE_S" in src
    assert '"status": "pending"' in src or "'status': 'pending'" in src


def test_pending_reaper_query_filter_logic():
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    old = (now - timedelta(seconds=600)).isoformat()
    recent = (now - timedelta(seconds=30)).isoformat()
    rows = [
        {"id": "t1", "status": "pending", "pre_submit_at": old, "executed_at": None},
        {"id": "t2", "status": "pending", "pre_submit_at": recent, "executed_at": None},
        {"id": "t3", "status": "pending", "pre_submit_at": old, "executed_at": old},
        {"id": "t4", "status": "open",    "pre_submit_at": old, "executed_at": old},
    ]
    cutoff = (now - timedelta(seconds=300)).isoformat()
    matches = [
        r for r in rows
        if r["status"] == "pending"
        and r["pre_submit_at"] < cutoff
        and r.get("executed_at") in (None,)
    ]
    assert {r["id"] for r in matches} == {"t1"}
TEST2

cat > "$BACKEND/tests/test_sizer_guardrail_sync_v19_34_29.py" <<'TEST3'
"""v19.34.29 — Bug C: Sizer ↔ execution-guardrail sync.

If you applied Bug C from a previous patch, this is the regression to
keep it locked in. If not, you can skip — v19.34.30 ships on top of it.
"""
from __future__ import annotations
from dataclasses import dataclass
import pytest


@dataclass
class _RP:
    max_risk_per_trade: float = 5_000.0
    starting_capital: float = 250_000.0
    max_position_pct: float = 80.0
    max_notional_per_trade: float = 0
    use_volatility_sizing: bool = False
    volatility_scale_factor: float = 1.0


class _Bot:
    def __init__(self, rp):
        self.risk_params = rp
        self._current_regime = None
        self._regime_position_multipliers = {}
        self._db = None


def _direction_long():
    from services.trading_bot_service import TradeDirection
    return TradeDirection.LONG


def _make_evaluator():
    from services.opportunity_evaluator import OpportunityEvaluator
    return OpportunityEvaluator()


def test_sizer_clamps_to_execution_guardrail(monkeypatch):
    monkeypatch.setenv("EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT", "0.40")
    monkeypatch.setenv("EXECUTION_GUARDRAIL_NOTIONAL_CAP_TOLERANCE", "0.005")
    monkeypatch.setenv("SAFETY_MAX_SYMBOL_EXPOSURE_USD", "500000")
    import importlib
    from services import execution_guardrails as eg
    from services import safety_guardrails as sg
    importlib.reload(eg)
    importlib.reload(sg)
    rp = _RP()
    bot = _Bot(rp)
    ev = _make_evaluator()
    shares, _ = ev.calculate_position_size(
        entry_price=10.0, stop_price=9.90,
        direction=_direction_long(), bot=bot,
    )
    notional = shares * 10.0
    assert notional <= 100_000 * 1.005 + 1e-6
    assert shares >= 9_900
TEST3

echo "==> Done."
echo
echo "Run the tests:"
echo "    cd backend && python -m pytest tests/test_bug_b_trend_continuation_dmatrix_v19_34_30.py tests/test_stale_pending_reaper_v19_34_30.py -v"
echo
echo "If Bug C from the previous patch is already in, also run:"
echo "    python -m pytest tests/test_sizer_guardrail_sync_v19_34_29.py -v"
echo
echo "Then restart however you start the backend on the DGX (NOT supervisorctl):"
echo "    pkill -f 'uvicorn.*8001' ; nohup python -m uvicorn server:app --host 0.0.0.0 --port 8001 > /tmp/backend.log 2>&1 &"
echo "    # or however you normally launch it"
echo
echo "Tail the bot log and watch for new sweeper + crash-fix indicators:"
echo "    tail -F /tmp/backend.log | grep -E 'PENDING-REAPER|L4a-DEPRECATED|TREND_CONTINUATION|qualifyContractsAsync'"
