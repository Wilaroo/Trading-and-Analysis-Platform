"""
Weekly Intelligence Report Service - Phase 5 Enhancement

Generates comprehensive weekly trading reports that combine:
1. Performance analytics (stats, charts data)
2. Learning insights (from Medium Learning services)
3. Personal reflection sections (editable by user)

These reports are stored as journal entries in the Trading Journal Tab.
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


@dataclass
class PerformanceSnapshot:
    """Weekly performance metrics"""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    scratches: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_r: float = 0.0
    avg_r_per_trade: float = 0.0
    profit_factor: float = 0.0
    best_day: str = ""
    best_day_pnl: float = 0.0
    worst_day: str = ""
    worst_day_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    
    # Comparison to previous week
    win_rate_change: float = 0.0
    pnl_change: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass 
class ContextInsight:
    """Insight about a context combination"""
    context_key: str = ""
    setup_type: str = ""
    market_regime: str = ""
    time_of_day: str = ""
    trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    trend: str = "stable"  # improving, stable, declining
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class EdgeAlert:
    """Edge decay alert"""
    edge_name: str = ""
    severity: str = "mild"  # mild, moderate, severe
    message: str = ""
    all_time_win_rate: float = 0.0
    recent_win_rate: float = 0.0
    drop_percent: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class CalibrationSuggestion:
    """Threshold calibration suggestion"""
    parameter: str = ""
    current_value: float = 0.0
    suggested_value: float = 0.0
    reason: str = ""
    confidence: str = "low"
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ConfirmationInsight:
    """Insight about confirmation signal effectiveness"""
    confirmation_type: str = ""
    win_rate_lift: float = 0.0
    is_effective: bool = True
    recommendation: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class PlaybookFocus:
    """Playbook focus recommendation"""
    playbook_name: str = ""
    action: str = ""  # focus, review, avoid
    reason: str = ""
    win_rate: float = 0.0
    profit_factor: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class PersonalReflection:
    """User's personal reflection section"""
    what_went_well: str = ""
    what_to_improve: str = ""
    key_lessons: str = ""
    goals_for_next_week: str = ""
    mood_rating: int = 3  # 1-5
    confidence_rating: int = 3  # 1-5
    notes: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "PersonalReflection":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class WeeklyIntelligenceReport:
    """Complete weekly intelligence report"""
    id: str = ""
    week_number: int = 0
    year: int = 0
    week_start: str = ""  # Monday
    week_end: str = ""    # Friday
    
    # Auto-generated sections
    performance: PerformanceSnapshot = field(default_factory=PerformanceSnapshot)
    top_contexts: List[Dict] = field(default_factory=list)
    struggling_contexts: List[Dict] = field(default_factory=list)
    edge_alerts: List[Dict] = field(default_factory=list)
    calibration_suggestions: List[Dict] = field(default_factory=list)
    confirmation_insights: List[Dict] = field(default_factory=list)
    playbook_focus: List[Dict] = field(default_factory=list)
    
    # User-editable section
    reflection: PersonalReflection = field(default_factory=PersonalReflection)
    
    # Metadata
    generated_at: str = ""
    last_updated: str = ""
    is_complete: bool = False  # User marks as complete after adding reflection
    
    def to_dict(self) -> Dict:
        d = asdict(self)
        return d
    
    @classmethod
    def from_dict(cls, data: Dict) -> "WeeklyIntelligenceReport":
        # Handle nested dataclasses
        if "performance" in data and isinstance(data["performance"], dict):
            data["performance"] = PerformanceSnapshot(**data["performance"])
        if "reflection" in data and isinstance(data["reflection"], dict):
            data["reflection"] = PersonalReflection.from_dict(data["reflection"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class WeeklyReportService:
    """
    Generates and manages weekly intelligence reports.
    
    Reports are stored in MongoDB and displayed in the Trading Journal Tab.
    Auto-generates on Friday after market close, but can be triggered manually.
    """
    
    def __init__(self):
        self._db = None
        self._weekly_reports_col = None
        self._trade_outcomes_col = None
        
        # Medium Learning services
        self._calibration_service = None
        self._context_performance_service = None
        self._confirmation_validator_service = None
        self._playbook_performance_service = None
        self._edge_decay_service = None
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._weekly_reports_col = db['weekly_intelligence_reports']
            self._trade_outcomes_col = db['trade_outcomes']
            
            # Create indexes
            self._weekly_reports_col.create_index([("year", -1), ("week_number", -1)])
            self._weekly_reports_col.create_index([("week_start", -1)])
            
    def set_services(
        self,
        calibration_service=None,
        context_performance_service=None,
        confirmation_validator_service=None,
        playbook_performance_service=None,
        edge_decay_service=None
    ):
        """Wire up Medium Learning services"""
        self._calibration_service = calibration_service
        self._context_performance_service = context_performance_service
        self._confirmation_validator_service = confirmation_validator_service
        self._playbook_performance_service = playbook_performance_service
        self._edge_decay_service = edge_decay_service
        
    async def generate_weekly_report(
        self,
        week_start: str = None,
        force: bool = False
    ) -> WeeklyIntelligenceReport:
        """
        Generate a weekly intelligence report.
        
        Args:
            week_start: Start date of the week (Monday). If None, uses current week.
            force: If True, regenerate even if report exists.
            
        Returns:
            WeeklyIntelligenceReport
        """
        # Calculate week boundaries
        if week_start:
            start_date = datetime.fromisoformat(week_start)
        else:
            # Get Monday of current week
            today = datetime.now(timezone.utc)
            days_since_monday = today.weekday()
            start_date = today - timedelta(days=days_since_monday)
            
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=4)  # Friday
        
        week_number = start_date.isocalendar()[1]
        year = start_date.year
        
        # Check if report exists
        if not force and self._weekly_reports_col is not None:
            existing = self._weekly_reports_col.find_one({
                "year": year,
                "week_number": week_number
            })
            if existing:
                existing.pop('_id', None)
                return WeeklyIntelligenceReport.from_dict(existing)
                
        # Create new report
        report = WeeklyIntelligenceReport(
            id=f"wir_{year}_w{week_number}",
            week_number=week_number,
            year=year,
            week_start=start_date.strftime("%Y-%m-%d"),
            week_end=end_date.strftime("%Y-%m-%d"),
            generated_at=datetime.now(timezone.utc).isoformat(),
            last_updated=datetime.now(timezone.utc).isoformat()
        )
        
        # Get trades for this week
        trades = await self._get_week_trades(start_date, end_date)
        
        # Generate each section with individual timeouts to prevent hangs
        import asyncio
        
        async def _safe_call(coro, default, label=""):
            """Run an async call with a 10s timeout, return default on failure"""
            try:
                return await asyncio.wait_for(coro, timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning(f"Weekly report section timed out: {label}")
                return default
            except Exception as e:
                logger.warning(f"Weekly report section failed ({label}): {e}")
                return default
        
        report.performance = await _safe_call(
            self._generate_performance_snapshot(trades, start_date),
            PerformanceSnapshot(), "performance"
        )
        report.top_contexts = await _safe_call(
            self._get_top_contexts(), [], "top_contexts"
        )
        report.struggling_contexts = await _safe_call(
            self._get_struggling_contexts(), [], "struggling_contexts"
        )
        report.edge_alerts = await _safe_call(
            self._get_edge_alerts(), [], "edge_alerts"
        )
        report.calibration_suggestions = await _safe_call(
            self._get_calibration_suggestions(), [], "calibration_suggestions"
        )
        report.confirmation_insights = await _safe_call(
            self._get_confirmation_insights(), [], "confirmation_insights"
        )
        report.playbook_focus = await _safe_call(
            self._get_playbook_focus(), [], "playbook_focus"
        )
        
        # Save to database
        if self._weekly_reports_col is not None:
            doc = report.to_dict()
            doc.pop('_id', None)
            self._weekly_reports_col.update_one(
                {"id": report.id},
                {"$set": doc},
                upsert=True
            )
            
        return report
        
    async def _get_week_trades(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict]:
        """Get trades for a specific week — merges trade_outcomes + bot_trades.
        Runs blocking PyMongo queries in thread pool to avoid blocking the event loop.
        """
        import asyncio
        
        def _fetch_trades():
            trades = []
            # 1. Manual trade outcomes
            if self._trade_outcomes_col is not None:
                try:
                    outcome_trades = list(self._trade_outcomes_col.find({
                        "created_at": {
                            "$gte": start_date.isoformat(),
                            "$lte": (end_date + timedelta(days=1)).isoformat()
                        }
                    }, {"_id": 0}))
                    trades.extend(outcome_trades)
                except Exception:
                    pass
            
            # 2. Bot trades (closed) from bot_trades collection
            try:
                if self._db is not None:
                    bot_closed = list(self._db["bot_trades"].find({
                        "status": "closed",
                        "$or": [
                            {"closed_at": {
                                "$gte": start_date.isoformat(),
                                "$lte": (end_date + timedelta(days=1)).isoformat()
                            }},
                            {"executed_at": {
                                "$gte": start_date.isoformat(),
                                "$lte": (end_date + timedelta(days=1)).isoformat()
                            }}
                        ]
                    }, {"_id": 0}).limit(500))
                    
                    for bt in bot_closed:
                        pnl = bt.get("realized_pnl", 0) or 0
                        if pnl == 0 and bt.get("fill_price") and bt.get("close_price") and bt.get("shares"):
                            entry = bt["fill_price"]
                            exit_p = bt["close_price"]
                            shares = bt["shares"]
                            if bt.get("direction", "long") == "short":
                                pnl = (entry - exit_p) * shares
                            else:
                                pnl = (exit_p - entry) * shares
                        
                        trades.append({
                            "symbol": bt.get("symbol"),
                            "setup_type": bt.get("setup_type"),
                            "direction": bt.get("direction"),
                            "pnl": pnl,
                            "pnl_percent": bt.get("pnl_percent", 0),
                            "outcome": "won" if pnl > 0 else "lost" if pnl < 0 else "scratch",
                            "market_regime": bt.get("market_regime"),
                            "created_at": bt.get("executed_at") or bt.get("closed_at"),
                            "source": "bot"
                        })
            except Exception:
                pass
            return trades
        
        return await asyncio.to_thread(_fetch_trades)
        
    async def _generate_performance_snapshot(
        self,
        trades: List[Dict],
        week_start: datetime
    ) -> PerformanceSnapshot:
        """Generate performance snapshot from trades"""
        snapshot = PerformanceSnapshot()
        
        if not trades:
            return snapshot
            
        snapshot.total_trades = len(trades)
        snapshot.wins = sum(1 for t in trades if t.get("outcome") == "won")
        snapshot.losses = sum(1 for t in trades if t.get("outcome") == "lost")
        snapshot.scratches = sum(1 for t in trades if t.get("outcome") == "scratch")
        
        total = snapshot.wins + snapshot.losses
        snapshot.win_rate = snapshot.wins / total if total > 0 else 0
        
        # P&L
        pnls = [t.get("pnl", 0) for t in trades]
        snapshot.total_pnl = sum(pnls)
        
        wins_pnl = [p for p in pnls if p > 0]
        losses_pnl = [p for p in pnls if p < 0]
        
        snapshot.avg_win = sum(wins_pnl) / len(wins_pnl) if wins_pnl else 0
        snapshot.avg_loss = abs(sum(losses_pnl) / len(losses_pnl)) if losses_pnl else 0
        snapshot.largest_win = max(pnls) if pnls else 0
        snapshot.largest_loss = min(pnls) if pnls else 0
        
        gross_profit = sum(wins_pnl) if wins_pnl else 0
        gross_loss = abs(sum(losses_pnl)) if losses_pnl else 0
        snapshot.profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # R metrics
        rs = [t.get("actual_r", 0) for t in trades]
        snapshot.total_r = sum(rs)
        snapshot.avg_r_per_trade = snapshot.total_r / len(rs) if rs else 0
        
        # Best/Worst days
        day_pnls: Dict[str, float] = {}
        for t in trades:
            date = t.get("created_at", "")[:10]
            if date:
                day_pnls[date] = day_pnls.get(date, 0) + t.get("pnl", 0)
                
        if day_pnls:
            best_day = max(day_pnls.items(), key=lambda x: x[1])
            worst_day = min(day_pnls.items(), key=lambda x: x[1])
            snapshot.best_day = best_day[0]
            snapshot.best_day_pnl = best_day[1]
            snapshot.worst_day = worst_day[0]
            snapshot.worst_day_pnl = worst_day[1]
            
        # Get previous week for comparison
        prev_week_start = week_start - timedelta(days=7)
        prev_week_end = week_start - timedelta(days=3)
        prev_trades = await self._get_week_trades(prev_week_start, prev_week_end)
        
        if prev_trades:
            prev_wins = sum(1 for t in prev_trades if t.get("outcome") == "won")
            prev_total = prev_wins + sum(1 for t in prev_trades if t.get("outcome") == "lost")
            prev_win_rate = prev_wins / prev_total if prev_total > 0 else 0
            prev_pnl = sum(t.get("pnl", 0) for t in prev_trades)
            
            snapshot.win_rate_change = (snapshot.win_rate - prev_win_rate) * 100
            snapshot.pnl_change = snapshot.total_pnl - prev_pnl
            
        return snapshot
        
    async def _get_top_contexts(self, limit: int = 5) -> List[Dict]:
        """Get top performing contexts"""
        if self._context_performance_service is None:
            return []
            
        try:
            all_perf = await self._context_performance_service.get_all_performances()
            qualified = [p for p in all_perf if p.total_trades >= 5]
            top = sorted(qualified, key=lambda p: p.win_rate * max(p.profit_factor, 0.5), reverse=True)[:limit]
            
            return [
                ContextInsight(
                    context_key=p.context_key,
                    setup_type=p.setup_type,
                    market_regime=p.market_regime,
                    time_of_day=p.time_of_day,
                    trades=p.total_trades,
                    win_rate=p.win_rate,
                    total_pnl=p.total_pnl,
                    trend=p.win_rate_trend
                ).to_dict()
                for p in top
            ]
        except Exception as e:
            logger.error(f"Error getting top contexts: {e}")
            return []
            
    async def _get_struggling_contexts(self, limit: int = 5) -> List[Dict]:
        """Get struggling contexts"""
        if self._context_performance_service is None:
            return []
            
        try:
            all_perf = await self._context_performance_service.get_all_performances()
            qualified = [p for p in all_perf if p.total_trades >= 5]
            # Filter to struggling ones
            struggling = [p for p in qualified if p.win_rate < 0.45 or p.profit_factor < 0.8]
            bottom = sorted(struggling, key=lambda p: p.win_rate)[:limit]
            
            return [
                ContextInsight(
                    context_key=p.context_key,
                    setup_type=p.setup_type,
                    market_regime=p.market_regime,
                    time_of_day=p.time_of_day,
                    trades=p.total_trades,
                    win_rate=p.win_rate,
                    total_pnl=p.total_pnl,
                    trend=p.win_rate_trend
                ).to_dict()
                for p in bottom
            ]
        except Exception as e:
            logger.error(f"Error getting struggling contexts: {e}")
            return []
            
    async def _get_edge_alerts(self) -> List[Dict]:
        """Get edge decay alerts"""
        if self._edge_decay_service is None:
            return []
            
        try:
            decaying = await self._edge_decay_service.get_decaying_edges()
            
            return [
                EdgeAlert(
                    edge_name=e.name,
                    severity=e.decay_severity,
                    message=e.alert_message,
                    all_time_win_rate=e.all_time_win_rate,
                    recent_win_rate=e.win_rate_30d,
                    drop_percent=(e.all_time_win_rate - e.win_rate_30d) * 100
                ).to_dict()
                for e in decaying
            ]
        except Exception as e:
            logger.error(f"Error getting edge alerts: {e}")
            return []
            
    async def _get_calibration_suggestions(self, limit: int = 5) -> List[Dict]:
        """Get calibration suggestions"""
        if self._calibration_service is None:
            return []
            
        try:
            recommendations = await self._calibration_service.analyze_and_recommend(30)
            
            return [
                CalibrationSuggestion(
                    parameter=r.parameter,
                    current_value=r.current_value,
                    suggested_value=r.recommended_value,
                    reason=r.reason,
                    confidence=r.confidence
                ).to_dict()
                for r in recommendations[:limit]
            ]
        except Exception as e:
            logger.error(f"Error getting calibration suggestions: {e}")
            return []
            
    async def _get_confirmation_insights(self) -> List[Dict]:
        """Get confirmation signal insights"""
        if self._confirmation_validator_service is None:
            return []
            
        try:
            all_stats = await self._confirmation_validator_service.get_all_stats()
            
            # Only include those with significant impact
            significant = [s for s in all_stats if abs(s.win_rate_lift) > 3 and s.confidence != "low"]
            
            return [
                ConfirmationInsight(
                    confirmation_type=s.confirmation_type,
                    win_rate_lift=s.win_rate_lift,
                    is_effective=s.is_effective,
                    recommendation=s.recommendation
                ).to_dict()
                for s in sorted(significant, key=lambda x: abs(x.win_rate_lift), reverse=True)
            ]
        except Exception as e:
            logger.error(f"Error getting confirmation insights: {e}")
            return []
            
    async def _get_playbook_focus(self) -> List[Dict]:
        """Get playbook focus recommendations"""
        if self._playbook_performance_service is None:
            return []
            
        try:
            all_perf = await self._playbook_performance_service.get_all_performance()
            qualified = [p for p in all_perf if p.total_trades >= 5]
            
            focus_items = []
            
            # Top performers to focus on
            top = sorted(qualified, key=lambda p: p.win_rate * max(p.profit_factor, 0.5), reverse=True)[:3]
            for p in top:
                if p.win_rate >= 0.55 and p.profit_factor >= 1.2:
                    focus_items.append(PlaybookFocus(
                        playbook_name=p.playbook_name,
                        action="focus",
                        reason=f"Strong performer with {p.win_rate*100:.0f}% win rate",
                        win_rate=p.win_rate,
                        profit_factor=p.profit_factor
                    ).to_dict())
                    
            # Underperformers to review or avoid
            bottom = sorted(qualified, key=lambda p: p.win_rate)[:3]
            for p in bottom:
                if p.win_rate < 0.40 or p.profit_factor < 0.8:
                    action = "avoid" if p.profit_factor < 0.7 else "review"
                    focus_items.append(PlaybookFocus(
                        playbook_name=p.playbook_name,
                        action=action,
                        reason=f"Struggling with {p.win_rate*100:.0f}% win rate",
                        win_rate=p.win_rate,
                        profit_factor=p.profit_factor
                    ).to_dict())
                    
            return focus_items
        except Exception as e:
            logger.error(f"Error getting playbook focus: {e}")
            return []
            
    async def update_reflection(
        self,
        report_id: str,
        reflection: Dict
    ) -> Optional[WeeklyIntelligenceReport]:
        """Update the personal reflection section of a report"""
        if self._weekly_reports_col is None:
            return None
            
        # Validate and update
        updates = {
            "reflection": reflection,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        
        result = self._weekly_reports_col.find_one_and_update(
            {"id": report_id},
            {"$set": updates},
            return_document=True
        )
        
        if result:
            result.pop('_id', None)
            return WeeklyIntelligenceReport.from_dict(result)
            
        return None
        
    async def mark_complete(self, report_id: str) -> bool:
        """Mark a report as complete (user has added their reflection)"""
        if self._weekly_reports_col is None:
            return False
            
        result = self._weekly_reports_col.update_one(
            {"id": report_id},
            {"$set": {
                "is_complete": True,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }}
        )
        
        return result.modified_count > 0
        
    async def get_report(self, report_id: str) -> Optional[WeeklyIntelligenceReport]:
        """Get a specific report by ID"""
        if self._weekly_reports_col is None:
            return None
            
        doc = self._weekly_reports_col.find_one({"id": report_id})
        if doc:
            doc.pop('_id', None)
            return WeeklyIntelligenceReport.from_dict(doc)
            
        return None
        
    async def get_report_by_week(
        self,
        year: int,
        week_number: int
    ) -> Optional[WeeklyIntelligenceReport]:
        """Get report by year and week number"""
        if self._weekly_reports_col is None:
            return None
            
        doc = self._weekly_reports_col.find_one({
            "year": year,
            "week_number": week_number
        })
        
        if doc:
            doc.pop('_id', None)
            return WeeklyIntelligenceReport.from_dict(doc)
            
        return None
        
    async def get_recent_reports(self, limit: int = 12) -> List[WeeklyIntelligenceReport]:
        """Get recent weekly reports"""
        if self._weekly_reports_col is None:
            return []
            
        docs = list(
            self._weekly_reports_col
            .find({})
            .sort([("year", -1), ("week_number", -1)])
            .limit(limit)
        )
        
        return [WeeklyIntelligenceReport.from_dict({k: v for k, v in d.items() if k != '_id'}) for d in docs]
        
    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics"""
        count = 0
        if self._weekly_reports_col is not None:
            count = self._weekly_reports_col.count_documents({})
            
        return {
            "db_connected": self._db is not None,
            "reports_generated": count
        }


# Singleton
_weekly_report_service: Optional[WeeklyReportService] = None


def get_weekly_report_service() -> WeeklyReportService:
    global _weekly_report_service
    if _weekly_report_service is None:
        _weekly_report_service = WeeklyReportService()
    return _weekly_report_service


def init_weekly_report_service(
    db=None,
    calibration_service=None,
    context_performance_service=None,
    confirmation_validator_service=None,
    playbook_performance_service=None,
    edge_decay_service=None
) -> WeeklyReportService:
    service = get_weekly_report_service()
    if db is not None:
        service.set_db(db)
    service.set_services(
        calibration_service=calibration_service,
        context_performance_service=context_performance_service,
        confirmation_validator_service=confirmation_validator_service,
        playbook_performance_service=playbook_performance_service,
        edge_decay_service=edge_decay_service
    )
    return service
