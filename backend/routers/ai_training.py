"""
AI Training Pipeline API Router

Endpoints to trigger bulk model training, monitor progress,
and view results. All training runs asynchronously in the background.
"""

import logging
import asyncio
import subprocess
import sys
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-training", tags=["AI Training"])


class _TrainingProcess:
    """Wrapper around subprocess.Popen that provides .done() interface."""
    def __init__(self, proc, start_time=None):
        self._proc = proc
        self._start_time = start_time or datetime.now(timezone.utc)

    def done(self):
        return self._proc.poll() is not None

    def terminate(self):
        if self._proc.poll() is None:
            self._proc.terminate()

# Global training task reference
_training_task: Optional[asyncio.Task] = None
_last_result = None


class TrainingRequest(BaseModel):
    phases: Optional[List[str]] = None  # e.g., ["generic", "volatility", "exit"]
    bar_sizes: Optional[List[str]] = None  # e.g., ["1 day", "5 mins"]
    max_symbols: Optional[int] = None
    force_retrain: bool = False  # If True, retrain all models ignoring resume cache
    resume_max_age_hours: float = 24.0  # Skip models trained within N hours
    test_mode: bool = False  # Quick test: cap symbols to 50, bars to 5000


async def _monitor_training_process(task: _TrainingProcess):
    """Lightweight monitor that checks the subprocess every 10s and restores focus mode when done."""
    global _last_result
    while not task.done():
        await asyncio.sleep(10)

    # Subprocess finished — log exit code and output from log file
    exit_code = task._proc.returncode
    logger.info(f"[TRAINING] Subprocess finished with exit code: {exit_code}")
    try:
        log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'training_subprocess.log')
        with open(log_path, 'r') as f:
            log_output = f.read()[-2000:]
        if log_output:
            logger.info(f"[TRAINING] Subprocess output (last 2000 chars):\n{log_output}")
    except Exception:
        pass

    # Read result from MongoDB and restore focus mode
    logger.info("[TRAINING] Restoring LIVE mode")
    try:
        from server import db as mongo_db
        if mongo_db is not None:
            result_doc = await asyncio.to_thread(
                mongo_db["training_pipeline_result"].find_one,
                {"_id": "latest"}, {"_id": 0}
            )
            if result_doc:
                _last_result = result_doc.get("result")
    except Exception as e:
        logger.warning(f"[TRAINING] Failed to read result: {e}")

    try:
        from services.focus_mode_manager import focus_mode_manager
        focus_mode_manager.reset_to_live(result=_last_result)
    except Exception:
        pass


@router.post("/start")
async def start_training(request: TrainingRequest):
    """
    Start the bulk training pipeline in the background.
    Returns immediately with a task ID.
    """
    global _training_task, _last_result

    # OS-level guard: check if training_subprocess is already running as a system process
    # This catches orphaned processes that survive server restarts
    if os.name != 'nt':
        try:
            result = subprocess.run(
                ['pgrep', '-f', 'services.ai_modules.training_subprocess'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                pids = result.stdout.strip().split('\n')
                pids = [p for p in pids if p.strip()]
                if pids:
                    logger.warning(f"[TRAINING] Found {len(pids)} existing training subprocess(es): {pids}")
                    return {
                        "success": False,
                        "error": f"Training already running as OS process (PIDs: {', '.join(pids)}). Kill them first: pkill -9 -f training_subprocess",
                        "status": "running",
                        "pids": pids,
                    }
        except Exception as e:
            logger.warning(f"[TRAINING] OS-level process check failed (non-fatal): {e}")

    if _training_task and not _training_task.done():
        if hasattr(_training_task, '_start_time'):
            elapsed = datetime.now(timezone.utc) - _training_task._start_time
            if elapsed > timedelta(hours=6):
                logger.warning(f"Stale training process detected (running {elapsed}), terminating...")
                _training_task.terminate()
                _training_task = None
            else:
                return {
                    "success": False,
                    "error": f"Training already in progress (running for {int(elapsed.total_seconds())}s)",
                    "status": "running",
                }
        else:
            return {
                "success": False,
                "error": "Training already in progress",
                "status": "running",
            }

    try:
        from services.focus_mode_manager import focus_mode_manager
        from server import db as mongo_db

        # Activate TRAINING focus mode — pauses non-essential services
        try:
            focus_mode_manager.set_mode(
                mode="training",
                context={"phases": request.phases, "bar_sizes": request.bar_sizes},
            )
        except Exception as fm_err:
            logger.warning(f"Focus mode activation failed (non-fatal): {fm_err}")

        # Launch in a completely separate process — zero GIL/import lock interference
        # Pass MongoDB credentials via environment (avoids shell escaping issues with special chars in URLs)
        logger.info("[TRAINING] Launching subprocess...")

        # Write "starting" status to MongoDB BEFORE spawning subprocess
        # so any immediate WS broadcast picks up the correct phase (not stale "idle")
        try:
            await asyncio.to_thread(
                mongo_db["training_pipeline_status"].update_one,
                {"_id": "pipeline"},
                {"$set": {"phase": "starting", "started_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True
            )
        except Exception as db_err:
            logger.warning(f"[TRAINING] Could not pre-set starting status: {db_err}")

        env = os.environ.copy()
        # MONGO_URL and DB_NAME are already in os.environ; subprocess inherits them
        
        cmd = [sys.executable, "-m", "services.ai_modules.training_subprocess"]
        if request.phases:
            cmd.extend(["--phases", ",".join(request.phases)])
        if request.bar_sizes:
            cmd.extend(["--bar-sizes", ",".join(request.bar_sizes)])
        if request.max_symbols:
            cmd.extend(["--max-symbols", str(request.max_symbols)])
        if request.force_retrain:
            cmd.append("--force-retrain")
        if request.resume_max_age_hours != 24.0:
            cmd.extend(["--resume-max-age", str(request.resume_max_age_hours)])
        if request.test_mode:
            cmd.append("--test-mode")

        log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'training_subprocess.log')
        popen_kwargs = dict(
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # /app/backend
            stdout=open(log_path, 'w'),
            stderr=subprocess.STDOUT,  # Merge stderr into stdout log file
            env=env,
        )
        # Lower CPU priority on POSIX systems (Linux/Mac) so browser stays responsive
        if os.name != 'nt':
            popen_kwargs['preexec_fn'] = lambda: os.nice(10)

        proc = subprocess.Popen(cmd, **popen_kwargs)

        # On Windows, lower the subprocess priority after creation
        if os.name == 'nt':
            try:
                import ctypes
                handle = ctypes.windll.kernel32.OpenProcess(0x0200, False, proc.pid)
                if handle:
                    ctypes.windll.kernel32.SetPriorityClass(handle, 0x00004000)  # BELOW_NORMAL_PRIORITY_CLASS
                    ctypes.windll.kernel32.CloseHandle(handle)
                    logger.info(f"[TRAINING] Set subprocess {proc.pid} to BELOW_NORMAL priority")
            except Exception as e:
                logger.warning(f"[TRAINING] Could not lower subprocess priority: {e}")
        
        # Verify subprocess started (give it 2 seconds) — use async sleep to keep event loop alive
        await asyncio.sleep(1.5)
        if proc.poll() is not None:
            # Subprocess already exited — crashed on startup. Read from log file.
            log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'training_subprocess.log')
            log_output = ""
            try:
                with open(log_path, 'r') as f:
                    log_output = f.read()[-2000:]
            except Exception:
                pass
            logger.error(f"[TRAINING] Subprocess crashed immediately! Exit code: {proc.returncode}")
            logger.error(f"[TRAINING] output: {log_output}")
            try:
                focus_mode_manager.reset_to_live(result={"error": "subprocess crashed"})
            except Exception:
                pass
            return {
                "success": False,
                "error": f"Training subprocess crashed on startup: {log_output[-500:] or 'Unknown error'}",
            }
        
        _training_task = _TrainingProcess(proc)
        logger.info(f"[TRAINING] Subprocess running with PID: {proc.pid}")

        # Start a background task to monitor the subprocess and restore focus mode when done
        asyncio.create_task(_monitor_training_process(_training_task))

        phases_list = request.phases or [
            "generic", "setup", "short", "volatility", "exit",
            "sector", "gap_fill", "risk", "regime", "ensemble", "cnn", "validate",
        ]

        return {
            "success": True,
            "message": "Training pipeline started (TRAINING focus mode activated)",
            "focus_mode": "training",
            "phases": phases_list,
            "bar_sizes": request.bar_sizes if request.bar_sizes else "all",
        }

    except Exception as e:
        logger.error(f"Failed to start training: {e}", exc_info=True)
        return {"success": False, "error": f"Failed to start training: {str(e)}"}


@router.get("/status")
async def get_training_status():
    """Get current training pipeline status."""
    global _training_task, _last_result

    try:
        from server import db as mongo_db

        # Check pipeline status from DB (run in thread to avoid blocking event loop)
        status_doc = None
        if mongo_db is not None:
            status_doc = await asyncio.to_thread(
                mongo_db["training_pipeline_status"].find_one,
                {"_id": "pipeline"}, {"_id": 0}
            )

        task_status = "idle"
        subprocess_info = None
        if _training_task:
            if _training_task.done():
                task_status = "completed"
                subprocess_info = {"exit_code": _training_task._proc.returncode}
            else:
                task_status = "running"
                subprocess_info = {"pid": _training_task._proc.pid, "running": True}

        # Auto-reset stale DB status: if no in-memory task is running but DB shows
        # a non-idle phase, a previous run was interrupted. Reset to idle.
        if task_status != "running" and status_doc and mongo_db is not None:
            db_phase = status_doc.get("phase", "idle")
            if db_phase not in ("idle", "completed", "cancelled", "error"):
                logger.info(f"Resetting stale pipeline status (phase was '{db_phase}' but no task running)")
                await asyncio.to_thread(
                    mongo_db["training_pipeline_status"].update_one,
                    {"_id": "pipeline"},
                    {"$set": {"phase": "idle", "current_model": "", "current_phase_progress": 0}},
                )
                status_doc["phase"] = "idle"
                status_doc["current_model"] = ""
                status_doc["current_phase_progress"] = 0

        return {
            "success": True,
            "task_status": task_status,
            "subprocess": subprocess_info,
            "pipeline_status": status_doc,
            "last_result": _last_result,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/stop")
async def stop_training():
    """Cancel the running training pipeline — kills both in-memory task and OS processes."""
    global _training_task

    terminated = False
    if _training_task and not _training_task.done():
        logger.info("[TRAINING] Stop requested — terminating subprocess")
        try:
            _training_task.terminate()
            await asyncio.sleep(2)
            if not _training_task.done():
                logger.warning("[TRAINING] Subprocess didn't terminate gracefully, force killing...")
                _training_task._proc.kill()
        except Exception as e:
            logger.warning(f"[TRAINING] Error during termination: {e}")
        _training_task = None
        terminated = True

    # OS-level kill: catch orphaned training processes that survive server restarts
    os_killed = []
    if os.name != 'nt':
        try:
            result = subprocess.run(
                ['pgrep', '-f', 'services.ai_modules.training_subprocess'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                pids = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]
                for pid in pids:
                    try:
                        os.kill(int(pid), 9)  # SIGKILL
                        os_killed.append(pid)
                        logger.info(f"[TRAINING] Force-killed orphaned training process PID {pid}")
                    except (ProcessLookupError, ValueError):
                        pass
        except Exception as e:
            logger.warning(f"[TRAINING] OS-level kill failed: {e}")

    # Also reset training status in DB to idle
    try:
        from server import db as mongo_db
        if mongo_db is not None:
            await asyncio.to_thread(
                mongo_db["training_pipeline_status"].update_one,
                {"_id": "pipeline"},
                {"$set": {"phase": "idle", "current_model": "", "current_phase_progress": 0}},
            )
            logger.info("[TRAINING] Reset training status to idle")
    except Exception as e:
        logger.warning(f"[TRAINING] Could not reset training status: {e}")

    # Always reset focus mode to LIVE, even if task was lost (e.g., backend restarted)
    try:
        from services.focus_mode_manager import focus_mode_manager
        focus_mode_manager.reset_to_live(result={"stopped": "manual"})
    except Exception:
        pass

    if terminated or os_killed:
        msg = "Training stopped."
        if terminated:
            msg += " In-memory process terminated."
        if os_killed:
            msg += f" Killed {len(os_killed)} orphaned OS process(es): PIDs {', '.join(os_killed)}."
        msg += " Focus mode restored to LIVE."
        return {"success": True, "message": msg, "os_killed_pids": os_killed}

    # Even if no task found, reset focus mode (handles backend restart case)
    return {"success": True, "message": "Focus mode restored to LIVE (training process may have already ended)"}


@router.get("/is-active")
async def is_training_active():
    """
    Lightweight endpoint for external processes (IB Pusher, Collectors) to check
    if training is currently running. Returns a simple boolean.
    
    Used by Windows-side scripts to back off during Spark GPU training.
    """
    active = False
    reason = "idle"
    try:
        from services.focus_mode_manager import focus_mode_manager
        mode = focus_mode_manager.get_mode()
        if mode == "training":
            active = True
            reason = f"focus_mode={mode}"
    except Exception:
        pass

    if not active:
        try:
            from services.training_mode import training_mode_manager
            if training_mode_manager.is_training_active():
                active = True
                reason = "training_mode_manager"
        except Exception:
            pass

    if not active and _training_task and not _training_task.done():
        active = True
        reason = "subprocess_running"

    return {
        "active": active,
        "reason": reason,
    }


@router.get("/models")
async def list_trained_models():
    """List all trained models with their metrics."""
    try:
        from server import db as mongo_db
        if mongo_db is None:
            raise HTTPException(status_code=503, detail="Database not connected")

        models = list(mongo_db["timeseries_models"].find(
            {},
            {"_id": 0, "model_data": 0}  # Exclude heavy binary data
        ).sort("promoted_at", -1))

        return {
            "success": True,
            "count": len(models),
            "models": models,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data-readiness")
async def check_data_readiness():
    """
    Check how much training data is available per bar size.
    Helps decide when to start training.
    """
    try:
        from server import db as mongo_db
        if mongo_db is None:
            raise HTTPException(status_code=503, detail="Database not connected")

        pipeline = [
            {"$group": {
                "_id": "$bar_size",
                "total_bars": {"$sum": 1},
                "unique_symbols": {"$addToSet": "$symbol"},
            }},
            {"$project": {
                "_id": 0,
                "bar_size": "$_id",
                "total_bars": 1,
                "symbol_count": {"$size": "$unique_symbols"},
            }},
            {"$sort": {"total_bars": -1}},
        ]

        results = list(mongo_db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True))

        total_bars = sum(r["total_bars"] for r in results)

        return {
            "success": True,
            "total_bars": total_bars,
            "by_bar_size": results,
            "recommendation": (
                "Ready for training" if total_bars > 1_000_000
                else "Collecting more data recommended"
            ),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/regime-live")
async def get_live_regime():
    """
    Get live market regime classification from SPY, QQQ, IWM daily bars.
    Returns the current regime (bull/bear/range/high_vol) plus per-index metrics.
    """
    try:
        from server import db as mongo_db
        if mongo_db is None:
            raise HTTPException(status_code=503, detail="Database not connected")

        import numpy as np
        from services.ai_modules.regime_conditional_model import classify_regime
        from services.ai_modules.regime_features import compute_single_index_features

        def _load_index(symbol):
            # Use aggregation to get one bar per date, much faster than pulling 3000 raw bars
            pipeline = [
                {"$match": {"symbol": symbol, "bar_size": "1 day"}},
                {"$addFields": {"date_key": {"$substr": [{"$toString": "$date"}, 0, 10]}}},
                {"$sort": {"date": -1}},
                {"$group": {
                    "_id": "$date_key",
                    "close": {"$first": "$close"},
                    "high": {"$first": "$high"},
                    "low": {"$first": "$low"},
                    "date": {"$first": "$date_key"},
                }},
                {"$sort": {"_id": -1}},
                {"$limit": 30},
            ]
            try:
                real = list(mongo_db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True))
            except Exception:
                return None, None, None, None

            if len(real) < 25:
                return None, None, None, None
            return (
                np.array([b["close"] for b in real], dtype=float),
                np.array([b["high"] for b in real], dtype=float),
                np.array([b["low"] for b in real], dtype=float),
                real[0].get("date", ""),
            )

        # Run blocking MongoDB aggregations in thread pool to avoid freezing the event loop
        spy_result, qqq_result, iwm_result = await asyncio.gather(
            asyncio.to_thread(_load_index, "SPY"),
            asyncio.to_thread(_load_index, "QQQ"),
            asyncio.to_thread(_load_index, "IWM"),
        )
        spy_c, spy_h, spy_l, spy_date = spy_result
        qqq_c, qqq_h, qqq_l, qqq_date = qqq_result
        iwm_c, iwm_h, iwm_l, iwm_date = iwm_result

        regime = "unknown"
        if spy_c is not None:
            regime = classify_regime(spy_c, spy_h, spy_l)

        # Per-index features
        indexes = {}
        for name, c, h, lo, dt in [
            ("SPY", spy_c, spy_h, spy_l, spy_date),
            ("QQQ", qqq_c, qqq_h, qqq_l, qqq_date),
            ("IWM", iwm_c, iwm_h, iwm_l, iwm_date),
        ]:
            if c is not None:
                feats = compute_single_index_features(f"regime_{name.lower()}", c, h, lo)
                indexes[name] = {
                    "price": float(c[0]),
                    "date": dt,
                    "trend": feats.get(f"regime_{name.lower()}_trend", 0),
                    "rsi": feats.get(f"regime_{name.lower()}_rsi", 0),
                    "momentum": feats.get(f"regime_{name.lower()}_momentum", 0),
                    "volatility": feats.get(f"regime_{name.lower()}_volatility", 0),
                    "vol_expansion": feats.get(f"regime_{name.lower()}_vol_expansion", 0),
                    "breadth": feats.get(f"regime_{name.lower()}_breadth", 0),
                }
            else:
                indexes[name] = {"price": 0, "date": "", "trend": 0, "rsi": 0,
                                 "momentum": 0, "volatility": 0, "vol_expansion": 0, "breadth": 0}

        # Cross-correlations
        cross = {}
        if spy_c is not None and qqq_c is not None and iwm_c is not None:
            from services.ai_modules.regime_features import compute_cross_features
            cross_feats = compute_cross_features(spy_c, qqq_c, iwm_c)
            cross = {
                "spy_qqq_corr": cross_feats.get("regime_corr_spy_qqq", 0),
                "spy_iwm_corr": cross_feats.get("regime_corr_spy_iwm", 0),
                "qqq_iwm_corr": cross_feats.get("regime_corr_qqq_iwm", 0),
                "rotation_qqq_spy": cross_feats.get("regime_rotation_qqq_spy", 0),
                "rotation_iwm_spy": cross_feats.get("regime_rotation_iwm_spy", 0),
                "rotation_qqq_iwm": cross_feats.get("regime_rotation_qqq_iwm", 0),
            }

        return {
            "success": True,
            "regime": regime,
            "indexes": indexes,
            "cross": cross,
        }

    except Exception as e:
        logger.error(f"Live regime error: {e}")
        return {"success": False, "error": str(e)}


@router.get("/model-inventory")
async def get_model_inventory():
    """
    Get complete inventory of all model definitions with their training status.
    Shows which models are defined, which are trained, and their accuracy.
    """
    try:
        from server import db as mongo_db

        # Get trained models from DB (run in thread to avoid blocking event loop)
        trained_models = {}
        if mongo_db is not None:
            def _fetch_trained_models():
                models = {}
                for doc in mongo_db["timeseries_models"].find({}, {"_id": 0, "model_data": 0}):
                    model_name = doc.get("name", doc.get("model_name", ""))
                    if model_name:
                        metrics = doc.get("metrics", {})
                        models[model_name] = {
                            "accuracy": metrics.get("accuracy", doc.get("accuracy", 0)),
                            "training_samples": metrics.get("training_samples", doc.get("training_samples", 0)),
                            "promoted_at": doc.get("saved_at", doc.get("promoted_at", "")),
                        }
                return models
            trained_models = await asyncio.to_thread(_fetch_trained_models)

        from services.ai_modules.volatility_model import VOL_MODEL_CONFIGS
        from services.ai_modules.exit_timing_model import EXIT_MODEL_CONFIGS
        from services.ai_modules.sector_relative_model import SECTOR_MODEL_CONFIGS
        from services.ai_modules.gap_fill_model import GAP_MODEL_CONFIGS
        from services.ai_modules.risk_of_ruin_model import RISK_MODEL_CONFIGS
        from services.ai_modules.ensemble_model import ENSEMBLE_MODEL_CONFIGS

        categories = {
            "setup_specific": {
                "label": "Setup-Specific",
                "description": "Per setup type trade signals (Long + Short)",
                "group": "signal",
                "models": [],
            },
            "ensemble": {
                "label": "Ensemble Meta-Learner",
                "description": "Stacks multi-timeframe signals into final GO/NO-GO",
                "group": "signal",
                "models": [],
            },
            "generic_directional": {
                "label": "Generic Directional",
                "description": "Predicts UP/DOWN per timeframe",
                "group": "support",
                "models": [],
            },
            "volatility": {
                "label": "Volatility Prediction",
                "description": "Predicts high/low vol for position sizing",
                "group": "support",
                "models": [],
            },
            "exit_timing": {
                "label": "Exit Timing",
                "description": "Predicts optimal holding period",
                "group": "support",
                "models": [],
            },
            "sector_relative": {
                "label": "Sector-Relative",
                "description": "Outperform/underperform vs sector ETF",
                "group": "support",
                "models": [],
            },
            "gap_fill": {
                "label": "Gap Fill Probability",
                "description": "Gap fill vs continuation prediction",
                "group": "support",
                "models": [],
            },
            "risk_of_ruin": {
                "label": "Risk-of-Ruin",
                "description": "Stop-loss hit probability",
                "group": "support",
                "models": [],
            },
            "regime_conditional": {
                "label": "Regime-Conditional",
                "description": "Per-regime model variants (bull/bear/range/high_vol)",
                "group": "support",
                "models": [],
            },
            "deep_learning": {
                "label": "Deep Learning",
                "description": "Neural network models (VAE regime, TFT cross-timeframe, CNN-LSTM patterns)",
                "group": "support",
                "models": [],
            },
            "finbert": {
                "label": "FinBERT Sentiment",
                "description": "Pre-trained news sentiment scoring (bullish/bearish/neutral)",
                "group": "support",
                "models": [],
            },
        }

        # Generic directional — use the ACTUAL model names from timeseries_service.py config
        DIRECTIONAL_MODEL_NAMES = {
            "1 min": "direction_predictor_1min",
            "5 mins": "direction_predictor_5min",
            "15 mins": "direction_predictor_15min",
            "30 mins": "direction_predictor_30min",
            "1 hour": "direction_predictor_1hour",
            "1 day": "direction_predictor_daily",
            "1 week": "direction_predictor_weekly",
        }
        for bs, name in DIRECTIONAL_MODEL_NAMES.items():
            categories["generic_directional"]["models"].append({
                "name": name, "bar_size": bs,
                "trained": name in trained_models,
                **(trained_models.get(name, {})),
            })

        # Setup-specific (from existing config)
        from services.ai_modules.setup_training_config import SETUP_TRAINING_PROFILES, get_setup_profiles, get_model_name
        for st in SETUP_TRAINING_PROFILES.keys():
            profiles = get_setup_profiles(st)
            for profile in profiles:
                bs = profile.get("bar_size", "1 day")
                name = get_model_name(st, bs)
                categories["setup_specific"]["models"].append({
                    "name": name, "setup_type": st, "bar_size": bs,
                    "trained": name in trained_models,
                    **(trained_models.get(name, {})),
                })

        # New model categories
        for config_map, category_key in [
            (VOL_MODEL_CONFIGS, "volatility"),
            (EXIT_MODEL_CONFIGS, "exit_timing"),
            (SECTOR_MODEL_CONFIGS, "sector_relative"),
            (GAP_MODEL_CONFIGS, "gap_fill"),
            (RISK_MODEL_CONFIGS, "risk_of_ruin"),
            (ENSEMBLE_MODEL_CONFIGS, "ensemble"),
        ]:
            for key, cfg in config_map.items():
                name = cfg["model_name"]
                categories[category_key]["models"].append({
                    "name": name, "config_key": key,
                    "trained": name in trained_models,
                    **(trained_models.get(name, {})),
                })

        # Regime-conditional model variants (generic directional x 4 regimes)
        from services.ai_modules.regime_conditional_model import ALL_REGIMES, get_regime_model_name
        for bs, base_name in DIRECTIONAL_MODEL_NAMES.items():
            for regime in ALL_REGIMES:
                name = get_regime_model_name(base_name, regime)
                categories["regime_conditional"]["models"].append({
                    "name": name, "bar_size": bs, "regime": regime,
                    "trained": name in trained_models,
                    **(trained_models.get(name, {})),
                })

        # Deep Learning models (Phase 11)
        DL_MODELS = [
            {"name": "vae_regime_detector", "description": "VAE market regime labeling (5 regimes)"},
            {"name": "temporal_fusion_transformer", "description": "TFT cross-timeframe attention"},
            {"name": "cnn_lstm_sequential", "description": "CNN-LSTM temporal pattern recognition"},
        ]
        for dl in DL_MODELS:
            name = dl["name"]
            # Check dl_models collection as well as timeseries_models
            dl_trained = name in trained_models
            dl_info = trained_models.get(name, {})
            if not dl_trained and mongo_db is not None:
                try:
                    dl_doc = mongo_db["dl_models"].find_one({"name": name}, {"_id": 0, "model_data": 0})
                    if dl_doc:
                        dl_trained = True
                        metrics = dl_doc.get("metrics", {})
                        dl_info = {
                            "accuracy": metrics.get("accuracy", dl_doc.get("accuracy", 0)),
                            "training_samples": metrics.get("training_samples", 0),
                            "promoted_at": dl_doc.get("saved_at", ""),
                        }
                except Exception:
                    pass
            categories["deep_learning"]["models"].append({
                "name": name, "description": dl["description"],
                "trained": dl_trained,
                **dl_info,
            })

        # FinBERT Sentiment (Phase 12) — check if sentiment data exists
        finbert_trained = False
        finbert_info = {}
        if mongo_db is not None:
            try:
                sent_count = mongo_db["finbert_sentiment"].count_documents({})
                if sent_count > 0:
                    finbert_trained = True
                    latest = mongo_db["finbert_sentiment"].find_one(
                        {}, {"_id": 0, "analyzed_at": 1}, sort=[("analyzed_at", -1)]
                    )
                    finbert_info = {
                        "articles_scored": sent_count,
                        "promoted_at": str(latest.get("analyzed_at", "")) if latest else "",
                    }
            except Exception:
                pass
        categories["finbert"]["models"].append({
            "name": "finbert_news_sentiment",
            "description": "Scores news articles via ProsusAI/finbert for market sentiment",
            "trained": finbert_trained,
            **finbert_info,
        })

        # Summary stats
        total_defined = sum(len(c["models"]) for c in categories.values())
        total_trained = sum(
            sum(1 for m in c["models"] if m.get("trained"))
            for c in categories.values()
        )

        # Validation status for signal generators (setup_specific + ensemble)
        validation_summary = {"setup_specific": {}, "ensemble": {}}
        try:
            if mongo_db is not None:
                val_col = mongo_db["model_validations"]
            # Get latest validation per setup_type
            pipeline = [
                {"$sort": {"validated_at": -1}},
                {"$group": {
                    "_id": "$setup_type",
                    "status": {"$first": "$status"},
                    "phases_passed": {"$first": "$phases_passed"},
                    "validated_at": {"$first": "$validated_at"},
                    "training_accuracy": {"$first": "$training_accuracy"},
                }},
            ]
            for doc in val_col.aggregate(pipeline):
                setup_type = doc["_id"]
                validation_summary["setup_specific"][setup_type] = {
                    "status": doc.get("status", "unknown"),
                    "phases_passed": doc.get("phases_passed", 0),
                    "validated_at": doc.get("validated_at"),
                    "training_accuracy": doc.get("training_accuracy", 0),
                }

            # Count promoted/rejected
            promoted = sum(1 for v in validation_summary["setup_specific"].values() if v["status"] == "promoted")
            rejected = sum(1 for v in validation_summary["setup_specific"].values() if v["status"] == "rejected")
            total_validated = len(validation_summary["setup_specific"])

            # Attach to setup_specific category
            categories["setup_specific"]["validation"] = {
                "total_validated": total_validated,
                "promoted": promoted,
                "rejected": rejected,
                "per_setup": validation_summary["setup_specific"],
            }
        except Exception as e:
            logger.debug(f"Validation summary fetch error: {e}")

        return {
            "success": True,
            "total_defined": total_defined,
            "total_trained": total_trained,
            "categories": categories,
        }

    except Exception as e:
        logger.error(f"Model inventory error: {e}")
        return {"success": False, "error": str(e)}



# ============ CONFIDENCE GATE ENDPOINTS ============

@router.get("/confidence-gate/summary")
async def get_confidence_gate_summary():
    """
    Get SentCom's current trading mode, today's decision stats, and recent streak.
    Used by the NIA SentCom Intelligence panel header.
    """
    try:
        from services.ai_modules.confidence_gate import get_confidence_gate
        gate = get_confidence_gate()
        return {"success": True, **gate.get_summary()}
    except Exception as e:
        logger.error(f"Confidence gate summary error: {e}")
        return {"success": False, "error": str(e)}


@router.get("/confidence-gate/decisions")
async def get_confidence_gate_decisions(limit: int = 30):
    """
    Get recent confidence gate decisions for the NIA decision log.
    Shows what SentCom evaluated, what it decided, and why.
    """
    try:
        from services.ai_modules.confidence_gate import get_confidence_gate
        gate = get_confidence_gate()
        decisions = gate.get_decision_log(limit=limit)
        # Strip heavy fields for API response
        clean = []
        for d in decisions:
            clean.append({
                "decision": d.get("decision"),
                "confidence_score": d.get("confidence_score"),
                "symbol": d.get("symbol"),
                "setup_type": d.get("setup_type"),
                "direction": d.get("direction"),
                "regime_state": d.get("regime_state"),
                "ai_regime": d.get("ai_regime"),
                "trading_mode": d.get("trading_mode"),
                "position_multiplier": d.get("position_multiplier"),
                "reasoning": d.get("reasoning"),
                "timestamp": d.get("timestamp"),
            })
        return {"success": True, "decisions": clean, "count": len(clean)}
    except Exception as e:
        logger.error(f"Confidence gate decisions error: {e}")
        return {"success": False, "error": str(e)}


@router.get("/confidence-gate/stats")
async def get_confidence_gate_stats():
    """
    Get lifetime and daily statistics for the confidence gate.
    """
    try:
        from services.ai_modules.confidence_gate import get_confidence_gate
        gate = get_confidence_gate()
        return {"success": True, **gate.get_stats()}
    except Exception as e:
        logger.error(f"Confidence gate stats error: {e}")
        return {"success": False, "error": str(e)}


@router.post("/confidence-gate/evaluate")
async def evaluate_trade_confidence(symbol: str, setup_type: str, direction: str = "long", quality_score: int = 70):
    """
    Manually evaluate a symbol+setup through the confidence gate.
    Useful for testing or manual pre-trade checks.
    """
    try:
        from server import db as mongo_db
        from services.ai_modules.confidence_gate import get_confidence_gate
        gate = get_confidence_gate()
        if mongo_db is not None and gate._db is None:
            gate.set_db(mongo_db)

        # Try to get regime engine
        regime_engine = None
        try:
            from server import market_regime_engine
            regime_engine = market_regime_engine
        except ImportError:
            pass

        result = await gate.evaluate(
            symbol=symbol,
            setup_type=setup_type,
            direction=direction,
            quality_score=quality_score,
            regime_engine=regime_engine,
        )
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Confidence gate evaluate error: {e}")
        return {"success": False, "error": str(e)}



@router.get("/confidence-gate/accuracy")
async def get_confidence_gate_accuracy(limit: int = 100):
    """
    GAP 5: Get decision accuracy — how often did GO/REDUCE/SKIP lead to wins?
    Returns per-decision win rate, total P&L, and avg confidence.
    Used by the upcoming Confidence Gate Tuner (P2).
    """
    try:
        from services.ai_modules.confidence_gate import get_confidence_gate
        gate = get_confidence_gate()
        accuracy = gate.get_decision_accuracy(limit=limit)
        return {"success": True, **accuracy}
    except Exception as e:
        logger.error(f"Confidence gate accuracy error: {e}")
        return {"success": False, "error": str(e)}



# ═══════════════════════════════════════════════════════════════
# CNN Chart Pattern Training Endpoints
# ═══════════════════════════════════════════════════════════════

@router.post("/cnn/start")
async def start_cnn_training(
    setup_type: str = "ALL",
    bar_size: str = None,
    max_symbols: int = None,
):
    """
    Queue a CNN chart pattern training job.
    
    Args:
        setup_type: "ALL" or specific setup (e.g., "BREAKOUT", "SCALP")
        bar_size: Optional specific bar size (e.g., "1 day", "5 mins")
        max_symbols: Limit symbols for faster training (None = all)
    """
    try:
        from services.job_queue_manager import job_queue_manager, JobType
        
        params = {"setup_type": setup_type.upper()}
        if bar_size:
            params["bar_size"] = bar_size
        if max_symbols:
            params["max_symbols"] = max_symbols
        
        result = await job_queue_manager.create_job(
            job_type=JobType.CNN_TRAINING.value,
            params=params,
            metadata={"description": f"CNN training: {setup_type}" + (f"/{bar_size}" if bar_size else " (all profiles)")}
        )
        
        if result.get("success"):
            job = result.get("job", {})
            return {
                "success": True,
                "job_id": job.get("job_id"),
                "message": f"CNN training job queued for {setup_type}",
                "params": params,
            }
        else:
            return {"success": False, "error": result.get("error", "Failed to create job")}
    except Exception as e:
        logger.error(f"CNN training start error: {e}")
        return {"success": False, "error": str(e)}


@router.get("/cnn/models")
def get_cnn_models():
    """List all trained CNN models with their metrics."""
    try:
        from server import db as mongo_db
        from services.ai_modules.chart_pattern_cnn import list_cnn_models
        if mongo_db is None:
            return {"success": False, "error": "Database not available"}
        models = list_cnn_models(mongo_db)
        return {"success": True, "models": models, "count": len(models)}
    except Exception as e:
        logger.error(f"CNN models list error: {e}")
        return {"success": False, "error": str(e)}


@router.get("/cnn/predict/{symbol}")
def cnn_predict(symbol: str, bar_size: str = "1 day", setup_type: str = "BREAKOUT"):
    """
    Run CNN inference on a symbol's current chart.
    
    Generates a chart image from the latest bars and runs the CNN model.
    Returns pattern classification and win probability.
    """
    try:
        from server import db as mongo_db
        from services.ai_modules.chart_pattern_cnn import (
            load_model_from_db, predict_from_image, CNN_WINDOW_SIZES, DEFAULT_WINDOW_SIZE
        )
        from services.ai_modules.chart_image_generator import generate_live_chart_tensor

        if mongo_db is None:
            return {"success": False, "error": "Database not available"}
        
        # Load the trained model
        model, metadata = load_model_from_db(mongo_db, setup_type, bar_size)
        if model is None:
            return {
                "success": False,
                "error": f"No CNN model found for {setup_type}/{bar_size}. Train one first."
            }
        
        # Generate chart tensor from latest bars
        window_size = CNN_WINDOW_SIZES.get(setup_type, DEFAULT_WINDOW_SIZE)
        tensor, chart_meta = generate_live_chart_tensor(mongo_db, symbol, bar_size, window_size)
        
        if tensor is None:
            return {
                "success": False,
                "error": f"Insufficient bar data for {symbol}/{bar_size}"
            }
        
        # Run prediction
        prediction = predict_from_image(model, tensor)
        prediction["symbol"] = symbol
        prediction["bar_size"] = bar_size
        prediction["setup_type"] = setup_type
        prediction["model_accuracy"] = metadata.get("metrics", {}).get("accuracy", 0)
        prediction["chart_meta"] = chart_meta
        
        return {"success": True, "prediction": prediction}
        
    except Exception as e:
        logger.error(f"CNN prediction error for {symbol}: {e}")
        return {"success": False, "error": str(e)}


@router.get("/gpu-status")
def get_gpu_status():
    """Get GPU information and CUDA availability."""
    try:
        from services.ai_modules.chart_pattern_cnn import get_gpu_info
        info = get_gpu_info()
        
        # Try to get current GPU memory usage
        try:
            import torch
            if torch.cuda.is_available():
                info["vram_used_mb"] = torch.cuda.memory_allocated() // (1024 * 1024)
                info["vram_reserved_mb"] = torch.cuda.memory_reserved() // (1024 * 1024)
        except Exception:
            pass
        
        return {"success": True, "gpu": info}
    except Exception as e:
        return {"success": True, "gpu": {"gpu": "Unknown", "cuda": False, "error": str(e)}}
