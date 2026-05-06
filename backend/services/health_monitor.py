"""
Health Monitor Service - System Health Dashboard

Monitors the health and status of all trading system components:
- Service availability (Alpaca, IB Gateway, Ollama, etc.)
- Data quality (freshness, completeness)
- Model performance (accuracy, drift)
- Resource usage (API limits, quotas)

Provides:
1. Real-time health dashboard data
2. Alerts when services degrade
3. Recommendations for resolution
"""

import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Health status levels"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ComponentCategory(str, Enum):
    """Categories of system components"""
    DATA_FEED = "data_feed"
    AI_SERVICE = "ai_service"
    BROKER = "broker"
    DATABASE = "database"
    ANALYTICS = "analytics"
    RISK = "risk"


@dataclass
class ComponentHealth:
    """Health status of a single component"""
    name: str
    category: ComponentCategory
    status: HealthStatus = HealthStatus.UNKNOWN
    last_check: str = ""
    last_success: str = ""
    response_time_ms: float = 0.0
    error_count: int = 0
    error_message: str = ""
    
    # Component-specific metrics
    metrics: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "category": self.category.value,
            "status": self.status.value,
            "last_check": self.last_check,
            "last_success": self.last_success,
            "response_time_ms": round(self.response_time_ms, 1),
            "error_count": self.error_count,
            "error_message": self.error_message,
            "metrics": self.metrics
        }


@dataclass
class DataQualityMetric:
    """Metrics for data quality assessment"""
    name: str
    freshness_seconds: float = 0.0
    completeness_pct: float = 100.0
    accuracy_score: float = 1.0
    last_update: str = ""
    issues: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "freshness_seconds": round(self.freshness_seconds, 1),
            "completeness_pct": round(self.completeness_pct, 1),
            "accuracy_score": round(self.accuracy_score, 2),
            "last_update": self.last_update,
            "issues": self.issues
        }


@dataclass
class SystemHealthReport:
    """Complete system health report"""
    overall_status: HealthStatus = HealthStatus.HEALTHY
    can_trade: bool = True
    components: Dict[str, ComponentHealth] = field(default_factory=dict)
    data_quality: Dict[str, DataQualityMetric] = field(default_factory=dict)
    alerts: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    generated_at: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "overall_status": self.overall_status.value,
            "can_trade": self.can_trade,
            "components": {k: v.to_dict() for k, v in self.components.items()},
            "data_quality": {k: v.to_dict() for k, v in self.data_quality.items()},
            "alerts": self.alerts,
            "recommendations": self.recommendations,
            "generated_at": self.generated_at
        }


class HealthMonitorService:
    """
    Monitors system health and provides dashboard data.
    
    Components monitored:
    - Alpaca (quotes, streaming)
    - IB Gateway (L2, fundamentals)
    - MongoDB (database)
    - Ollama (local AI)
    - Finnhub (earnings, news)
    - Scanner (alerts)
    - TQS Engine (scoring)
    - Circuit Breakers (risk)
    """
    
    # Component configurations
    COMPONENT_CONFIGS = {
        "alpaca": {
            "category": ComponentCategory.DATA_FEED,
            "critical": True,
            "check_interval": 30
        },
        "alpaca_stream": {
            "category": ComponentCategory.DATA_FEED,
            "critical": True,
            "check_interval": 10
        },
        "ib_gateway": {
            "category": ComponentCategory.DATA_FEED,
            "critical": False,
            "check_interval": 60
        },
        "mongodb": {
            "category": ComponentCategory.DATABASE,
            "critical": True,
            "check_interval": 60
        },
        "ollama": {
            "category": ComponentCategory.AI_SERVICE,
            "critical": False,
            "check_interval": 120
        },
        "finnhub": {
            "category": ComponentCategory.DATA_FEED,
            "critical": False,
            "check_interval": 300
        },
        "scanner": {
            "category": ComponentCategory.ANALYTICS,
            "critical": True,
            "check_interval": 30
        },
        "tqs_engine": {
            "category": ComponentCategory.ANALYTICS,
            "critical": False,
            "check_interval": 60
        },
        "circuit_breakers": {
            "category": ComponentCategory.RISK,
            "critical": True,
            "check_interval": 10
        },
        "learning_loop": {
            "category": ComponentCategory.ANALYTICS,
            "critical": False,
            "check_interval": 60
        }
    }
    
    def __init__(self):
        self._components: Dict[str, ComponentHealth] = {}
        self._data_quality: Dict[str, DataQualityMetric] = {}
        self._last_full_check: Optional[datetime] = None
        
        # Service references
        self._alpaca_service = None
        self._ib_service = None
        self._scanner = None
        self._tqs_engine = None
        self._circuit_breaker = None
        self._learning_loop = None
        self._db = None
        
        # Initialize component health tracking
        for name, config in self.COMPONENT_CONFIGS.items():
            self._components[name] = ComponentHealth(
                name=name,
                category=config["category"]
            )
            
        # Initialize data quality tracking
        for data_type in ["quotes", "level2", "fundamentals", "technicals", "learning_stats"]:
            self._data_quality[data_type] = DataQualityMetric(name=data_type)
            
    def set_services(
        self,
        alpaca_service=None,
        ib_service=None,
        scanner=None,
        tqs_engine=None,
        circuit_breaker=None,
        learning_loop=None,
        db=None
    ):
        """Wire up dependencies"""
        self._alpaca_service = alpaca_service
        self._ib_service = ib_service
        self._scanner = scanner
        self._tqs_engine = tqs_engine
        self._circuit_breaker = circuit_breaker
        self._learning_loop = learning_loop
        self._db = db
        
    def record_success(self, component: str, response_time_ms: float = 0.0, metrics: Dict = None):
        """Record a successful component interaction"""
        if component in self._components:
            comp = self._components[component]
            comp.status = HealthStatus.HEALTHY
            comp.last_check = datetime.now(timezone.utc).isoformat()
            comp.last_success = comp.last_check
            comp.response_time_ms = response_time_ms
            comp.error_count = 0
            comp.error_message = ""
            if metrics:
                comp.metrics.update(metrics)
                
    def record_failure(self, component: str, error: str = ""):
        """Record a component failure"""
        if component in self._components:
            comp = self._components[component]
            comp.last_check = datetime.now(timezone.utc).isoformat()
            comp.error_count += 1
            comp.error_message = error
            
            if comp.error_count >= 3:
                comp.status = HealthStatus.UNHEALTHY
            elif comp.error_count >= 1:
                comp.status = HealthStatus.DEGRADED
                
            logger.warning(f"Health: {component} failure #{comp.error_count}: {error}")
            
    def update_data_quality(
        self,
        data_type: str,
        freshness_seconds: float,
        completeness_pct: float = 100.0,
        accuracy_score: float = 1.0,
        issues: List[str] = None
    ):
        """Update data quality metrics"""
        if data_type in self._data_quality:
            dq = self._data_quality[data_type]
            dq.freshness_seconds = freshness_seconds
            dq.completeness_pct = completeness_pct
            dq.accuracy_score = accuracy_score
            dq.last_update = datetime.now(timezone.utc).isoformat()
            if issues:
                dq.issues = issues
                
    async def check_component(self, component: str) -> ComponentHealth:
        """Check health of a specific component"""
        comp = self._components.get(component)
        if comp is None:
            return ComponentHealth(name=component, category=ComponentCategory.DATA_FEED)
            
        start_time = datetime.now()
        
        try:
            if component == "alpaca":
                await self._check_alpaca(comp)
            elif component == "alpaca_stream":
                self._check_alpaca_stream(comp)
            elif component == "ib_gateway":
                self._check_ib_gateway(comp)
            elif component == "mongodb":
                self._check_mongodb(comp)
            elif component == "scanner":
                self._check_scanner(comp)
            elif component == "tqs_engine":
                await self._check_tqs_engine(comp)
            elif component == "circuit_breakers":
                self._check_circuit_breakers(comp)
            elif component == "learning_loop":
                await self._check_learning_loop(comp)
            elif component == "ollama":
                await self._check_ollama(comp)
            elif component == "finnhub":
                self._check_finnhub(comp)
                
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
            comp.response_time_ms = elapsed_ms
            comp.last_check = datetime.now(timezone.utc).isoformat()
            
        except Exception as e:
            self.record_failure(component, str(e))
            
        return comp
        
    async def _check_alpaca(self, comp: ComponentHealth):
        """Check Alpaca API health"""
        if self._alpaca_service is None:
            comp.status = HealthStatus.UNKNOWN
            return
            
        try:
            # Try to get a quote
            quotes = await self._alpaca_service.get_quotes_batch(["SPY"])
            if quotes and "SPY" in quotes:
                comp.status = HealthStatus.HEALTHY
                comp.last_success = datetime.now(timezone.utc).isoformat()
                comp.metrics["spy_price"] = quotes["SPY"].get("price", 0)
            else:
                comp.status = HealthStatus.DEGRADED
                comp.error_message = "No quote data returned"
        except Exception as e:
            self.record_failure("alpaca", str(e))
            
    def _check_alpaca_stream(self, comp: ComponentHealth):
        """Check Alpaca streaming health"""
        if self._alpaca_service is None:
            comp.status = HealthStatus.UNKNOWN
            return
            
        # Check if streaming is active
        is_streaming = getattr(self._alpaca_service, '_streaming_active', False)
        last_message = getattr(self._alpaca_service, '_last_stream_message', None)
        
        if is_streaming:
            comp.status = HealthStatus.HEALTHY
            comp.last_success = datetime.now(timezone.utc).isoformat()
            if last_message:
                age = (datetime.now(timezone.utc) - last_message).total_seconds()
                comp.metrics["last_message_age_seconds"] = age
                if age > 60:
                    comp.status = HealthStatus.DEGRADED
                    comp.error_message = f"No stream message in {age:.0f}s"
        else:
            comp.status = HealthStatus.DEGRADED
            comp.error_message = "Streaming not active"
            
    def _check_ib_gateway(self, comp: ComponentHealth):
        """Check IB Gateway health"""
        if self._ib_service is None:
            comp.status = HealthStatus.UNKNOWN
            return
            
        is_connected = getattr(self._ib_service, '_connected', False)
        
        if is_connected:
            comp.status = HealthStatus.HEALTHY
            comp.last_success = datetime.now(timezone.utc).isoformat()
            comp.metrics["has_level2"] = True
        else:
            comp.status = HealthStatus.UNHEALTHY
            comp.error_message = "IB Gateway not connected"
            
    def _check_mongodb(self, comp: ComponentHealth):
        """Check MongoDB health"""
        if self._db is None:
            comp.status = HealthStatus.UNKNOWN
            return
            
        try:
            # Simple ping
            self._db.command("ping")
            comp.status = HealthStatus.HEALTHY
            comp.last_success = datetime.now(timezone.utc).isoformat()
            
            # Get collection stats
            collections = self._db.list_collection_names()
            comp.metrics["collection_count"] = len(collections)
        except Exception as e:
            self.record_failure("mongodb", str(e))
            
    def _check_scanner(self, comp: ComponentHealth):
        """Check scanner health"""
        if self._scanner is None:
            comp.status = HealthStatus.UNKNOWN
            return
            
        is_running = getattr(self._scanner, '_is_running', False)
        alerts_count = len(getattr(self._scanner, '_live_alerts', {}))
        
        if is_running:
            comp.status = HealthStatus.HEALTHY
            comp.last_success = datetime.now(timezone.utc).isoformat()
            comp.metrics["active_alerts"] = alerts_count
        else:
            comp.status = HealthStatus.DEGRADED
            comp.error_message = "Scanner not running"
            
    async def _check_tqs_engine(self, comp: ComponentHealth):
        """Check TQS engine health"""
        if self._tqs_engine is None:
            comp.status = HealthStatus.UNKNOWN
            return
            
        try:
            # Try a simple score calculation
            result = await self._tqs_engine.calculate_tqs(
                symbol="SPY",
                setup_type="test",
                direction="long"
            )
            
            if result and result.score >= 0:
                comp.status = HealthStatus.HEALTHY
                comp.last_success = datetime.now(timezone.utc).isoformat()
                comp.metrics["test_score"] = result.score
            else:
                comp.status = HealthStatus.DEGRADED
        except Exception as e:
            self.record_failure("tqs_engine", str(e))
            
    def _check_circuit_breakers(self, comp: ComponentHealth):
        """Check circuit breaker health"""
        if self._circuit_breaker is None:
            comp.status = HealthStatus.UNKNOWN
            return
            
        status = self._circuit_breaker.get_status()
        
        comp.status = HealthStatus.HEALTHY
        comp.last_success = datetime.now(timezone.utc).isoformat()
        comp.metrics["any_triggered"] = status.get("any_triggered", False)
        comp.metrics["daily_pnl"] = status.get("trading_metrics", {}).get("daily_pnl", 0)
        
        if status.get("any_triggered"):
            comp.status = HealthStatus.DEGRADED
            comp.error_message = "Circuit breaker(s) triggered"
            
    async def _check_learning_loop(self, comp: ComponentHealth):
        """Check learning loop health"""
        if self._learning_loop is None:
            comp.status = HealthStatus.UNKNOWN
            return
            
        try:
            profile = await self._learning_loop.get_trader_profile()
            
            comp.status = HealthStatus.HEALTHY
            comp.last_success = datetime.now(timezone.utc).isoformat()
            comp.metrics["total_trades"] = profile.total_trades
            comp.metrics["is_tilted"] = profile.current_tilt_state.is_tilted
        except Exception as e:
            self.record_failure("learning_loop", str(e))
            
    async def _check_ollama(self, comp: ComponentHealth):
        """Check Ollama health"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get("http://localhost:11434/api/tags")
                if response.status_code == 200:
                    comp.status = HealthStatus.HEALTHY
                    comp.last_success = datetime.now(timezone.utc).isoformat()
                    data = response.json()
                    comp.metrics["models_loaded"] = len(data.get("models", []))
                else:
                    comp.status = HealthStatus.DEGRADED
        except Exception:
            comp.status = HealthStatus.UNHEALTHY
            comp.error_message = "Ollama not reachable"
            
    def _check_finnhub(self, comp: ComponentHealth):
        """Check Finnhub health (based on recent data)"""
        # Check if we have recent earnings data
        if self._db is not None:
            try:
                earnings_col = self._db.get("earnings_calendar")
                if earnings_col:
                    recent = earnings_col.find_one(
                        sort=[("fetched_at", -1)]
                    )
                    if recent:
                        fetched = datetime.fromisoformat(recent.get("fetched_at", "").replace("Z", "+00:00"))
                        age = (datetime.now(timezone.utc) - fetched).total_seconds()
                        
                        if age < 3600:  # Less than 1 hour old
                            comp.status = HealthStatus.HEALTHY
                        elif age < 86400:  # Less than 1 day old
                            comp.status = HealthStatus.DEGRADED
                        else:
                            comp.status = HealthStatus.UNHEALTHY
                            
                        comp.metrics["data_age_hours"] = age / 3600
                        comp.last_success = recent.get("fetched_at", "")
            except Exception:
                pass
                
    async def generate_report(self) -> SystemHealthReport:
        """Generate a complete health report"""
        report = SystemHealthReport()
        report.generated_at = datetime.now(timezone.utc).isoformat()
        
        # Check all components
        for name in self._components.keys():
            await self.check_component(name)
            
        report.components = dict(self._components)
        report.data_quality = dict(self._data_quality)
        
        # Determine overall status
        critical_failures = []
        degraded = []
        
        for name, comp in self._components.items():
            config = self.COMPONENT_CONFIGS.get(name, {})
            
            if comp.status == HealthStatus.UNHEALTHY:
                if config.get("critical", False):
                    critical_failures.append(name)
                    report.alerts.append(f"CRITICAL: {name} is unhealthy - {comp.error_message}")
                else:
                    degraded.append(name)
                    report.alerts.append(f"WARNING: {name} is unhealthy - {comp.error_message}")
            elif comp.status == HealthStatus.DEGRADED:
                degraded.append(name)
                report.alerts.append(f"NOTICE: {name} is degraded - {comp.error_message}")
                
        # Set overall status
        if critical_failures:
            report.overall_status = HealthStatus.UNHEALTHY
            report.can_trade = False
            report.recommendations.append("Resolve critical issues before trading")
        elif degraded:
            report.overall_status = HealthStatus.DEGRADED
            report.recommendations.append("System operational but some features may be limited")
        else:
            report.overall_status = HealthStatus.HEALTHY
            
        # Add recommendations based on specific issues
        if "ib_gateway" in degraded or self._components.get("ib_gateway", ComponentHealth("ib_gateway", ComponentCategory.DATA_FEED)).status != HealthStatus.HEALTHY:
            report.recommendations.append("Connect IB Gateway for Level 2 and fundamental data")
            
        if "ollama" in degraded:
            report.recommendations.append("Start Ollama for local AI features")
            
        self._last_full_check = datetime.now(timezone.utc)
        
        return report
        
    def get_quick_status(self) -> Dict[str, Any]:
        """Get a quick status summary"""
        healthy = sum(1 for c in self._components.values() if c.status == HealthStatus.HEALTHY)
        degraded = sum(1 for c in self._components.values() if c.status == HealthStatus.DEGRADED)
        unhealthy = sum(1 for c in self._components.values() if c.status == HealthStatus.UNHEALTHY)
        
        critical_healthy = all(
            self._components.get(name, ComponentHealth(name, ComponentCategory.DATA_FEED)).status == HealthStatus.HEALTHY
            for name, config in self.COMPONENT_CONFIGS.items()
            if config.get("critical", False)
        )
        
        return {
            "can_trade": critical_healthy,
            "healthy_count": healthy,
            "degraded_count": degraded,
            "unhealthy_count": unhealthy,
            "total_components": len(self._components),
            "last_check": self._last_full_check.isoformat() if self._last_full_check else None
        }


# Singleton
_health_monitor_service: Optional[HealthMonitorService] = None


def get_health_monitor_service() -> HealthMonitorService:
    global _health_monitor_service
    if _health_monitor_service is None:
        _health_monitor_service = HealthMonitorService()
    return _health_monitor_service


def init_health_monitor_service(
    alpaca_service=None,
    ib_service=None,
    scanner=None,
    tqs_engine=None,
    circuit_breaker=None,
    learning_loop=None,
    db=None
) -> HealthMonitorService:
    service = get_health_monitor_service()
    service.set_services(
        alpaca_service=alpaca_service,
        ib_service=ib_service,
        scanner=scanner,
        tqs_engine=tqs_engine,
        circuit_breaker=circuit_breaker,
        learning_loop=learning_loop,
        db=db
    )
    return service
