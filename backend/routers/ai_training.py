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
import time as _time
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-training", tags=["AI Training"])

# Simple response cache for expensive endpoints
_endpoint_cache = {}
_CACHE_TTL = 30  # seconds


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
    skip_preflight: bool = False  # Escape hatch: bypass shape-drift check (not recommended)


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

        # ── Pre-flight shape validation ──────────────────────────────────
        # Runs the ~5s synthetic-bar validator to catch feature-shape drift
        # BEFORE we spawn a multi-hour subprocess. This is the bug class
        # that killed the 2026-04-21 run 12 min into Phase 1 with a
        # "expected 57, got 52" mismatch. Bypass only via skip_preflight.
        if not request.skip_preflight:
            try:
                from services.ai_modules.preflight_validator import preflight_validate_shapes
                pf_phases = request.phases if request.phases else [
                    "setup", "short", "volatility", "exit", "risk",
                    "sector", "gap_fill", "regime", "ensemble",
                ]
                pf_report = await asyncio.to_thread(
                    preflight_validate_shapes, pf_phases, request.bar_sizes
                )
                if not pf_report.get("ok", False):
                    logger.error(
                        f"[TRAINING] Preflight FAILED — refusing to spawn training subprocess. "
                        f"{len(pf_report.get('failures', []))} mismatches."
                    )
                    return {
                        "success": False,
                        "error": "Pre-flight shape validation failed. Fix the feature/name mismatches before retrying — running would crash mid-training.",
                        "status": "preflight_failed",
                        "preflight": pf_report,
                    }
                logger.info(
                    f"[TRAINING] Preflight passed ({pf_report.get('duration_s')}s, "
                    f"phases={pf_report.get('checked_phases')})"
                )
            except Exception as pf_err:
                logger.warning(f"[TRAINING] Preflight check errored (non-fatal, proceeding): {pf_err}")

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
def is_training_active():
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
def list_trained_models():
    """List ALL trained models across all collections (XGBoost, CNN, DL).
    Sync handler — runs in thread pool, doesn't block event loop."""
    try:
        from server import db as mongo_db
        if mongo_db is None:
            raise HTTPException(status_code=503, detail="Database not connected")

        all_models = []

        # XGBoost models (timeseries_models)
        xgb_models = list(mongo_db["timeseries_models"].find(
            {},
            {"_id": 0, "model_data": 0, "xgboost_json_zlib": 0}
        ).sort("promoted_at", -1))
        for m in xgb_models:
            m["model_type"] = m.get("model_type", "xgboost")
            m["source"] = "timeseries_models"
        all_models.extend(xgb_models)

        # CNN models
        cnn_models = list(mongo_db["cnn_models"].find(
            {},
            {"_id": 0, "gridfs_file_id": 0}
        ).sort("trained_at", -1))
        for m in cnn_models:
            m["model_type"] = "cnn_resnet18"
            m["source"] = "cnn_models"
        all_models.extend(cnn_models)

        # Deep Learning models (VAE, TFT, CNN-LSTM)
        dl_models = list(mongo_db["dl_models"].find(
            {},
            {"_id": 0, "model_data": 0}
        ).sort("trained_at", -1))
        for m in dl_models:
            m["source"] = "dl_models"
        all_models.extend(dl_models)

        return {
            "success": True,
            "count": len(all_models),
            "breakdown": {
                "xgboost": len(xgb_models),
                "cnn": len(cnn_models),
                "deep_learning": len(dl_models),
            },
            "models": all_models,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data-readiness")
async def check_data_readiness():
    """
    Check how much training data is available per bar size.

    Uses DISTINCT_SCAN + estimated_document_count() instead of a full
    $group over the 178M-row `ib_historical_data` collection. Previously
    this was a sync `def` running a `$group` aggregation that blocked
    the FastAPI event loop and timed out the UI. Now returns in seconds.

    Also cross-references `BAR_SIZE_CONFIGS` from training_pipeline so each
    bar size gets a clear "ready/insufficient" verdict based on the
    training pipeline's own thresholds.
    """
    try:
        from server import db as mongo_db
        if mongo_db is None:
            raise HTTPException(status_code=503, detail="Database not connected")

        # Cache: readiness doesn't change on a minute-to-minute basis.
        cache_key = "data_readiness"
        now = _time.time()
        cached = _endpoint_cache.get(cache_key)
        if cached and now - cached["at"] < _CACHE_TTL:
            return cached["data"]

        def _compute():
            from services.ai_modules.training_pipeline import BAR_SIZE_CONFIGS

            data_col = mongo_db["ib_historical_data"]
            total_bars = data_col.estimated_document_count()

            results = []
            total_ready_syms = 0
            for bar_size, cfg in BAR_SIZE_CONFIGS.items():
                min_bars = cfg.get("min_bars_per_symbol", 100)
                try:
                    syms = data_col.distinct(
                        "symbol", {"bar_size": bar_size}, maxTimeMS=15000
                    )
                except Exception as e:
                    logger.warning(f"[data-readiness] distinct failed for {bar_size}: {e}")
                    syms = []

                # We purposefully don't re-count bars per symbol here (that's
                # what the training pipeline does against `symbol_adv_cache`
                # in `get_available_symbols`). This endpoint just answers
                # "is there ANY data for this bar_size?" — fast & cheap.
                symbol_count = len(syms)
                target_symbols = cfg.get("max_symbols", 0)
                ready = symbol_count >= min(100, max(1, target_symbols // 10))
                if ready:
                    total_ready_syms += symbol_count

                results.append({
                    "bar_size": bar_size,
                    "symbol_count": symbol_count,
                    "min_bars_per_symbol": min_bars,
                    "target_symbols": target_symbols,
                    "ready": ready,
                })

            ready_count = sum(1 for r in results if r["ready"])
            all_ready = ready_count == len(results)
            any_ready = ready_count > 0

            return {
                "success": True,
                "total_bars": total_bars,
                "by_bar_size": sorted(results, key=lambda r: -r["symbol_count"]),
                "bar_sizes_ready": ready_count,
                "bar_sizes_total": len(results),
                "all_bar_sizes_ready": all_ready,
                "recommendation": (
                    "Ready for full training" if all_ready
                    else "Ready for partial training" if any_ready
                    else "Insufficient data — run Collect Data first"
                ),
            }

        data = await asyncio.to_thread(_compute)
        _endpoint_cache[cache_key] = {"at": now, "data": data}
        return data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[data-readiness] error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/preflight")
async def run_preflight(
    phases: Optional[str] = None,
    bar_sizes: Optional[str] = None,
):
    """
    Run the pre-flight shape validator against all training phases.

    This is the <5-second check that catches shape-drift bugs (like the
    2026-04-21 Phase-2 crash where a 1-line name-list mismatch would
    kill a 44-hour run 12 minutes in). Uses synthetic OHLCV bars so it
    has NO database dependency and runs safely even during heavy data
    collection.

    Query params:
        phases: comma-separated (e.g., "setup,short,volatility,exit,risk,sector,gap_fill,regime,ensemble").
                Defaults to ALL phases.
        bar_sizes: comma-separated (e.g., "1 min,5 mins,1 day"). Defaults to the
                   full set used by the risk phase.

    Returns:
        {
          "success": true, "ok": bool, "checked_phases": [...],
          "failures": [...], "duration_s": float, "flags": {...},
          "ran_at": "..."
        }
    """
    import asyncio as _aio
    phases_list = [p.strip() for p in phases.split(",") if p.strip()] if phases else [
        "setup", "short", "volatility", "exit", "risk",
        "sector", "gap_fill", "regime", "ensemble",
    ]
    bar_sizes_list = [b.strip() for b in bar_sizes.split(",") if b.strip()] if bar_sizes else None

    def _run():
        from services.ai_modules.preflight_validator import preflight_validate_shapes
        return preflight_validate_shapes(phases_list, bar_sizes_list)

    try:
        report = await _aio.to_thread(_run)
        return {
            "success": True,
            "ok": bool(report.get("ok", False)),
            "checked_phases": report.get("checked_phases", []),
            "failures": report.get("failures", []),
            "duration_s": report.get("duration_s"),
            "flags": report.get("flags", {}),
            "ran_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"[preflight] error: {e}", exc_info=True)
        return {
            "success": False,
            "ok": False,
            "error": str(e),
            "checked_phases": [],
            "failures": [],
            "ran_at": datetime.now(timezone.utc).isoformat(),
        }



@router.get("/triple-barrier-configs")
def get_triple_barrier_configs():
    """
    Return all triple-barrier sweep configs (per setup_type × bar_size × trade_side).
    UI displays these as badges on setup profiles so the user can see which PT/SL
    multiples are active and when they were chosen.
    """
    try:
        from server import db as mongo_db
        if mongo_db is None:
            return {"success": False, "configs": [], "error": "DB not available"}
        from services.ai_modules.triple_barrier_config import list_all_configs
        return {"success": True, "configs": list_all_configs(mongo_db)}
    except Exception as e:
        return {"success": False, "configs": [], "error": str(e)}



@router.get("/scorecard/{model_name}")
def get_model_scorecard(model_name: str):
    """Return the stored ModelScorecard for a given model (from timeseries_models.scorecard)."""
    try:
        from server import db as mongo_db
        if mongo_db is None:
            return {"success": False, "error": "DB not available"}
        doc = mongo_db["timeseries_models"].find_one(
            {"name": model_name},
            {"_id": 0, "name": 1, "version": 1, "scorecard": 1, "num_classes": 1, "label_scheme": 1, "metrics": 1}
        )
        if not doc:
            return {"success": False, "error": "Model not found"}
        return {"success": True, **doc}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/scorecards")
def list_scorecards(setup_type: str = None, bar_size: str = None, min_grade: str = None):
    """Return all model scorecards, optionally filtered. Used by NIA summary dashboard."""
    try:
        from server import db as mongo_db
        if mongo_db is None:
            return {"success": False, "scorecards": []}
        q = {"scorecard": {"$exists": True, "$ne": {}}}
        cursor = mongo_db["timeseries_models"].find(
            q,
            {"_id": 0, "name": 1, "version": 1, "scorecard": 1, "label_scheme": 1}
        ).limit(500)
        out = []
        grade_order = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
        for d in cursor:
            sc = d.get("scorecard") or {}
            if setup_type and sc.get("setup_type", "").upper() != setup_type.upper():
                continue
            if bar_size and sc.get("bar_size") != bar_size:
                continue
            if min_grade and grade_order.get(sc.get("composite_grade", "F"), 0) < grade_order.get(min_grade, 0):
                continue
            out.append({
                "model_name": d.get("name"),
                "version": d.get("version"),
                "scorecard": sc,
            })
        # Sort: A first, then by composite_score desc
        out.sort(key=lambda x: (-grade_order.get(x["scorecard"].get("composite_grade", "F"), 0),
                                -x["scorecard"].get("composite_score", 0)))
        return {"success": True, "count": len(out), "scorecards": out}
    except Exception as e:
        return {"success": False, "scorecards": [], "error": str(e)}
@router.get("/model-load-diagnostic")
def model_load_diagnostic():
    """
    Cross-check `timeseries_models` (trained/persisted) vs `_setup_models`
    (reachable at runtime) and report any mismatch.

    This is the safety net that would have caught the 2026-04-24 latent bug
    (17 trained models in DB, 0 loaded in memory, every predict_for_setup
    falling through to the general model) at the first startup after the
    XGBoost migration instead of going unnoticed for weeks.

    Returns:
      trained_in_db_count / loaded_count / missing_count — the summary
      missing_models — trained but not reachable (the red flag)
      by_setup — per-(setup_type, bar_size) detail row
    """
    from services.ai_modules.timeseries_service import get_timeseries_ai
    ts = get_timeseries_ai()
    try:
        report = ts.diagnose_model_load_consistency()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Diagnostic failed: {e}")
    return {"success": True, "report": report}


@router.get("/setup-resolver-trace")
def setup_resolver_trace(setup: Optional[str] = None, batch: Optional[str] = None):
    """
    Diagnostic: trace how a scanner-emitted setup_type routes to a trained model.

    Two modes:
      • `?setup=rubber_band_scalp_short` — single trace
      • `?batch=short_scalp,vwap_reclaim_short,halfback_reversal_short` — comma-separated list

    For each input, returns:
      • input:            raw setup_type as sent
      • normalized:       uppercase version
      • resolved_key:     the key the resolver picks
      • resolved_loaded:  whether that key has a loaded model in `_setup_models`
      • match_step:       which priority branch fired (exact / legacy / short_family / long_base / fallback)
      • will_use_general: True when no setup model will match → general direction_predictor is used

    Purpose: makes coverage gaps obvious. If scanner emits `my_new_setup_short`
    and no SHORT_* family contains `MY_NEW_SETUP`, you'll see `will_use_general=true`
    and know to either add a training profile or map the alias.
    """
    from services.ai_modules.timeseries_service import get_timeseries_ai, TimeSeriesAIService

    ts = get_timeseries_ai()
    available = set(ts._setup_models.keys()) if hasattr(ts, "_setup_models") else set()
    # Keys are a mix of str and (str, bar_size) tuples — we only care about the
    # string keys for resolver comparison (those are the canonical model-name lookups)
    available_str_keys = {k for k in available if isinstance(k, str)}

    def _trace_one(raw: str):
        if not raw:
            return {"input": raw, "error": "empty setup"}
        normalized = raw.upper()
        resolved = TimeSeriesAIService._resolve_setup_model_key(raw, available_str_keys)

        # Figure out which branch fired — cheap static inspection
        match_step = "fallback"
        if resolved == normalized and normalized in available_str_keys:
            match_step = "exact"
        elif normalized in ("VWAP_BOUNCE", "VWAP_FADE") and resolved == "VWAP":
            match_step = "legacy_vwap_alias"
        elif normalized.endswith("_SHORT") and resolved.startswith("SHORT_"):
            match_step = "short_family"
        elif normalized.endswith("_LONG") and resolved == normalized[:-5]:
            match_step = "long_base_strip"
        elif resolved != normalized and resolved in available_str_keys:
            match_step = "family_substring"

        return {
            "input": raw,
            "normalized": normalized,
            "resolved_key": resolved,
            "resolved_loaded": resolved in available_str_keys,
            "match_step": match_step,
            "will_use_general": resolved not in available_str_keys,
        }

    if batch:
        items = [s.strip() for s in batch.split(",") if s.strip()]
        traces = [_trace_one(s) for s in items]
        coverage = sum(1 for t in traces if t.get("resolved_loaded")) / max(1, len(traces))
        return {
            "success": True,
            "count": len(traces),
            "coverage_rate": round(coverage, 4),
            "loaded_models_count": len(available_str_keys),
            "traces": traces,
        }

    if setup:
        return {
            "success": True,
            "loaded_models_count": len(available_str_keys),
            "trace": _trace_one(setup),
        }

    raise HTTPException(
        status_code=400,
        detail="Provide either ?setup=... or ?batch=...,..."
    )


@router.get("/trial-stats/{setup_type}/{bar_size}")
def get_trial_stats(setup_type: str, bar_size: str, trade_side: str = "long"):
    """Return trial registry stats for a bucket (used by NIA sidebar)."""
    try:
        from server import db as mongo_db
        if mongo_db is None:
            return {"success": False}
        from services.ai_modules.trial_registry import get_trial_statistics, list_recent_trials
        stats = get_trial_statistics(mongo_db, setup_type, bar_size, trade_side)
        recent = list_recent_trials(mongo_db, setup_type, bar_size, limit=20)
        return {"success": True, "stats": stats, "recent_trials": recent}
    except Exception as e:
        return {"success": False, "error": str(e)}



@router.get("/regime-live")
def get_live_regime():
    """
    Get live market regime classification from SPY, QQQ, IWM daily bars.
    Returns the current regime (bull/bear/range/high_vol) plus per-index metrics.
    Cached for 30s to avoid redundant heavy DB aggregations.
    """
    cache_key = "regime_live"
    cached = _endpoint_cache.get(cache_key)
    if cached and (_time.time() - cached["ts"]) < _CACHE_TTL:
        return cached["data"]
    
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

        # Run MongoDB aggregations directly (sync handler runs in thread pool)
        spy_result = _load_index("SPY")
        qqq_result = _load_index("QQQ")
        iwm_result = _load_index("IWM")
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

        result = {
            "success": True,
            "regime": regime,
            "indexes": indexes,
            "cross": cross,
        }
        _endpoint_cache[cache_key] = {"data": result, "ts": _time.time()}
        return result

    except Exception as e:
        logger.error(f"Live regime error: {e}")
        return {"success": False, "error": str(e)}


@router.get("/model-inventory")
def get_model_inventory():
    """
    Get complete inventory of all model definitions with their training status.
    Sync handler — runs in thread pool, doesn't block event loop.
    Cached for 30s to prevent repeated heavy DB queries.
    """
    cache_key = "model_inventory"
    cached = _endpoint_cache.get(cache_key)
    if cached and (_time.time() - cached["ts"]) < _CACHE_TTL:
        return cached["data"]
    
    try:
        from server import db as mongo_db

        # Get trained models from DB
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
            trained_models = _fetch_trained_models()

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
            "finbert_sentiment": {
                "label": "FinBERT Sentiment",
                "description": "Pre-trained news sentiment scoring (bullish/bearish/neutral)",
                "group": "support",
                "models": [],
            },
            "cnn_patterns": {
                "label": "CNN Visual Patterns",
                "description": "ResNet18 chart pattern recognition (WIN/LOSS/SCRATCH from candlestick images)",
                "group": "signal",
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
            {"name": "tft_multi_timeframe", "description": "TFT cross-timeframe attention"},
            {"name": "cnn_lstm_chart", "description": "CNN-LSTM temporal pattern recognition"},
        ]
        for dl in DL_MODELS:
            name = dl["name"]
            # Check dl_models collection as well as timeseries_models
            dl_trained = name in trained_models
            dl_info = trained_models.get(name, {})
            if not dl_trained and mongo_db is not None:
                try:
                    dl_doc = mongo_db["dl_models"].find_one({"name": name}, {"_id": 0, "model_data": 0})
                    logger.info(f"[MODEL-INVENTORY] DL check '{name}': doc_found={dl_doc is not None}")
                    if dl_doc:
                        dl_trained = True
                        metrics = dl_doc.get("metrics", {})
                        dl_info = {
                            "accuracy": metrics.get("accuracy",
                                        dl_doc.get("accuracy",
                                        dl_doc.get("val_accuracy", 0))),
                            "training_samples": (metrics.get("training_samples", 0)
                                                or dl_doc.get("training_samples", 0)),
                            "promoted_at": dl_doc.get("saved_at",
                                          dl_doc.get("updated_at",
                                          dl_doc.get("trained_at", ""))),
                            "model_type": dl_doc.get("model_type", "deep_learning"),
                            "version": dl_doc.get("version", ""),
                        }
                        logger.info(f"[MODEL-INVENTORY] DL '{name}' → trained=True, acc={dl_info.get('accuracy')}, samples={dl_info.get('training_samples')}")
                except Exception as e:
                    logger.error(f"[MODEL-INVENTORY] Error checking DL model '{name}': {e}")
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
                # FinBERT saves scored articles to news_sentiment collection
                sent_count = mongo_db["news_sentiment"].count_documents({})
                if sent_count == 0:
                    # Also check news_articles for raw collection
                    sent_count = mongo_db["news_articles"].count_documents({"sentiment_score": {"$exists": True}})
                if sent_count > 0:
                    finbert_trained = True
                    latest = mongo_db["news_sentiment"].find_one(
                        {}, {"_id": 0, "datetime": 1, "date": 1}, sort=[("datetime", -1)]
                    )
                    finbert_info = {
                        "articles_scored": sent_count,
                        "promoted_at": str(latest.get("datetime", latest.get("date", ""))) if latest else "",
                    }
            except Exception:
                pass
        categories["finbert_sentiment"]["models"].append({
            "name": "finbert_news_sentiment",
            "description": "Scores news articles via ProsusAI/finbert for market sentiment",
            "trained": finbert_trained,
            **finbert_info,
        })

        # CNN Visual Patterns — from cnn_models collection
        try:
            if mongo_db is not None:
                cnn_docs = list(mongo_db["cnn_models"].find(
                    {},
                    {"_id": 0, "gridfs_file_id": 0}
                ).sort("trained_at", -1))
                for doc in cnn_docs:
                    metrics = doc.get("metrics", {})
                    categories["cnn_patterns"]["models"].append({
                        "name": doc.get("model_name", ""),
                        "setup_type": doc.get("setup_type", ""),
                        "bar_size": doc.get("bar_size", ""),
                        "trained": True,
                        "accuracy": metrics.get("accuracy", 0),
                        "win_auc": metrics.get("win_auc", 0),
                        "test_samples": metrics.get("test_samples", 0),
                        "promoted_at": doc.get("trained_at", ""),
                        "model_type": "cnn_resnet18",
                        "size_mb": doc.get("size_mb", 0),
                    })
        except Exception:
            pass

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

        result = {
            "success": True,
            "total_defined": total_defined,
            "total_trained": total_trained,
            "categories": categories,
        }
        _endpoint_cache[cache_key] = {"data": result, "ts": _time.time()}
        return result

    except Exception as e:
        logger.error(f"Model inventory error: {e}")
        return {"success": False, "error": str(e)}



# ============ CONFIDENCE GATE ENDPOINTS ============

@router.get("/confidence-gate/summary")
def get_confidence_gate_summary():
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
def get_confidence_gate_decisions(limit: int = 30):
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
def get_confidence_gate_stats():
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
def get_confidence_gate_accuracy(limit: int = 100):
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



@router.post("/confidence-gate/calibrate")
def calibrate_confidence_gate():
    """
    Run auto-calibration on the confidence gate thresholds.
    Analyzes trade outcomes to find optimal GO/REDUCE/SKIP thresholds per trading mode.
    Requires 50+ tracked outcomes to produce meaningful calibration.
    """
    try:
        from server import db as mongo_db
        from services.ai_modules.gate_calibrator import init_gate_calibrator
        calibrator = init_gate_calibrator(db=mongo_db)
        result = calibrator.calibrate()

        # If calibration succeeded, reload thresholds in the live gate
        if result.get("success"):
            from services.ai_modules.confidence_gate import get_confidence_gate
            gate = get_confidence_gate()
            gate._load_calibrated_thresholds()

        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Confidence gate calibration error: {e}")
        return {"success": False, "error": str(e)}


@router.get("/confidence-gate/calibration")
def get_confidence_gate_calibration():
    """Get the current calibration state (thresholds, analysis, last calibrated)."""
    try:
        from server import db as mongo_db
        doc = mongo_db["gate_calibration"].find_one({"_id": "current"}, {"_id": 0})
        if doc:
            return {"success": True, "calibrated": True, **doc}
        return {"success": True, "calibrated": False, "reason": "No calibration data yet"}
    except Exception as e:
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



# ──────────────────────────────────────────────────────────────────────
#  TROPHY RUN — last successful training pipeline summary (for the
#  FreshnessInspector "Last Trophy Run" SLA tile).
#
#  Reads from `training_runs_archive` (populated when the pipeline marks
#  itself completed in services/ai_modules/training_pipeline.py).
# ──────────────────────────────────────────────────────────────────────

@router.get("/last-trophy-run")
async def get_last_trophy_run(only_trophy: bool = True):
    """Return the most recent archived training run summary.

    A "trophy run" is one that completed with 0 failed models and 0 errors.
    By default returns only trophy runs; pass `only_trophy=false` to fall
    back to the most recent run regardless of failure status.

    Response shape (compact, frontend-friendly):
        {
          "success": True,
          "found": true|false,
          "is_trophy": bool,
          "started_at": iso,
          "completed_at": iso,
          "elapsed_seconds": float,
          "elapsed_human": "6h 54m",
          "models_trained_count": int,
          "models_failed_count": int,
          "errors": int,
          "phase_health": [
              {"phase": "P5", "label": "Sector-Relative",
               "models": 3, "total": 3, "failed": 0, "acc": 0.537,
               "is_recurrence_watch": true, "ok": true},
              ...
          ],
          "headline_accuracies": [
              {"model": "vae_regime_detector", "accuracy": 1.00},
              {"model": "..._predictor", "accuracy": 0.94},
              ...
          ]
        }
    """
    try:
        from server import db
        if db is None:
            return {"success": False, "found": False, "error": "db_unavailable"}

        col = db["training_runs_archive"]
        query = {"is_trophy": True} if only_trophy else {}
        # Most recent by completed_at
        doc = col.find_one(query, sort=[("completed_at", -1)], projection={"_id": 0})
        if not doc and only_trophy:
            # Fall back to any most-recent run if no trophy on file
            doc = col.find_one({}, sort=[("completed_at", -1)], projection={"_id": 0})

        # Fallback for backfilling pre-archive runs: if no archived doc but
        # the live pipeline_status shows a completed run, synthesize a doc
        # from it so the just-finished run shows up in the UI immediately.
        if not doc:
            live = db["training_pipeline_status"].find_one(
                {"_id": "pipeline"}, projection={"_id": 0},
            )
            if live and live.get("phase") == "completed":
                ph_hist = live.get("phase_history") or {}
                # Long-name → P-code map so the UI tile renders correctly
                # (the existing route's `phase_labels` lookup uses short codes).
                LONG_TO_SHORT = {
                    "generic_directional":   "P1",
                    "setup_specific":        "P2",
                    "short_setup_specific":  "P2.5",
                    "volatility_prediction": "P3",
                    "exit_timing":           "P4",
                    "sector_relative":       "P5",
                    "gap_fill":              "P5.5",
                    "risk_of_ruin":          "P6",
                    "regime_conditional":    "P7",
                    "ensemble_meta":         "P8",
                    "cnn_patterns":          "P9",
                    "deep_learning":         "P11",
                    "finbert_sentiment":     "P12",
                    "auto_validation":       "P13",
                }
                # Re-key phase_history under short codes so downstream
                # phase_labels lookup + per-phase rendering works.
                ph_remapped = {}
                for k, v in ph_hist.items():
                    short = LONG_TO_SHORT.get(k, k)
                    ph_remapped[short] = v
                trained = sum((ph.get("models") or 0) for ph in ph_remapped.values())
                failed = sum((ph.get("failed") or 0) for ph in ph_remapped.values())
                # Phase history can be wiped to {} when the next training
                # subprocess starts (TrainingPipelineStatus.__init__ writes
                # a fresh empty dict). Fall back to the durable counters we
                # persist at run-completion: `models_trained_count` and
                # `models_completed` are both monotonic per-run and survive
                # across status updates within the same run.
                if trained == 0:
                    trained = int(
                        live.get("models_trained_count")
                        or live.get("models_completed")
                        or 0
                    )
                if failed == 0:
                    failed = int(live.get("models_failed_count") or 0)
                # Use `completed_models` (always-incremented per model) as a
                # secondary recovery source if recently_completed is short.
                completed_models = list(live.get("completed_models") or [])
                recent = list(live.get("recently_completed") or completed_models)
                # Pull total_samples from durable terminal counter saved at
                # pipeline-end (added 2026-02). Falls back to any earlier key.
                total_samples = int(
                    live.get("total_samples_final")
                    or live.get("total_samples")
                    or 0
                )
                start = live.get("started_at")
                end = live.get("updated_at") or live.get("completed_at")
                elapsed = 0.0
                if start and end:
                    try:
                        elapsed = (datetime.fromisoformat(end.replace("Z", "+00:00"))
                                   - datetime.fromisoformat(start.replace("Z", "+00:00"))
                                  ).total_seconds()
                    except Exception:
                        pass
                doc = {
                    "started_at": start,
                    "completed_at": end,
                    "elapsed_seconds": elapsed,
                    "models_trained_count": trained,
                    "models_failed_count": failed,
                    "errors": int(live.get("errors") or 0),
                    "total_samples": total_samples,
                    "models_trained": recent,
                    "phase_breakdown": ph_remapped,
                    "is_trophy": failed == 0 and int(live.get("errors") or 0) == 0,
                    "_synthesized_from_live": True,
                }

                # Auto-promote synthesized snapshot to archive so subsequent
                # calls hit the durable doc directly. Only promote runs with
                # real signal (trained > 0) to avoid polluting the archive.
                if trained > 0 and start:
                    try:
                        promote = {
                            **{k: v for k, v in doc.items()
                               if k != "_synthesized_from_live"},
                            "_id": start,
                            "archived_at": datetime.now(timezone.utc).isoformat(),
                            "_recovered_from_live": True,
                        }
                        db["training_runs_archive"].update_one(
                            {"_id": promote["_id"]},
                            {"$setOnInsert": promote},
                            upsert=True,
                        )
                        logger.info(
                            f"[TROPHY] Recovered live status into archive "
                            f"({trained} models, started_at={start})"
                        )
                    except Exception as promote_err:
                        logger.warning(
                            f"[TROPHY] Could not auto-promote synthesized "
                            f"trophy doc: {promote_err}"
                        )

        if not doc:
            return {"success": True, "found": False}

        # ── Phase health rollup (recurrence-watch on P5 + P8) ────────
        phase_breakdown = doc.get("phase_breakdown") or {}
        recurrence_watch = {"P5", "P8"}
        phase_labels = {
            "P1": "Generic Directional",
            "P2": "Setup Long",
            "P2.5": "Setup Short",
            "P3": "Volatility",
            "P4": "Exit Timing",
            "P5": "Sector-Relative",
            "P5.5": "Gap Fill",
            "P6": "Risk-of-Ruin",
            "P7": "Regime-Conditional",
            "P8": "Ensemble",
            "P9": "CNN Patterns",
            "P11": "Deep Learning",
            "P12": "FinBERT",
            "P13": "Validation",
        }
        phase_health = []
        for pk, ph in phase_breakdown.items():
            if not isinstance(ph, dict):
                continue
            models = ph.get("models") or ph.get("completed") or 0
            total = ph.get("total") or ph.get("target") or 0
            failed = ph.get("failed") or 0
            phase_health.append({
                "phase": pk,
                "label": phase_labels.get(pk, pk),
                "models": models,
                "total": total,
                "failed": failed,
                "acc": ph.get("acc"),
                "time_minutes": ph.get("time"),
                "is_recurrence_watch": pk in recurrence_watch,
                "ok": failed == 0 and (total == 0 or models >= total),
            })
        phase_health.sort(key=lambda x: x["phase"])

        # ── Headline accuracies — top 6 by accuracy across all models ──
        models_list = doc.get("models_trained") or []
        scored = [m for m in models_list
                  if isinstance(m.get("accuracy"), (int, float))]
        scored.sort(key=lambda m: m["accuracy"], reverse=True)
        headline = [
            {"model": m["name"], "phase": m.get("phase"),
             "accuracy": float(m["accuracy"])}
            for m in scored[:6] if m.get("name")
        ]

        # Elapsed-human
        secs = float(doc.get("elapsed_seconds") or 0)
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        elapsed_human = (f"{h}h {m}m" if h else f"{m}m") if secs > 0 else "—"

        return {
            "success": True,
            "found": True,
            "is_trophy": bool(doc.get("is_trophy")),
            "started_at": doc.get("started_at"),
            "completed_at": doc.get("completed_at"),
            "archived_at": doc.get("archived_at"),
            "elapsed_seconds": secs,
            "elapsed_human": elapsed_human,
            "models_trained_count": int(doc.get("models_trained_count") or 0),
            "models_failed_count": int(doc.get("models_failed_count") or 0),
            "errors": int(doc.get("errors") or 0),
            "total_samples": int(doc.get("total_samples") or 0),
            "phase_health": phase_health,
            "phase_count": len(phase_health),
            "phase_recurrence_watch_ok": all(
                p["ok"] for p in phase_health if p["is_recurrence_watch"]
            ),
            "headline_accuracies": headline,
            "validation_summary": doc.get("validation_summary") or {},
        }
    except Exception as e:
        logger.exception("last-trophy-run failed")
        return {"success": False, "found": False, "error": str(e)}
