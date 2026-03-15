"""
AI Modules Package - Institutional-Grade Trading AI

This package contains advanced AI agents for institutional-style trading:
- Shadow Mode: Paper trading for AI decisions without execution
- Bull/Bear Debate: Multi-agent deliberation before trade decisions  
- AI Risk Manager: Pre-trade risk assessment agent
- Institutional Flow: 13F tracking, volume anomaly detection

All modules are toggleable and support Shadow Mode for safe testing.
"""

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

__all__ = [
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
