#!/usr/bin/env python3
"""
SentCom Worker Process - Background Job Processor

This worker runs as a separate process from the main FastAPI server.
It picks up jobs from the MongoDB queue and executes them in isolation.

Benefits:
- Heavy tasks don't block the main app
- If worker crashes, main app keeps running
- Can run multiple workers for parallelism
- No IB connection conflicts

Usage:
    python worker.py                    # Process all job types
    python worker.py --type training    # Process only training jobs
    python worker.py --once             # Process one job and exit

Jobs are processed in priority order (higher priority first, then oldest first).
"""

import asyncio
import argparse
import logging
import signal
import sys
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List

# Add the backend directory to the path
backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, backend_dir)

# Load .env file directly (so worker doesn't depend on BAT file parsing)
env_file = os.path.join(backend_dir, '.env')
if os.path.exists(env_file):
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip()
                if key and not os.environ.get(key):  # Don't override existing env vars
                    os.environ[key] = value

from pymongo import MongoClient
from services.job_queue_manager import job_queue_manager, JobType, JobStatus

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [WORKER] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Worker state
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info("Shutdown signal received, finishing current job...")
    shutdown_requested = True


async def setup_database():
    """Connect to MongoDB using pymongo (sync driver).
    
    All training services expect pymongo cursors. The job_queue_manager
    supports both pymongo and motor via its _run() helper.
    """
    mongo_url = os.environ.get('MONGO_URL')
    db_name = os.environ.get('DB_NAME', 'tradecommand')
    
    if not mongo_url:
        logger.error("MONGO_URL environment variable not set")
        sys.exit(1)
    
    client = MongoClient(mongo_url)
    db = client[db_name]
    
    # Test connection
    try:
        client.admin.command('ping')
        logger.info(f"Connected to MongoDB database: {db_name}")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        sys.exit(1)
    
    # Set up managers
    job_queue_manager.set_db(db)
    
    return db


async def process_training_job(job: dict, db) -> dict:
    """Process an AI training job."""
    params = job.get('params', {})
    job_id = job['job_id']
    
    logger.info(f"Processing training job {job_id}")
    logger.info(f"Parameters: {params}")
    
    # Import training service
    from services.ai_modules.timeseries_service import init_timeseries_ai
    
    # Get the service
    timeseries_service = init_timeseries_ai(db=db)
    
    # Determine training type
    bar_size = params.get('bar_size') or params.get('timeframe', '1 day')
    max_symbols = params.get('max_symbols')
    full_universe = params.get('full_universe', False)
    all_timeframes = params.get('all_timeframes', False)
    
    try:
        # Update progress
        await job_queue_manager.update_progress(
            job_id, percent=5, message='Starting training...'
        )
        
        if all_timeframes:
            # Train all timeframes with per-timeframe progress updates
            timeframes = ["1 day", "1 hour", "5 mins", "15 mins", "30 mins", "1 min", "1 week"]
            logger.info(f"Training ALL {len(timeframes)} timeframes...")
            
            results = {}
            completed_count = 0
            total_elapsed = 0
            
            for idx, tf in enumerate(timeframes):
                tf_num = idx + 1
                pct = int(5 + (idx / len(timeframes)) * 90)  # 5% to 95%
                
                await job_queue_manager.update_progress(
                    job_id, percent=pct, 
                    message=f'Training timeframe {tf_num}/{len(timeframes)}: {tf}...'
                )
                
                logger.info("")
                logger.info(f">>> Timeframe {tf_num}/{len(timeframes)}: {tf}")
                
                try:
                    if full_universe:
                        tf_result = await timeseries_service.train_full_universe(
                            bar_size=tf,
                            max_bars_per_symbol=params.get('max_bars_per_symbol', 99999),
                            symbol_batch_size=params.get('symbol_batch_size', 500)
                        )
                    else:
                        tf_result = await timeseries_service.train_model(
                            bar_size=tf, max_symbols=max_symbols
                        )
                    
                    results[tf] = tf_result
                    
                    if tf_result.get('success'):
                        completed_count += 1
                        elapsed = tf_result.get('elapsed_seconds', 0)
                        total_elapsed += elapsed
                        acc = tf_result.get('accuracy', 0)
                        acc_pct = f"{acc * 100:.1f}%" if acc else 'N/A'
                        
                        await job_queue_manager.update_progress(
                            job_id, percent=pct + 5,
                            message=f'{tf} done ({acc_pct}) - {completed_count}/{len(timeframes)} complete'
                        )
                        logger.info(f">>> {tf} complete: {acc_pct} accuracy in {elapsed:.0f}s")
                    else:
                        logger.error(f">>> {tf} failed: {tf_result.get('error', 'Unknown')}")
                        results[tf] = tf_result
                
                except Exception as tf_err:
                    logger.error(f">>> {tf} exception: {tf_err}")
                    results[tf] = {'success': False, 'error': str(tf_err)}
            
            # Final result
            await job_queue_manager.update_progress(
                job_id, percent=100,
                message=f'Full universe complete! {completed_count}/{len(timeframes)} timeframes in {total_elapsed/60:.1f} min'
            )
            
            result = {
                'success': completed_count > 0,
                'timeframes_trained': completed_count,
                'total_timeframes': len(timeframes),
                'total_elapsed_seconds': total_elapsed,
                'results': results
            }
        else:
            # Train single timeframe
            logger.info(f"Training single timeframe: {bar_size}")
            await job_queue_manager.update_progress(
                job_id, percent=10, message=f'Loading data for {bar_size}...'
            )
            
            if full_universe:
                result = await timeseries_service.train_full_universe(
                    bar_size=bar_size,
                    max_bars_per_symbol=params.get('max_bars_per_symbol', 99999),
                    symbol_batch_size=params.get('symbol_batch_size', 500)
                )
            else:
                result = await timeseries_service.train_model(
                    bar_size=bar_size,
                    max_symbols=max_symbols
                )
        
        # Extract result info
        if result.get('success'):
            # Handle both single-timeframe and full-universe-all results
            if 'results' in result and all_timeframes:
                return result  # Already formatted above
            else:
                # Single timeframe result
                accuracy = result.get('accuracy', 0) or result.get('metrics', {}).get('accuracy', 0)
                accuracy_pct = f"{accuracy * 100:.1f}%" if accuracy else 'N/A'
                
                await job_queue_manager.update_progress(
                    job_id, 
                    percent=100, 
                    message=f'Training complete! {accuracy_pct} accuracy'
                )
                
                return {
                    'success': True,
                    'accuracy': accuracy,
                    'accuracy_percent': accuracy_pct,
                    'training_samples': result.get('training_samples', 0),
                    'details': result
                }
        else:
            return {
                'success': False,
                'error': result.get('error', 'Training failed')
            }
            
    except Exception as e:
        logger.error(f"Training job failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


async def process_data_collection_job(job: dict, db) -> dict:
    """Process a data collection job.
    
    Job params:
        - bar_size: str (default '1 day')
        - symbols: list or None (None = all liquid symbols)
        - duration: str (default '1 M')
        - collection_type: 'liquid' | 'full_market' | 'smart' | 'custom'
        - min_adv: int (for liquid collection, default 100000)
        - min_price: float (for full market, default 1.0)
        - max_price: float (for full market, default 1000.0)
    """
    params = job.get('params', {})
    job_id = job['job_id']
    
    logger.info(f"Processing data collection job {job_id}")
    logger.info(f"Parameters: {params}")
    
    # Import collector service
    from services.ib_historical_collector import init_ib_collector
    
    collector = init_ib_collector(db=db)
    
    try:
        collection_type = params.get('collection_type', 'liquid')
        bar_size = params.get('bar_size', '1 day')
        duration = params.get('duration', '1 M')
        symbols = params.get('symbols')  # None means use collection_type logic
        
        await job_queue_manager.update_progress(
            job_id, percent=5, message=f'Starting {collection_type} data collection for {bar_size}...'
        )
        
        result = None
        
        if collection_type == 'liquid':
            # Collect liquid stocks (high volume)
            min_adv = params.get('min_adv', 100000)
            logger.info(f"Starting liquid collection: {bar_size}, ADV >= {min_adv}")
            result = await collector.start_liquid_collection(
                bar_size=bar_size,
                duration=duration,
                min_adv=min_adv
            )
            
        elif collection_type == 'full_market':
            # Collect all US stocks
            min_price = params.get('min_price', 1.0)
            max_price = params.get('max_price', 1000.0)
            logger.info(f"Starting full market collection: {bar_size}, price ${min_price}-${max_price}")
            result = await collector.start_full_market_collection(
                bar_size=bar_size,
                duration=duration,
                min_price=min_price,
                max_price=max_price
            )
            
        elif collection_type == 'smart':
            # Smart collection - collect what's needed
            logger.info(f"Starting smart collection: {bar_size}")
            result = await collector.start_smart_collection(duration=duration)
            
        elif collection_type == 'custom' and symbols:
            # Custom symbol list
            logger.info(f"Starting custom collection: {bar_size}, {len(symbols)} symbols")
            result = await collector.start_collection(
                symbols=symbols,
                bar_size=bar_size,
                duration=duration,
                use_defaults=False
            )
        else:
            return {
                'success': False,
                'error': f'Unknown collection type or missing symbols: {collection_type}'
            }
        
        # Monitor collection progress
        if result and result.get('success'):
            job_info = result.get('job', {})
            total_symbols = job_info.get('total_symbols', 0)
            
            await job_queue_manager.update_progress(
                job_id, 
                percent=10, 
                message=f'Collection started: {total_symbols} symbols queued'
            )
            
            # Poll for completion (collection runs in background)
            # Note: The actual collection runs via the IB pusher, so we just 
            # return the job info. The UI can poll the collection status separately.
            return {
                'success': True,
                'message': f'Data collection started for {total_symbols} symbols',
                'collection_type': collection_type,
                'bar_size': bar_size,
                'total_symbols': total_symbols,
                'job_info': job_info
            }
        else:
            return {
                'success': False,
                'error': result.get('error', 'Failed to start collection')
            }
        
    except Exception as e:
        logger.error(f"Data collection job failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


async def process_backtest_job(job: dict, db) -> dict:
    """Process a backtest job.
    
    Job params:
        - start_date: str (ISO format)
        - end_date: str (ISO format)
        - universe: 'all' | 'sp500' | 'nasdaq100' | 'custom'
        - custom_symbols: list (if universe is 'custom')
        - bar_size: str (default '1 day')
        - starting_capital: float (default 100000)
        - min_adv: int (default 100000)
        - min_price: float (default 5.0)
        - max_price: float (default 500.0)
        - use_ai_agents: bool (default True)
    """
    params = job.get('params', {})
    job_id = job['job_id']
    
    logger.info(f"Processing backtest job {job_id}")
    logger.info(f"Parameters: {params}")
    
    try:
        # Import simulation service
        from services.simulation_engine import HistoricalSimulationEngine, SimulationConfig
        
        engine = HistoricalSimulationEngine(db)
        await engine.initialize()
        
        await job_queue_manager.update_progress(
            job_id, percent=5, message='Initializing backtest engine...'
        )
        
        # Build simulation config from params
        config = SimulationConfig(
            start_date=params.get('start_date', (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()),
            end_date=params.get('end_date', datetime.now(timezone.utc).isoformat()),
            universe=params.get('universe', 'all'),
            custom_symbols=params.get('custom_symbols', []),
            bar_size=params.get('bar_size', '1 day'),
            starting_capital=params.get('starting_capital', 100000.0),
            min_adv=params.get('min_adv', 100000),
            min_price=params.get('min_price', 5.0),
            max_price=params.get('max_price', 500.0),
            use_ai_agents=params.get('use_ai_agents', True),
            data_source=params.get('data_source', 'ib')
        )
        
        await job_queue_manager.update_progress(
            job_id, percent=10, message=f'Starting backtest: {config.start_date[:10]} to {config.end_date[:10]}...'
        )
        
        # Start the simulation
        sim_job_id = await engine.start_simulation(config)
        
        # Monitor simulation progress
        while True:
            status = await engine.get_job_status(sim_job_id)
            
            if not status:
                await asyncio.sleep(5)
                continue
            
            sim_status = status.get('status')
            progress = status.get('progress', {})
            
            # Update job progress
            percent_complete = progress.get('percent', 0)
            symbols_processed = progress.get('symbols_processed', 0)
            symbols_total = progress.get('symbols_total', 0)
            current_date = status.get('current_date', '')
            
            await job_queue_manager.update_progress(
                job_id,
                percent=min(10 + int(percent_complete * 0.9), 99),
                message=f'Processing {symbols_processed}/{symbols_total} symbols, date: {current_date[:10] if current_date else "..."}'
            )
            
            if sim_status == 'completed':
                # Get final results
                results = status.get('results', {})
                metrics = results.get('metrics', {})
                
                await job_queue_manager.update_progress(
                    job_id, percent=100, 
                    message=f'Backtest complete! Return: {metrics.get("total_return_pct", 0):.1f}%'
                )
                
                return {
                    'success': True,
                    'simulation_id': sim_job_id,
                    'metrics': metrics,
                    'trades_count': results.get('total_trades', 0),
                    'win_rate': metrics.get('win_rate', 0),
                    'total_return': metrics.get('total_return', 0),
                    'details': results
                }
                
            elif sim_status == 'failed':
                return {
                    'success': False,
                    'error': status.get('error', 'Simulation failed')
                }
                
            elif sim_status == 'cancelled':
                return {
                    'success': False,
                    'error': 'Simulation was cancelled'
                }
            
            await asyncio.sleep(5)
        
    except Exception as e:
        logger.error(f"Backtest job failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


async def process_calibration_job(job: dict, db) -> dict:
    """Process a calibration job."""
    job_id = job['job_id']
    
    logger.info(f"Processing calibration job {job_id}")
    
    try:
        from services.learning_connectors_service import init_learning_connectors
        
        service = init_learning_connectors(db=db)
        
        await job_queue_manager.update_progress(
            job_id, percent=5, message='Starting calibration...'
        )
        
        result = await service.run_all_calibrations()
        
        await job_queue_manager.update_progress(
            job_id, percent=100, message='Calibration complete!'
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Calibration job failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


async def process_setup_training_job(job: dict, db) -> dict:
    """Process a setup-specific AI model training job.
    
    Job params:
        - setup_type: str (e.g., 'MOMENTUM', 'BREAKOUT', or 'ALL')
        - bar_size: str (optional — if omitted, trains all profiles for that setup)
        - max_symbols: int (optional)
        - max_bars_per_symbol: int (optional)
    """
    params = job.get('params', {})
    job_id = job['job_id']
    
    logger.info(f"Processing setup training job {job_id}")
    logger.info(f"Parameters: {params}")
    
    from services.ai_modules.timeseries_service import init_timeseries_ai
    
    timeseries_service = init_timeseries_ai(db=db)
    
    setup_type = params.get('setup_type', '').upper()
    bar_size = params.get('bar_size')  # None means train all profiles
    max_symbols = params.get('max_symbols')
    max_bars_per_symbol = params.get('max_bars_per_symbol')
    
    try:
        from services.ai_modules.post_training_validator import (
            backup_current_model, validate_trained_model, run_batch_validation
        )
        
        if setup_type == 'ALL':
            # Train all profiles for all setup types
            from services.ai_modules.setup_training_config import get_setup_profiles
            
            setup_types = list(timeseries_service.SETUP_TYPES.keys())
            total_profiles = 0
            for st in setup_types:
                total_profiles += len(get_setup_profiles(st))
            
            results = {}
            completed = 0
            profile_idx = 0
            validation_results = []
            
            for st in setup_types:
                profiles = get_setup_profiles(st)
                st_results = {}
                
                for profile in profiles:
                    profile_idx += 1
                    pbar = profile["bar_size"]
                    pct = int(5 + (profile_idx / total_profiles) * 75)
                    
                    await job_queue_manager.update_progress(
                        job_id, percent=pct,
                        message=f'Training {st}/{pbar} ({profile_idx}/{total_profiles})...',
                        current_step=profile_idx,
                        total_steps=total_profiles
                    )
                    
                    # Backup current model before training
                    await backup_current_model(db, st, pbar)
                    
                    try:
                        result = await timeseries_service._train_single_setup_profile(
                            setup_type=st,
                            profile=profile,
                            max_symbols=max_symbols,
                            max_bars_per_symbol=max_bars_per_symbol,
                        )
                        st_results[pbar] = result
                        if result.get('success'):
                            completed += 1
                            acc = result.get('metrics', {}).get('accuracy', 0)
                            await job_queue_manager.update_progress(
                                job_id, percent=pct + 2,
                                message=f'{st}/{pbar} done ({acc*100:.1f}%) - {completed}/{total_profiles}'
                            )
                    except Exception as e:
                        logger.error(f"Profile {st}/{pbar} failed: {e}")
                        st_results[pbar] = {'success': False, 'error': str(e)}
                
                results[st] = st_results
            
            # Per-profile validation (Phases 1-3)
            await job_queue_manager.update_progress(
                job_id, percent=80,
                message=f'Training done! Running 5-phase validation on {completed} models...'
            )
            
            backtest_engine = None
            try:
                backtest_engine = _get_backtest_engine(db, timeseries_service)
                val_idx = 0
                for st, st_results in results.items():
                    for pbar, result in st_results.items():
                        if result.get('success'):
                            val_idx += 1
                            base_pct = int(80 + (val_idx / max(completed, 1)) * 14)
                            
                            async def _prog(p, m, _j=job_id, _bp=base_pct):
                                await job_queue_manager.update_progress(_j, percent=min(_bp + 1, 94), message=m)
                            
                            val = await validate_trained_model(
                                db, timeseries_service, backtest_engine,
                                st, pbar, result, job_id, _prog
                            )
                            validation_results.append(val)
            except Exception as val_err:
                logger.warning(f"Per-profile validation error (models still saved): {val_err}")
            
            promoted = sum(1 for v in validation_results if v.get("status") == "promoted")
            rejected = sum(1 for v in validation_results if v.get("status") == "rejected")
            
            # Batch validation (Phases 4-5: Multi-Strategy + Market-Wide)
            batch_result = None
            trained_types = [st for st, sr in results.items() if any(r.get('success') for r in sr.values())]
            if backtest_engine and len(trained_types) >= 2:
                try:
                    await job_queue_manager.update_progress(
                        job_id, percent=95,
                        message=f'Phases 4-5: Multi-Strategy + Market-Wide ({len(trained_types)} setups)...'
                    )
                    
                    async def _batch_prog(p, m):
                        await job_queue_manager.update_progress(job_id, percent=min(p, 99), message=m)
                    
                    batch_result = await run_batch_validation(
                        db, backtest_engine, trained_types, job_id, _batch_prog
                    )
                except Exception as batch_err:
                    logger.warning(f"Batch validation error: {batch_err}")
            
            await job_queue_manager.update_progress(
                job_id, percent=100,
                message=f'Complete! {completed} trained, {promoted} promoted, {rejected} rejected'
            )
            
            return {
                'success': completed > 0,
                'profiles_trained': completed,
                'total_profiles': total_profiles,
                'results': results,
                'validation': {
                    'promoted': promoted,
                    'rejected': rejected,
                    'details': validation_results,
                },
                'batch_validation': batch_result,
            }
        else:
            # Train one setup type (all profiles or specific bar_size)
            if bar_size:
                # Train single profile — backup first
                from services.ai_modules.setup_training_config import get_setup_profile
                profile = get_setup_profile(setup_type, bar_size)
                
                await backup_current_model(db, setup_type, bar_size)
                
                await job_queue_manager.update_progress(
                    job_id, percent=10,
                    message=f'Training {setup_type}/{bar_size} (horizon={profile["forecast_horizon"]})...'
                )
                
                result = await timeseries_service._train_single_setup_profile(
                    setup_type=setup_type,
                    profile=profile,
                    max_symbols=max_symbols,
                    max_bars_per_symbol=max_bars_per_symbol,
                )
            else:
                # Train all profiles for this setup type — backup each
                from services.ai_modules.setup_training_config import get_setup_profiles
                for prof in get_setup_profiles(setup_type):
                    await backup_current_model(db, setup_type, prof["bar_size"])
                
                await job_queue_manager.update_progress(
                    job_id, percent=10,
                    message=f'Training all {setup_type} profiles...'
                )
                
                result = await timeseries_service.train_setup_model(
                    setup_type=setup_type,
                    bar_size=None,
                    max_symbols=max_symbols,
                    max_bars_per_symbol=max_bars_per_symbol,
                )
            
            if result.get('success'):
                acc = result.get('metrics', {}).get('accuracy', 0)
                
                # Per-profile validation (Phases 1-3)
                await job_queue_manager.update_progress(
                    job_id, percent=80,
                    message=f'{setup_type} trained! Running 5-phase validation...'
                )
                
                validation = None
                try:
                    backtest_engine = _get_backtest_engine(db, timeseries_service)
                    from services.ai_modules.setup_training_config import get_setup_profiles as _gsp
                    target_bar = bar_size or (_gsp(setup_type)[0]["bar_size"] if not bar_size else bar_size)
                    
                    async def _prog(p, m):
                        await job_queue_manager.update_progress(job_id, percent=p, message=m)
                    
                    validation = await validate_trained_model(
                        db, timeseries_service, backtest_engine,
                        setup_type, target_bar, result, job_id, _prog
                    )
                except Exception as val_err:
                    logger.warning(f"Validation failed (model still saved): {val_err}")
                
                status = validation.get("status", "unknown") if validation else "skipped"
                await job_queue_manager.update_progress(
                    job_id, percent=100,
                    message=f'{setup_type}: {status.upper()}' + (f' ({acc*100:.1f}% acc)' if acc else '')
                )
                return {
                    'success': True,
                    'setup_type': setup_type,
                    'details': result,
                    'validation': validation,
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', f'Training failed for {setup_type}')
                }
    
    except Exception as e:
        logger.error(f"Setup training job failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def _get_backtest_engine(db, timeseries_service):
    """Create a backtest engine instance for validation."""
    try:
        from services.slow_learning.advanced_backtest_engine import AdvancedBacktestEngine

        engine = AdvancedBacktestEngine()
        engine.set_db(db)
        engine.set_timeseries_model(timeseries_service)
        return engine
    except Exception as e:
        logger.error(f"Failed to create backtest engine: {e}")
        raise



async def process_cnn_training_job(job: dict, db) -> dict:
    """Process a CNN chart pattern training job.
    
    Job params:
        - setup_type: str (e.g., 'BREAKOUT', 'SCALP', or 'ALL')
        - bar_size: str (optional — if omitted, trains all profiles for that setup)
        - max_symbols: int (optional — limit symbols for faster training)
    """
    params = job.get('params', {})
    job_id = job['job_id']
    
    logger.info(f"Processing CNN training job {job_id}")
    logger.info(f"Parameters: {params}")
    
    setup_type = params.get('setup_type', 'ALL').upper()
    bar_size = params.get('bar_size')
    max_symbols = params.get('max_symbols')
    
    try:
        from services.ai_modules.cnn_training_pipeline import run_cnn_training
        
        async def progress_cb(pct, msg):
            await job_queue_manager.update_progress(job_id, percent=pct, message=msg)
        
        result = await run_cnn_training(
            db=db,
            setup_type=setup_type,
            bar_size=bar_size,
            max_symbols=max_symbols,
            progress_callback=progress_cb,
        )
        
        return result
        
    except Exception as e:
        logger.error(f"CNN training job failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


async def process_dl_training_job(job: dict, db) -> dict:
    """Process a Phase 5 Deep Learning training job.
    
    Job params:
        - models: list of models to train (default: ALL)
                  Options: "vae_regime", "tft", "cnn_lstm"
        - max_symbols: int (for TFT and CNN-LSTM)
        - epochs: int (training epochs per model)
    """
    params = job.get('params', {})
    job_id = job['job_id']
    models_to_train = params.get('models', ['vae_regime', 'tft', 'cnn_lstm'])
    max_symbols = params.get('max_symbols', 500)
    epochs = params.get('epochs', 50)

    logger.info(f"[DL TRAINING] Job {job_id} — models: {models_to_train}")
    results = {}

    # 1. VAE Regime
    if 'vae_regime' in models_to_train:
        try:
            await job_queue_manager.update_progress(job_id, percent=5, message="Training VAE Regime...")
            from services.ai_modules.vae_regime import VAERegimeModel
            vae = VAERegimeModel(db=db)
            results['vae_regime'] = await vae.train(db=db, epochs=epochs)
            logger.info(f"[DL TRAINING] VAE Regime: {results['vae_regime'].get('success')}")
        except Exception as e:
            logger.error(f"[DL TRAINING] VAE Regime failed: {e}")
            results['vae_regime'] = {'success': False, 'error': str(e)}

    # 2. TFT
    if 'tft' in models_to_train:
        try:
            await job_queue_manager.update_progress(job_id, percent=30, message="Training TFT...")
            from services.ai_modules.temporal_fusion_transformer import TFTModel
            tft = TFTModel(db=db)
            results['tft'] = await tft.train(db=db, max_symbols=max_symbols, epochs=epochs)
            logger.info(f"[DL TRAINING] TFT: {results['tft'].get('success')}")
        except Exception as e:
            logger.error(f"[DL TRAINING] TFT failed: {e}")
            results['tft'] = {'success': False, 'error': str(e)}

    # 3. CNN-LSTM
    if 'cnn_lstm' in models_to_train:
        try:
            await job_queue_manager.update_progress(job_id, percent=60, message="Training CNN-LSTM...")
            from services.ai_modules.cnn_lstm_model import CNNLSTMModel
            cnn_lstm = CNNLSTMModel(db=db)
            results['cnn_lstm'] = await cnn_lstm.train(db=db, max_symbols=min(max_symbols, 200), epochs=30)
            logger.info(f"[DL TRAINING] CNN-LSTM: {results['cnn_lstm'].get('success')}")
        except Exception as e:
            logger.error(f"[DL TRAINING] CNN-LSTM failed: {e}")
            results['cnn_lstm'] = {'success': False, 'error': str(e)}

    await job_queue_manager.update_progress(job_id, percent=100, message="DL training complete")

    n_success = sum(1 for r in results.values() if r.get('success'))
    return {
        'success': n_success > 0,
        'results': results,
        'models_trained': n_success,
        'total_models': len(models_to_train),
    }


async def process_finbert_job(job: dict, db) -> dict:
    """Process a FinBERT news collection + scoring job.
    
    Job params:
        - symbols: list of tickers (empty = auto-detect from DB)
        - days_back: int (default 30)
        - score_after_collect: bool (default True)
        - batch_size: int (FinBERT scoring batch size)
        - max_articles: int (max articles to score)
    """
    params = job.get('params', {})
    job_id = job['job_id']
    symbols = params.get('symbols', [])
    days_back = params.get('days_back', 30)
    score_after_collect = params.get('score_after_collect', True)
    batch_size = params.get('batch_size', 64)
    max_articles = params.get('max_articles', 10000)

    logger.info(f"[FINBERT] Job {job_id} — symbols: {len(symbols) or 'auto'}, days_back: {days_back}")
    results = {}

    # Auto-detect symbols from DB if none provided
    if not symbols:
        pipeline = [
            {"$match": {"bar_size": "1 day"}},
            {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gte": 50}}},
            {"$sort": {"count": -1}},
            {"$limit": 100},
        ]
        symbols = [r["_id"] for r in db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True)]
        logger.info(f"[FINBERT] Auto-detected {len(symbols)} symbols from DB")

    # Step 1: Collect news from Finnhub
    try:
        await job_queue_manager.update_progress(job_id, percent=5, message=f"Collecting news for {len(symbols)} symbols...")
        from services.ai_modules.finbert_sentiment import FinnhubNewsCollector
        collector = FinnhubNewsCollector(db=db)
        results['collection'] = await collector.collect_news(symbols=symbols, days_back=days_back)
        logger.info(f"[FINBERT] Collection: {results['collection'].get('new_articles_stored', 0)} new articles")
    except Exception as e:
        logger.error(f"[FINBERT] News collection failed: {e}")
        results['collection'] = {'success': False, 'error': str(e)}

    # Step 2: Score with FinBERT
    if score_after_collect:
        try:
            await job_queue_manager.update_progress(job_id, percent=50, message="Scoring articles with FinBERT...")
            from services.ai_modules.finbert_sentiment import FinBERTSentiment
            scorer = FinBERTSentiment(db=db)
            results['scoring'] = await scorer.score_unscored_articles(
                batch_size=batch_size, max_articles=max_articles
            )
            logger.info(f"[FINBERT] Scoring: {results['scoring'].get('scored', 0)} articles scored")
        except Exception as e:
            logger.error(f"[FINBERT] Scoring failed: {e}")
            results['scoring'] = {'success': False, 'error': str(e)}

    await job_queue_manager.update_progress(job_id, percent=100, message="FinBERT pipeline complete")

    return {
        'success': True,
        'results': results,
    }


async def process_job(job: dict, db) -> dict:
    """Route job to appropriate processor."""
    job_type = job.get('job_type')
    
    processors = {
        JobType.TRAINING.value: process_training_job,
        JobType.SETUP_TRAINING.value: process_setup_training_job,
        JobType.DATA_COLLECTION.value: process_data_collection_job,
        JobType.BACKTEST.value: process_backtest_job,
        JobType.CALIBRATION.value: process_calibration_job,
        JobType.CNN_TRAINING.value: process_cnn_training_job,
        JobType.DL_TRAINING.value: process_dl_training_job,
        JobType.FINBERT_ANALYSIS.value: process_finbert_job,
    }
    
    processor = processors.get(job_type)
    if not processor:
        return {
            'success': False,
            'error': f'Unknown job type: {job_type}'
        }
    
    return await processor(job, db)


async def worker_loop(job_types: Optional[List[str]] = None, once: bool = False):
    """Main worker loop."""
    global shutdown_requested
    
    logger.info("=" * 60)
    logger.info("SentCom Worker Starting")
    logger.info(f"Job types: {job_types or 'ALL'}")
    logger.info(f"Mode: {'Single job' if once else 'Continuous'}")
    logger.info("=" * 60)
    
    # Connect to database
    db = await setup_database()
    
    jobs_processed = 0
    
    while not shutdown_requested:
        try:
            # Get next job
            job = await job_queue_manager.get_next_job(job_types)
            
            if job:
                job_id = job['job_id']
                job_type = job['job_type']
                
                logger.info("")
                logger.info("=" * 40)
                logger.info(f"Processing job: {job_id} ({job_type})")
                logger.info("=" * 40)
                
                # Process the job
                result = await process_job(job, db)
                
                # Update job status
                if result.get('success'):
                    await job_queue_manager.complete_job(job_id, result)
                    logger.info(f"Job {job_id} completed successfully")
                else:
                    await job_queue_manager.fail_job(job_id, result.get('error', 'Unknown error'))
                    logger.error(f"Job {job_id} failed: {result.get('error')}")
                
                # Auto-restore to LIVE mode after job completes
                try:
                    from services.focus_mode_manager import focus_mode_manager
                    # Only reset if no other jobs are pending
                    pending = await job_queue_manager.get_next_job()
                    if not pending:
                        focus_mode_manager.reset_to_live()
                        logger.info("[FOCUS] Auto-restored to LIVE mode (no pending jobs)")
                    else:
                        # Put the pending job back
                        logger.info(f"[FOCUS] Keeping current mode — {pending.get('job_type')} job pending")
                except Exception as fm_err:
                    logger.warning(f"Focus mode reset error: {fm_err}")
                
                jobs_processed += 1
                
                if once:
                    break
            else:
                # No jobs available, wait before checking again
                if not once:
                    await asyncio.sleep(5)
                else:
                    logger.info("No pending jobs")
                    break
                    
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
            await asyncio.sleep(10)  # Wait before retrying
    
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Worker shutting down. Processed {jobs_processed} jobs.")
    logger.info("=" * 60)


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(description='SentCom Background Job Worker')
    parser.add_argument(
        '--type', '-t',
        choices=[j.value for j in JobType],
        help='Process only jobs of this type'
    )
    parser.add_argument(
        '--once', '-o',
        action='store_true',
        help='Process one job and exit'
    )
    
    args = parser.parse_args()
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run the worker
    job_types = [args.type] if args.type else None
    asyncio.run(worker_loop(job_types=job_types, once=args.once))


if __name__ == '__main__':
    main()
