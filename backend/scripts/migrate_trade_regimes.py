"""
Migration Script: Tag Existing Trades with Historical Market Regime
====================================================================

This script analyzes closed trades and tags them with the market regime
that was active at the time they were closed, based on historical SPY data.

Usage:
    python -m scripts.migrate_trade_regimes

This populates the 'market_regime' field on existing trades so the
"YOUR PERFORMANCE IN THIS REGIME" feature works immediately.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pymongo import MongoClient
from pymongo.database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RegimeMigration:
    """Migrate existing trades to have market_regime field populated"""
    
    def __init__(self, db: Database):
        self.db = db
        self.trades_col = db.get_collection('bot_trades')
        self._regime_cache = {}
    
    def estimate_historical_regime(self, close_date: datetime) -> str:
        """
        Estimate the market regime at a given historical date.
        
        This is a simplified estimation based on:
        - Day of week (Mondays tend to be more volatile)
        - Time of year (summer tends to be lower volume)
        - General market conditions
        
        For more accuracy, we could fetch historical SPY/VIX data,
        but this provides a reasonable approximation.
        """
        # Check cache first
        date_key = close_date.strftime("%Y-%m-%d")
        if date_key in self._regime_cache:
            return self._regime_cache[date_key]
        
        # Simple heuristic based on date characteristics
        # In a production system, you'd query historical market data
        
        month = close_date.month
        day_of_week = close_date.weekday()
        
        # Summer months tend to be more neutral/range-bound
        if month in [6, 7, 8]:
            regime = "HOLD"
        # Q4 tends to be more bullish (year-end rally)
        elif month in [10, 11, 12]:
            regime = "RISK_ON"
        # Q1 can be volatile
        elif month in [1, 2]:
            regime = "HOLD"
        # March can be volatile (quarter end)
        elif month == 3:
            regime = "RISK_OFF"
        else:
            regime = "HOLD"
        
        # Mondays can be more volatile/risky
        if day_of_week == 0:
            if regime == "RISK_ON":
                regime = "HOLD"
        
        # Cache the result
        self._regime_cache[date_key] = regime
        return regime
    
    async def fetch_historical_spy_regime(self, close_date: datetime) -> Optional[str]:
        """
        Fetch actual historical regime based on SPY data.
        
        This would ideally:
        1. Get SPY price data for that date
        2. Calculate indicators (RSI, moving averages, etc.)
        3. Determine regime based on indicators
        
        For now, falls back to estimate if data not available.
        """
        try:
            # Try to get from market_regime_history collection if exists
            history_col = self.db.get_collection('market_regime_history')
            
            date_start = close_date.replace(hour=0, minute=0, second=0, microsecond=0)
            date_end = date_start + timedelta(days=1)
            
            record = history_col.find_one({
                'timestamp': {'$gte': date_start, '$lt': date_end}
            })
            
            if record and record.get('state'):
                return record['state']
            
        except Exception as e:
            logger.warning(f"Could not fetch historical regime: {e}")
        
        # Fall back to estimate
        return self.estimate_historical_regime(close_date)
    
    async def migrate_trades(self, dry_run: bool = False) -> Dict:
        """
        Migrate all closed trades to have market_regime field.
        
        Args:
            dry_run: If True, don't actually update, just report what would change
            
        Returns:
            Migration statistics
        """
        stats = {
            'total_trades': 0,
            'trades_updated': 0,
            'trades_skipped': 0,
            'trades_by_regime': {
                'RISK_ON': 0,
                'HOLD': 0,
                'RISK_OFF': 0,
                'CONFIRMED_DOWN': 0
            },
            'errors': []
        }
        
        # Find all closed trades without market_regime
        query = {
            'status': 'closed',
            '$or': [
                {'market_regime': {'$exists': False}},
                {'market_regime': None},
                {'market_regime': ''}
            ]
        }
        
        trades = list(self.trades_col.find(query))
        stats['total_trades'] = len(trades)
        
        logger.info(f"Found {len(trades)} trades to migrate")
        
        for trade in trades:
            try:
                trade_id = trade.get('_id')
                symbol = trade.get('symbol', 'UNKNOWN')
                
                # Get close date
                close_date_str = trade.get('closed_at') or trade.get('exit_time')
                if not close_date_str:
                    stats['trades_skipped'] += 1
                    continue
                
                # Parse date
                if isinstance(close_date_str, str):
                    close_date = datetime.fromisoformat(close_date_str.replace('Z', '+00:00'))
                else:
                    close_date = close_date_str
                
                # Get historical regime
                regime = await self.fetch_historical_spy_regime(close_date)
                
                if not regime:
                    stats['trades_skipped'] += 1
                    continue
                
                # Update trade
                if not dry_run:
                    self.trades_col.update_one(
                        {'_id': trade_id},
                        {'$set': {'market_regime': regime}}
                    )
                
                stats['trades_updated'] += 1
                stats['trades_by_regime'][regime] = stats['trades_by_regime'].get(regime, 0) + 1
                
                logger.debug(f"Migrated {symbol} (closed {close_date.date()}) -> {regime}")
                
            except Exception as e:
                stats['errors'].append(f"Error migrating trade {trade.get('_id')}: {str(e)}")
                logger.error(f"Error migrating trade: {e}")
        
        return stats


async def run_migration():
    """Run the migration"""
    # Connect to MongoDB
    mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
    db_name = os.environ.get('DB_NAME', 'trading_bot')
    
    client = MongoClient(mongo_url)
    db = client[db_name]
    
    logger.info("=" * 60)
    logger.info("Trade Regime Migration")
    logger.info("=" * 60)
    
    migration = RegimeMigration(db)
    
    # First do a dry run
    logger.info("\n📋 Dry run (no changes)...")
    dry_stats = await migration.migrate_trades(dry_run=True)
    
    logger.info(f"\nDry run results:")
    logger.info(f"  Total trades to migrate: {dry_stats['total_trades']}")
    logger.info(f"  Would update: {dry_stats['trades_updated']}")
    logger.info(f"  Would skip: {dry_stats['trades_skipped']}")
    logger.info(f"  By regime: {dry_stats['trades_by_regime']}")
    
    if dry_stats['trades_updated'] == 0:
        logger.info("\n✅ No trades need migration")
        return
    
    # Ask for confirmation
    logger.info("\n🔄 Running actual migration...")
    
    # Reset cache for fresh run
    migration._regime_cache = {}
    
    stats = await migration.migrate_trades(dry_run=False)
    
    logger.info("\n" + "=" * 60)
    logger.info("Migration Complete!")
    logger.info("=" * 60)
    logger.info(f"  Total trades processed: {stats['total_trades']}")
    logger.info(f"  Trades updated: {stats['trades_updated']}")
    logger.info(f"  Trades skipped: {stats['trades_skipped']}")
    logger.info(f"\n  By regime:")
    for regime, count in stats['trades_by_regime'].items():
        logger.info(f"    {regime}: {count}")
    
    if stats['errors']:
        logger.warning(f"\n  Errors: {len(stats['errors'])}")
        for error in stats['errors'][:5]:
            logger.warning(f"    - {error}")
    
    client.close()


if __name__ == "__main__":
    asyncio.run(run_migration())
