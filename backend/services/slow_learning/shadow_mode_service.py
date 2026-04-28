"""
Shadow Mode Service - Phase 6 Slow Learning

Tracks "paper" trading signals without executing real trades.
Validates new filters and strategies before going live.

Features:
- Paper signal tracking
- Performance comparison with actual trades
- Filter effectiveness validation
- Safe strategy testing
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field
import uuid

logger = logging.getLogger(__name__)


@dataclass
class ShadowSignal:
    """A shadow (paper) trading signal"""
    id: str = ""
    symbol: str = ""
    direction: str = "long"
    setup_type: str = ""
    
    # Signal details
    signal_time: str = ""
    signal_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    
    # Context at signal time
    tqs_score: float = 0.0
    market_regime: str = ""
    confirmations: List[str] = field(default_factory=list)
    filter_criteria: Dict = field(default_factory=dict)
    
    # Outcome tracking
    status: str = "pending"  # pending, won, lost, expired
    outcome_time: str = ""
    outcome_price: float = 0.0
    would_have_pnl: float = 0.0
    would_have_r: float = 0.0
    
    # Comparison with actual trading
    actual_trade_taken: bool = False
    actual_trade_id: str = ""
    actual_outcome: str = ""
    
    # Metadata
    filter_id: str = ""  # ID of filter being tested
    notes: str = ""
    created_at: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ShadowSignal":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ShadowFilter:
    """A filter being tested in shadow mode"""
    id: str = ""
    name: str = ""
    description: str = ""
    filter_type: str = ""  # entry, exit, position_size, risk
    
    # Filter criteria
    criteria: Dict = field(default_factory=dict)
    
    # Performance tracking
    signals_generated: int = 0
    signals_won: int = 0
    signals_lost: int = 0
    total_r: float = 0.0
    win_rate: float = 0.0
    
    # Comparison
    vs_no_filter_win_rate: float = 0.0  # Delta vs not using this filter
    
    # Status
    is_active: bool = True
    is_validated: bool = False  # Passed validation criteria
    validation_notes: str = ""
    
    # Timestamps
    created_at: str = ""
    last_signal: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ShadowFilter":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ShadowModeReport:
    """Summary report of shadow mode testing"""
    report_date: str = ""
    report_period_days: int = 30
    
    # Overall stats
    total_signals: int = 0
    signals_resolved: int = 0
    signals_pending: int = 0
    overall_win_rate: float = 0.0
    total_r: float = 0.0
    
    # Filter performance
    filter_performance: List[Dict] = field(default_factory=list)
    
    # Recommendations
    filters_to_activate: List[str] = field(default_factory=list)
    filters_to_review: List[str] = field(default_factory=list)
    filters_to_deactivate: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return asdict(self)


class ShadowModeService:
    """
    Manages shadow mode paper trading.
    
    Use shadow mode to:
    1. Test new entry/exit filters safely
    2. Validate TQS thresholds before applying
    3. Compare paper signals with actual trades
    4. Build confidence in strategy changes
    """
    
    # Minimum signals for validation
    MIN_SIGNALS_FOR_VALIDATION = 20
    MIN_WIN_RATE_IMPROVEMENT = 0.05  # 5% improvement required
    
    def __init__(self):
        self._db = None
        self._shadow_signals_col = None
        self._shadow_filters_col = None
        self._alpaca_service = None
        # 2026-04-28f: IB pusher quote source — primary post-Phase 4.
        self._ib_data_provider = None
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._shadow_signals_col = db['shadow_signals']
            self._shadow_filters_col = db['shadow_filters']
            
            # Create indexes
            self._shadow_signals_col.create_index([("filter_id", 1), ("status", 1)])
            self._shadow_signals_col.create_index([("symbol", 1), ("signal_time", -1)])
            
    def set_alpaca_service(self, alpaca_service):
        """Set Alpaca service for price updates (legacy — superseded
        by IB pusher quotes after Phase 4. Kept for BC.)"""
        self._alpaca_service = alpaca_service

    def set_ib_data_provider(self, ib_data_provider):
        """Set the IB pusher quote source (preferred). Used by
        `update_signal_outcomes` for shadow signal price tracking
        after Phase 4 retired Alpaca."""
        self._ib_data_provider = ib_data_provider
        
    async def create_filter(
        self,
        name: str,
        description: str,
        filter_type: str,
        criteria: Dict
    ) -> ShadowFilter:
        """Create a new shadow filter to test"""
        filter_obj = ShadowFilter(
            id=f"sf_{uuid.uuid4().hex[:12]}",
            name=name,
            description=description,
            filter_type=filter_type,
            criteria=criteria,
            created_at=datetime.now(timezone.utc).isoformat()
        )
        
        if self._shadow_filters_col is not None:
            self._shadow_filters_col.insert_one(filter_obj.to_dict())
            
        return filter_obj
        
    async def record_signal(
        self,
        symbol: str,
        direction: str,
        setup_type: str,
        signal_price: float,
        stop_price: float,
        target_price: float,
        filter_id: str = None,
        tqs_score: float = 0,
        market_regime: str = "",
        confirmations: List[str] = None,
        notes: str = ""
    ) -> ShadowSignal:
        """Record a shadow (paper) trading signal"""
        signal = ShadowSignal(
            id=f"ss_{uuid.uuid4().hex[:12]}",
            symbol=symbol.upper(),
            direction=direction,
            setup_type=setup_type,
            signal_time=datetime.now(timezone.utc).isoformat(),
            signal_price=signal_price,
            stop_price=stop_price,
            target_price=target_price,
            tqs_score=tqs_score,
            market_regime=market_regime,
            confirmations=confirmations or [],
            filter_id=filter_id or "",
            notes=notes,
            created_at=datetime.now(timezone.utc).isoformat()
        )
        
        if self._shadow_signals_col is not None:
            self._shadow_signals_col.insert_one(signal.to_dict())
            
        # Update filter stats
        if filter_id:
            await self._update_filter_signal_count(filter_id)
            
        return signal
        
    async def update_signal_outcomes(self) -> Dict[str, Any]:
        """
        Check pending signals against current prices and update outcomes.
        Should be called periodically (e.g., every 5 minutes during market hours).
        Processes in batches to avoid event loop starvation.
        """
        if self._shadow_signals_col is None:
            return {"updated": 0}
        
        # Step 1: Bulk-expire old signals (>5 days) in one DB call
        cutoff = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        expire_result = self._shadow_signals_col.update_many(
            {"status": "pending", "signal_time": {"$lt": cutoff}},
            {"$set": {
                "status": "expired",
                "outcome_time": datetime.now(timezone.utc).isoformat(),
            }}
        )
        expired_count = expire_result.modified_count
        
        # Step 2: Process remaining pending signals in batches (max 50 per run)
        pending = list(self._shadow_signals_col.find(
            {"status": "pending"}
        ).sort("signal_time", 1).limit(50))
        updated = 0
        
        for signal_doc in pending:
            signal = ShadowSignal.from_dict(signal_doc)
            
            try:
                # Get current price
                current_price = await self._get_current_price(signal.symbol)
                if current_price is None:
                    continue
                    
                # Check for stop or target hit
                outcome = None
                outcome_price = current_price
                
                if signal.direction == "long":
                    if current_price <= signal.stop_price:
                        outcome = "lost"
                    elif current_price >= signal.target_price:
                        outcome = "won"
                else:  # short
                    if current_price >= signal.stop_price:
                        outcome = "lost"
                    elif current_price <= signal.target_price:
                        outcome = "won"
                        
                # Check for expiry (signals older than 5 days)
                signal_time = datetime.fromisoformat(signal.signal_time.replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - signal_time).days
                if age_days > 5 and outcome is None:
                    outcome = "expired"
                    
                if outcome:
                    # Calculate would-have P&L
                    if signal.direction == "long":
                        would_have_pnl = outcome_price - signal.signal_price
                        risk = signal.signal_price - signal.stop_price
                    else:
                        would_have_pnl = signal.signal_price - outcome_price
                        risk = signal.stop_price - signal.signal_price
                        
                    would_have_r = would_have_pnl / risk if risk > 0 else 0
                    
                    # Update signal
                    self._shadow_signals_col.update_one(
                        {"id": signal.id},
                        {"$set": {
                            "status": outcome,
                            "outcome_time": datetime.now(timezone.utc).isoformat(),
                            "outcome_price": outcome_price,
                            "would_have_pnl": would_have_pnl,
                            "would_have_r": would_have_r
                        }}
                    )
                    
                    # Update filter stats
                    if signal.filter_id:
                        await self._update_filter_outcome(signal.filter_id, outcome, would_have_r)
                        
                    updated += 1
                    
            except Exception as e:
                logger.error(f"Error updating signal {signal.id}: {e}")
                
        return {"updated": updated, "expired": expired_count, "pending_checked": len(pending)}
        
    async def _get_current_price(self, symbol: str) -> Optional[float]:
        """Get current price for a symbol. Prefers IB pusher quote
        (post Phase-4); falls back to Alpaca legacy if not injected."""
        # 2026-04-28f: IB pusher path. Without this `update_signal_outcomes`
        # silently never updated any shadow signal — same root cause
        # as the 6,751-decisions-with-0-outcomes tracker bug.
        if self._ib_data_provider is not None:
            try:
                quote = await self._ib_data_provider.get_quote(symbol)
                if quote:
                    price = quote.get("price") or quote.get("last_price") or quote.get("close")
                    if price and float(price) > 0:
                        return float(price)
            except Exception as e:
                logger.warning(f"Shadow: IB pusher price fetch failed for {symbol}: {e}")

        if self._alpaca_service is None:
            return None
        try:
            quote = await self._alpaca_service.get_quote(symbol)
            if quote:
                return quote.get("last_price") or quote.get("close", 0)
        except Exception as e:
            logger.warning(f"Could not get price for {symbol}: {e}")

        return None
        
    async def _update_filter_signal_count(self, filter_id: str):
        """Increment signal count for a filter"""
        if self._shadow_filters_col is None:
            return
            
        self._shadow_filters_col.update_one(
            {"id": filter_id},
            {
                "$inc": {"signals_generated": 1},
                "$set": {"last_signal": datetime.now(timezone.utc).isoformat()}
            }
        )
        
    async def _update_filter_outcome(
        self,
        filter_id: str,
        outcome: str,
        r_multiple: float
    ):
        """Update filter stats with outcome"""
        if self._shadow_filters_col is None:
            return
            
        inc_field = "signals_won" if outcome == "won" else "signals_lost"
        
        self._shadow_filters_col.update_one(
            {"id": filter_id},
            {"$inc": {inc_field: 1, "total_r": r_multiple}}
        )
        
        # Recalculate win rate
        filter_doc = self._shadow_filters_col.find_one({"id": filter_id})
        if filter_doc:
            total = filter_doc.get("signals_won", 0) + filter_doc.get("signals_lost", 0)
            if total > 0:
                win_rate = filter_doc.get("signals_won", 0) / total
                self._shadow_filters_col.update_one(
                    {"id": filter_id},
                    {"$set": {"win_rate": win_rate}}
                )
                
    async def validate_filter(self, filter_id: str) -> Dict[str, Any]:
        """
        Check if a filter has passed validation criteria.
        
        Returns validation result with recommendation.
        """
        if self._shadow_filters_col is None:
            return {"validated": False, "error": "Database not connected"}
            
        filter_doc = self._shadow_filters_col.find_one({"id": filter_id})
        if not filter_doc:
            return {"validated": False, "error": "Filter not found"}
            
        filter_obj = ShadowFilter.from_dict(filter_doc)
        
        # Check minimum signals
        total_signals = filter_obj.signals_won + filter_obj.signals_lost
        if total_signals < self.MIN_SIGNALS_FOR_VALIDATION:
            return {
                "validated": False,
                "reason": f"Insufficient signals ({total_signals}/{self.MIN_SIGNALS_FOR_VALIDATION})",
                "signals_needed": self.MIN_SIGNALS_FOR_VALIDATION - total_signals
            }
            
        # Check win rate
        win_rate = filter_obj.win_rate
        avg_r = filter_obj.total_r / total_signals if total_signals > 0 else 0
        
        # Validation criteria
        is_validated = win_rate >= 0.50 and avg_r >= 0.5
        
        recommendation = "activate" if is_validated else "review"
        if win_rate < 0.40:
            recommendation = "deactivate"
            
        # Update filter
        validation_notes = (
            f"Validated with {total_signals} signals. "
            f"Win rate: {win_rate*100:.1f}%, Avg R: {avg_r:.2f}. "
            f"Recommendation: {recommendation}"
        )
        
        self._shadow_filters_col.update_one(
            {"id": filter_id},
            {"$set": {
                "is_validated": is_validated,
                "validation_notes": validation_notes
            }}
        )
        
        return {
            "validated": is_validated,
            "total_signals": total_signals,
            "win_rate": win_rate,
            "avg_r": avg_r,
            "recommendation": recommendation,
            "notes": validation_notes
        }
        
    async def generate_report(
        self,
        days: int = 30
    ) -> ShadowModeReport:
        """Generate shadow mode performance report"""
        report = ShadowModeReport(
            report_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            report_period_days=days
        )
        
        if self._shadow_signals_col is None:
            return report
            
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Get signals in period
        signals = list(self._shadow_signals_col.find({
            "created_at": {"$gte": cutoff.isoformat()}
        }))
        
        report.total_signals = len(signals)
        report.signals_resolved = sum(1 for s in signals if s.get("status") != "pending")
        report.signals_pending = sum(1 for s in signals if s.get("status") == "pending")
        
        resolved = [s for s in signals if s.get("status") in ["won", "lost"]]
        if resolved:
            wins = sum(1 for s in resolved if s.get("status") == "won")
            report.overall_win_rate = wins / len(resolved)
            report.total_r = sum(s.get("would_have_r", 0) for s in resolved)
            
        # Get filter performance
        if self._shadow_filters_col is not None:
            filters = list(self._shadow_filters_col.find({"is_active": True}))
            
            for f in filters:
                total = f.get("signals_won", 0) + f.get("signals_lost", 0)
                if total > 0:
                    report.filter_performance.append({
                        "filter_id": f.get("id"),
                        "name": f.get("name"),
                        "signals": total,
                        "win_rate": f.get("win_rate", 0),
                        "total_r": f.get("total_r", 0),
                        "is_validated": f.get("is_validated", False)
                    })
                    
                    # Categorize
                    if f.get("is_validated") and f.get("win_rate", 0) >= 0.55:
                        report.filters_to_activate.append(f.get("name"))
                    elif f.get("win_rate", 0) < 0.40:
                        report.filters_to_deactivate.append(f.get("name"))
                    else:
                        report.filters_to_review.append(f.get("name"))
                        
        return report
        
    async def get_filter(self, filter_id: str) -> Optional[ShadowFilter]:
        """Get a specific filter"""
        if self._shadow_filters_col is None:
            return None
            
        doc = self._shadow_filters_col.find_one({"id": filter_id})
        if doc:
            return ShadowFilter.from_dict(doc)
            
        return None
        
    async def get_all_filters(self, active_only: bool = True) -> List[ShadowFilter]:
        """Get all filters"""
        if self._shadow_filters_col is None:
            return []
            
        query = {}
        if active_only:
            query["is_active"] = True
            
        docs = list(self._shadow_filters_col.find(query))
        return [ShadowFilter.from_dict(d) for d in docs]
        
    async def get_signals(
        self,
        filter_id: str = None,
        status: str = None,
        symbol: str = None,
        limit: int = 50
    ) -> List[ShadowSignal]:
        """Get shadow signals with filters"""
        if self._shadow_signals_col is None:
            return []
            
        query = {}
        if filter_id:
            query["filter_id"] = filter_id
        if status:
            query["status"] = status
        if symbol:
            query["symbol"] = symbol.upper()
            
        docs = list(
            self._shadow_signals_col
            .find(query)
            .sort("created_at", -1)
            .limit(limit)
        )
        
        return [ShadowSignal.from_dict(d) for d in docs]
        
    async def deactivate_filter(self, filter_id: str) -> bool:
        """Deactivate a filter"""
        if self._shadow_filters_col is None:
            return False
            
        result = self._shadow_filters_col.update_one(
            {"id": filter_id},
            {"$set": {"is_active": False}}
        )
        return result.modified_count > 0
        
    def get_service_stats(self) -> Dict[str, Any]:
        """Get service statistics"""
        filters = 0
        signals = 0
        pending = 0
        
        if self._shadow_filters_col is not None:
            filters = self._shadow_filters_col.count_documents({"is_active": True})
        if self._shadow_signals_col is not None:
            signals = self._shadow_signals_col.count_documents({})
            pending = self._shadow_signals_col.count_documents({"status": "pending"})
            
        return {
            "db_connected": self._db is not None,
            "active_filters": filters,
            "total_signals": signals,
            "pending_signals": pending
        }


# Singleton
_shadow_mode_service: Optional[ShadowModeService] = None


def get_shadow_mode_service() -> ShadowModeService:
    global _shadow_mode_service
    if _shadow_mode_service is None:
        _shadow_mode_service = ShadowModeService()
    return _shadow_mode_service


def init_shadow_mode_service(db=None, alpaca_service=None, ib_data_provider=None) -> ShadowModeService:
    service = get_shadow_mode_service()
    if db is not None:
        service.set_db(db)
    if alpaca_service is not None:
        service.set_alpaca_service(alpaca_service)
    if ib_data_provider is not None:
        service.set_ib_data_provider(ib_data_provider)
    return service
