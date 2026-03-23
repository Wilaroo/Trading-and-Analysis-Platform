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
from datetime import datetime, timezone
from typing import Optional, List

# Add the backend directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from motor.motor_asyncio import AsyncIOMotorClient
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
    """Connect to MongoDB."""
    mongo_url = os.environ.get('MONGO_URL')
    db_name = os.environ.get('DB_NAME', 'tradecommand')
    
    if not mongo_url:
        logger.error("MONGO_URL environment variable not set")
        sys.exit(1)
    
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    
    # Test connection
    try:
        await client.admin.command('ping')
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
    from services.ai_modules.timeseries_service import get_timeseries_service
    
    # Get the service
    timeseries_service = get_timeseries_service(db)
    
    # Determine training type
    bar_size = params.get('bar_size') or params.get('timeframe', '1 day')
    max_symbols = params.get('max_symbols')
    full_universe = params.get('full_universe', False)
    all_timeframes = params.get('all_timeframes', False)
    
    try:
        # Update progress
        await job_queue_manager.update_progress(
            job_id, percent=5, message=f'Starting training for {bar_size}...'
        )
        
        if all_timeframes:
            # Train all timeframes
            logger.info("Training ALL timeframes...")
            await job_queue_manager.update_progress(
                job_id, percent=10, message='Training all timeframes...'
            )
            
            if full_universe:
                result = await timeseries_service.train_full_universe_all_timeframes(
                    max_symbols=max_symbols
                )
            else:
                result = await timeseries_service.train_all_timeframes(
                    max_symbols=max_symbols
                )
        else:
            # Train single timeframe
            logger.info(f"Training single timeframe: {bar_size}")
            await job_queue_manager.update_progress(
                job_id, percent=10, message=f'Loading data for {bar_size}...'
            )
            
            if full_universe:
                result = await timeseries_service.train_full_universe(
                    bar_size=bar_size,
                    max_symbols=max_symbols
                )
            else:
                result = await timeseries_service.train_single_timeframe(
                    bar_size=bar_size,
                    max_symbols=max_symbols
                )
        
        # Extract result info
        if result.get('success'):
            accuracy = result.get('metrics', {}).get('accuracy', 0)
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
    """Process a data collection job."""
    params = job.get('params', {})
    job_id = job['job_id']
    
    logger.info(f"Processing data collection job {job_id}")
    logger.info(f"Parameters: {params}")
    
    # Import collector service
    from services.ib_historical_collector import get_collector_service
    
    collector = get_collector_service(db)
    
    try:
        bar_size = params.get('bar_size', '1 day')
        symbols = params.get('symbols')  # None means all
        
        await job_queue_manager.update_progress(
            job_id, percent=5, message=f'Starting collection for {bar_size}...'
        )
        
        # This would need to be implemented based on your collector service
        # For now, return a placeholder
        result = {
            'success': True,
            'message': 'Data collection not yet implemented in worker',
            'bar_size': bar_size
        }
        
        return result
        
    except Exception as e:
        logger.error(f"Data collection job failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


async def process_backtest_job(job: dict, db) -> dict:
    """Process a backtest job."""
    params = job.get('params', {})
    job_id = job['job_id']
    
    logger.info(f"Processing backtest job {job_id}")
    logger.info(f"Parameters: {params}")
    
    try:
        # Import simulation service
        from services.historical_simulation_engine import HistoricalSimulationEngine
        
        engine = HistoricalSimulationEngine(db)
        
        await job_queue_manager.update_progress(
            job_id, percent=5, message='Starting backtest...'
        )
        
        # Run the simulation
        result = await engine.run_simulation(params)
        
        if result.get('success'):
            await job_queue_manager.update_progress(
                job_id, percent=100, message='Backtest complete!'
            )
        
        return result
        
    except Exception as e:
        logger.error(f"Backtest job failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


async def process_calibration_job(job: dict, db) -> dict:
    """Process a calibration job."""
    params = job.get('params', {})
    job_id = job['job_id']
    
    logger.info(f"Processing calibration job {job_id}")
    
    try:
        from services.learning_connectors_service import get_learning_connectors_service
        
        service = get_learning_connectors_service(db)
        
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


async def process_job(job: dict, db) -> dict:
    """Route job to appropriate processor."""
    job_type = job.get('job_type')
    
    processors = {
        JobType.TRAINING.value: process_training_job,
        JobType.DATA_COLLECTION.value: process_data_collection_job,
        JobType.BACKTEST.value: process_backtest_job,
        JobType.CALIBRATION.value: process_calibration_job,
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
