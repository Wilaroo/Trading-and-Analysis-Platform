"""
Graceful Degradation Service - Handles service failures gracefully

This service provides fallback mechanisms when data sources fail:
- IB Gateway offline → Use Alpaca-only data
- Ollama unavailable → Fall back to GPT-4o or rule-based
- Sector data missing → Skip sector context
- News API fails → Proceed without news sentiment

The goal is to NEVER block trading due to a non-critical service failure.
"""

import logging
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
import asyncio

logger = logging.getLogger(__name__)


class ServiceStatus(str, Enum):
    """Service health status"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ServicePriority(str, Enum):
    """Service criticality for trading"""
    CRITICAL = "critical"      # Trading cannot proceed without this
    IMPORTANT = "important"    # Significantly impacts quality
    OPTIONAL = "optional"      # Nice to have, can skip


@dataclass
class ServiceHealth:
    """Health status of a single service"""
    name: str
    status: ServiceStatus = ServiceStatus.UNKNOWN
    priority: ServicePriority = ServicePriority.OPTIONAL
    last_check: str = ""
    last_success: str = ""
    consecutive_failures: int = 0
    error_message: str = ""
    response_time_ms: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "priority": self.priority.value,
            "last_check": self.last_check,
            "last_success": self.last_success,
            "consecutive_failures": self.consecutive_failures,
            "error_message": self.error_message,
            "response_time_ms": self.response_time_ms
        }


@dataclass
class SystemHealth:
    """Overall system health"""
    overall_status: ServiceStatus = ServiceStatus.HEALTHY
    can_trade: bool = True
    degraded_services: List[str] = field(default_factory=list)
    unavailable_services: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    services: Dict[str, ServiceHealth] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "overall_status": self.overall_status.value,
            "can_trade": self.can_trade,
            "degraded_services": self.degraded_services,
            "unavailable_services": self.unavailable_services,
            "warnings": self.warnings,
            "services": {k: v.to_dict() for k, v in self.services.items()}
        }


class GracefulDegradationService:
    """
    Manages service health and provides fallback mechanisms.
    
    Services are categorized by priority:
    - CRITICAL: Alpaca quotes, MongoDB
    - IMPORTANT: IB Gateway, Ollama, Scanner
    - OPTIONAL: Sector analysis, News sentiment, Pattern detection
    """
    
    # Service configuration with priority and fallbacks
    SERVICE_CONFIG = {
        "alpaca": {
            "priority": ServicePriority.CRITICAL,
            "check_interval_seconds": 30,
            "max_failures_before_degraded": 2,
            "fallback": None  # No fallback - critical
        },
        "mongodb": {
            "priority": ServicePriority.CRITICAL,
            "check_interval_seconds": 60,
            "max_failures_before_degraded": 1,
            "fallback": None
        },
        "ib_gateway": {
            "priority": ServicePriority.IMPORTANT,
            "check_interval_seconds": 30,
            "max_failures_before_degraded": 3,
            "fallback": "alpaca"  # Fall back to Alpaca-only data
        },
        "ollama": {
            "priority": ServicePriority.IMPORTANT,
            "check_interval_seconds": 60,
            "max_failures_before_degraded": 2,
            "fallback": "gpt4o"  # Fall back to GPT-4o via Emergent
        },
        "scanner": {
            "priority": ServicePriority.IMPORTANT,
            "check_interval_seconds": 30,
            "max_failures_before_degraded": 3,
            "fallback": None  # Can't scan without scanner
        },
        "sector_analysis": {
            "priority": ServicePriority.OPTIONAL,
            "check_interval_seconds": 120,
            "max_failures_before_degraded": 5,
            "fallback": "skip"
        },
        "news_sentiment": {
            "priority": ServicePriority.OPTIONAL,
            "check_interval_seconds": 120,
            "max_failures_before_degraded": 5,
            "fallback": "skip"
        },
        "pattern_detection": {
            "priority": ServicePriority.OPTIONAL,
            "check_interval_seconds": 120,
            "max_failures_before_degraded": 5,
            "fallback": "skip"
        },
        "finnhub": {
            "priority": ServicePriority.OPTIONAL,
            "check_interval_seconds": 120,
            "max_failures_before_degraded": 5,
            "fallback": "skip"
        }
    }
    
    def __init__(self):
        self._services: Dict[str, ServiceHealth] = {}
        self._health_checks: Dict[str, Callable] = {}
        self._last_full_check: Optional[str] = None
        
        # Initialize service health tracking
        for service_name, config in self.SERVICE_CONFIG.items():
            self._services[service_name] = ServiceHealth(
                name=service_name,
                priority=config["priority"]
            )
            
    def register_health_check(self, service_name: str, check_function: Callable):
        """Register a health check function for a service"""
        self._health_checks[service_name] = check_function
        
    async def check_service(self, service_name: str) -> ServiceHealth:
        """Check health of a single service"""
        health = self._services.get(service_name)
        if health is None:
            health = ServiceHealth(name=service_name)
            self._services[service_name] = health
            
        health.last_check = datetime.now(timezone.utc).isoformat()
        
        # Get health check function
        check_fn = self._health_checks.get(service_name)
        if check_fn is None:
            health.status = ServiceStatus.UNKNOWN
            return health
            
        try:
            start_time = datetime.now()
            
            # Run health check with timeout
            if asyncio.iscoroutinefunction(check_fn):
                result = await asyncio.wait_for(check_fn(), timeout=10.0)
            else:
                result = check_fn()
                
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
            health.response_time_ms = elapsed_ms
            
            if result:
                health.status = ServiceStatus.HEALTHY
                health.last_success = health.last_check
                health.consecutive_failures = 0
                health.error_message = ""
            else:
                self._handle_failure(health, "Health check returned False")
                
        except asyncio.TimeoutError:
            self._handle_failure(health, "Health check timed out")
        except Exception as e:
            self._handle_failure(health, str(e))
            
        return health
        
    def _handle_failure(self, health: ServiceHealth, error: str):
        """Handle a service failure"""
        health.consecutive_failures += 1
        health.error_message = error
        
        config = self.SERVICE_CONFIG.get(health.name, {})
        max_failures = config.get("max_failures_before_degraded", 3)
        
        if health.consecutive_failures >= max_failures * 2:
            health.status = ServiceStatus.UNAVAILABLE
        elif health.consecutive_failures >= max_failures:
            health.status = ServiceStatus.DEGRADED
        else:
            health.status = ServiceStatus.DEGRADED
            
        logger.warning(f"Service {health.name} failure #{health.consecutive_failures}: {error}")
        
    def record_success(self, service_name: str):
        """Record a successful service interaction"""
        health = self._services.get(service_name)
        if health:
            health.status = ServiceStatus.HEALTHY
            health.last_success = datetime.now(timezone.utc).isoformat()
            health.consecutive_failures = 0
            health.error_message = ""
            
    def record_failure(self, service_name: str, error: str = ""):
        """Record a service failure"""
        health = self._services.get(service_name)
        if health:
            self._handle_failure(health, error)
            
    async def check_all_services(self) -> SystemHealth:
        """Check health of all registered services"""
        system_health = SystemHealth()
        
        for service_name in self._services.keys():
            if service_name in self._health_checks:
                await self.check_service(service_name)
                
        # Compile overall health
        for name, health in self._services.items():
            system_health.services[name] = health
            
            if health.status == ServiceStatus.DEGRADED:
                system_health.degraded_services.append(name)
            elif health.status == ServiceStatus.UNAVAILABLE:
                system_health.unavailable_services.append(name)
                
        # Determine if we can trade
        critical_failures = []
        for name in system_health.unavailable_services:
            config = self.SERVICE_CONFIG.get(name, {})
            if config.get("priority") == ServicePriority.CRITICAL:
                critical_failures.append(name)
                
        if critical_failures:
            system_health.can_trade = False
            system_health.overall_status = ServiceStatus.UNAVAILABLE
            system_health.warnings.append(f"Critical services unavailable: {', '.join(critical_failures)}")
        elif system_health.unavailable_services or system_health.degraded_services:
            system_health.overall_status = ServiceStatus.DEGRADED
            
            # Add warnings for important services
            for name in system_health.unavailable_services + system_health.degraded_services:
                config = self.SERVICE_CONFIG.get(name, {})
                if config.get("priority") == ServicePriority.IMPORTANT:
                    fallback = config.get("fallback")
                    if fallback:
                        system_health.warnings.append(f"{name} unavailable, using {fallback} fallback")
                    else:
                        system_health.warnings.append(f"{name} unavailable, functionality limited")
                        
        self._last_full_check = datetime.now(timezone.utc).isoformat()
        
        return system_health
        
    def get_system_health(self) -> SystemHealth:
        """Get current system health without running checks"""
        system_health = SystemHealth()
        
        for name, health in self._services.items():
            system_health.services[name] = health
            
            if health.status == ServiceStatus.DEGRADED:
                system_health.degraded_services.append(name)
            elif health.status == ServiceStatus.UNAVAILABLE:
                system_health.unavailable_services.append(name)
                
        # Determine overall status
        critical_failures = []
        for name in system_health.unavailable_services:
            config = self.SERVICE_CONFIG.get(name, {})
            if config.get("priority") == ServicePriority.CRITICAL:
                critical_failures.append(name)
                
        system_health.can_trade = len(critical_failures) == 0
        
        if critical_failures:
            system_health.overall_status = ServiceStatus.UNAVAILABLE
        elif system_health.unavailable_services or system_health.degraded_services:
            system_health.overall_status = ServiceStatus.DEGRADED
            
        return system_health
        
    def get_fallback(self, service_name: str) -> Optional[str]:
        """Get the fallback for a service"""
        config = self.SERVICE_CONFIG.get(service_name, {})
        return config.get("fallback")
        
    def should_use_fallback(self, service_name: str) -> bool:
        """Check if we should use fallback for a service"""
        health = self._services.get(service_name)
        if health is None:
            return True
            
        return health.status in (ServiceStatus.DEGRADED, ServiceStatus.UNAVAILABLE)
        
    def get_service_status(self, service_name: str) -> ServiceStatus:
        """Get status of a specific service"""
        health = self._services.get(service_name)
        if health is None:
            return ServiceStatus.UNKNOWN
        return health.status
        
    async def with_fallback(
        self,
        service_name: str,
        primary_fn: Callable,
        fallback_fn: Optional[Callable] = None,
        default_value: Any = None
    ) -> Any:
        """
        Execute a function with automatic fallback.
        
        Usage:
            result = await degradation.with_fallback(
                "ib_gateway",
                primary_fn=lambda: ib_service.get_fundamentals(symbol),
                fallback_fn=lambda: get_cached_fundamentals(symbol),
                default_value={}
            )
        """
        try:
            if asyncio.iscoroutinefunction(primary_fn):
                result = await asyncio.wait_for(primary_fn(), timeout=10.0)
            else:
                result = primary_fn()
                
            self.record_success(service_name)
            return result
            
        except Exception as e:
            self.record_failure(service_name, str(e))
            
            if fallback_fn is not None:
                try:
                    if asyncio.iscoroutinefunction(fallback_fn):
                        return await fallback_fn()
                    else:
                        return fallback_fn()
                except Exception as fe:
                    logger.warning(f"Fallback for {service_name} also failed: {fe}")
                    
            return default_value
            
    def wrap_with_degradation(
        self,
        service_name: str,
        default_value: Any = None
    ) -> Callable:
        """
        Decorator to wrap a function with graceful degradation.
        
        Usage:
            @degradation.wrap_with_degradation("sector_analysis", default_value={})
            async def get_sector_context(symbol: str):
                ...
        """
        def decorator(func: Callable) -> Callable:
            async def wrapper(*args, **kwargs):
                try:
                    if asyncio.iscoroutinefunction(func):
                        result = await asyncio.wait_for(func(*args, **kwargs), timeout=10.0)
                    else:
                        result = func(*args, **kwargs)
                        
                    self.record_success(service_name)
                    return result
                    
                except Exception as e:
                    self.record_failure(service_name, str(e))
                    logger.warning(f"Degradation triggered for {service_name}: {e}")
                    return default_value
                    
            return wrapper
        return decorator


# Singleton instance
_degradation_service: Optional[GracefulDegradationService] = None


def get_degradation_service() -> GracefulDegradationService:
    """Get the singleton degradation service"""
    global _degradation_service
    if _degradation_service is None:
        _degradation_service = GracefulDegradationService()
    return _degradation_service


def init_degradation_service() -> GracefulDegradationService:
    """Initialize the degradation service"""
    return get_degradation_service()
