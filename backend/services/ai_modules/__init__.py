"""
AI Modules Package - Institutional-Grade Trading AI

This package contains advanced AI agents for institutional-style trading:
- Shadow Mode: Paper trading for AI decisions without execution
- Bull/Bear Debate: Multi-agent deliberation before trade decisions  
- AI Risk Manager: Pre-trade risk assessment agent
- Institutional Flow: 13F tracking, volume anomaly detection

All modules are toggleable and support Shadow Mode for safe testing.

Note: Some modules require optional ML dependencies (lightgbm, torch, etc.)
      These will gracefully degrade if not installed.
"""
import logging

logger = logging.getLogger(__name__)

# Core modules (always available)
from .shadow_tracker import ShadowTracker, get_shadow_tracker, init_shadow_tracker
from .debate_agents import DebateAgents, get_debate_agents, init_debate_agents
from .risk_manager_agent import AIRiskManager, get_ai_risk_manager, init_ai_risk_manager
from .module_config import AIModuleConfig, get_ai_module_config, init_ai_module_config
from .institutional_flow import (
    InstitutionalFlowService, 
    get_institutional_flow_service, 
    init_institutional_flow_service
)
from .volume_anomaly import (
    VolumeAnomalyService,
    get_volume_anomaly_service,
    init_volume_anomaly_service
)
from .trade_consultation import (
    AITradeConsultation,
    get_ai_consultation,
    init_ai_consultation
)
from .timeseries_features import (
    TimeSeriesFeatureEngineer,
    FeatureSet,
    get_feature_engineer
)

# ML-dependent modules (optional - graceful degradation if not installed)
ML_AVAILABLE = False
try:
    from .timeseries_gbm import (
        TimeSeriesGBM,
        Prediction,
        ModelMetrics,
        get_timeseries_model,
        init_timeseries_model
    )
    from .timeseries_service import (
        TimeSeriesAIService,
        get_timeseries_ai,
        init_timeseries_ai
    )
    ML_AVAILABLE = True
    logger.info("ML modules loaded successfully (lightgbm available)")
except ImportError as e:
    logger.warning(f"ML modules not available - missing dependency: {e}")
    logger.warning("Time-series predictions will be disabled. Install lightgbm for full functionality.")
    
    # Create placeholder classes for graceful degradation
    class TimeSeriesGBM:
        """Placeholder when lightgbm not available"""
        def __init__(self, *args, **kwargs):
            pass
        async def predict(self, *args, **kwargs):
            return None
        async def train(self, *args, **kwargs):
            return {"success": False, "error": "lightgbm not installed"}
    
    class Prediction:
        """Placeholder prediction dataclass"""
        symbol: str = ""
        direction: str = "neutral"
        probability_up: float = 0.5
        probability_down: float = 0.5
        confidence: float = 0.0
    
    class ModelMetrics:
        """Placeholder metrics dataclass"""
        pass
    
    class TimeSeriesAIService:
        """Placeholder when ML not available"""
        def __init__(self, *args, **kwargs):
            pass
        async def get_forecast(self, *args, **kwargs):
            return {"usable": False, "error": "ML not available"}
        async def train_model(self, *args, **kwargs):
            return {"success": False, "error": "lightgbm not installed"}
    
    def get_timeseries_model():
        return None
    
    def init_timeseries_model(*args, **kwargs):
        return None
    
    def get_timeseries_ai():
        return TimeSeriesAIService()
    
    def init_timeseries_ai(*args, **kwargs):
        return TimeSeriesAIService()

__all__ = [
    'ML_AVAILABLE',
    'ShadowTracker',
    'get_shadow_tracker',
    'init_shadow_tracker',
    'DebateAgents', 
    'get_debate_agents',
    'init_debate_agents',
    'AIRiskManager',
    'get_ai_risk_manager',
    'init_ai_risk_manager',
    'AIModuleConfig',
    'get_ai_module_config',
    'init_ai_module_config',
    'InstitutionalFlowService',
    'get_institutional_flow_service',
    'init_institutional_flow_service',
    'VolumeAnomalyService',
    'get_volume_anomaly_service',
    'init_volume_anomaly_service',
    'AITradeConsultation',
    'get_ai_consultation',
    'init_ai_consultation',
    'TimeSeriesFeatureEngineer',
    'FeatureSet',
    'get_feature_engineer',
    'TimeSeriesGBM',
    'Prediction',
    'ModelMetrics',
    'get_timeseries_model',
    'init_timeseries_model',
    'TimeSeriesAIService',
    'get_timeseries_ai',
    'init_timeseries_ai'
]
