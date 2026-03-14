"""
AI Module Configuration Service

Central configuration for all AI trading modules.
Manages toggles, shadow mode, and module settings.
Persists to MongoDB for state continuity.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


@dataclass
class ModuleSettings:
    """Settings for a single AI module"""
    enabled: bool = False
    shadow_mode: bool = True  # Default to shadow mode (no real trades)
    confidence_threshold: float = 0.6
    last_updated: str = ""
    custom_settings: Dict = field(default_factory=dict)


@dataclass
class AIModuleConfigData:
    """Complete AI module configuration"""
    
    # Module toggles with defaults
    debate_agents: ModuleSettings = field(default_factory=lambda: ModuleSettings(
        enabled=False,
        shadow_mode=True,
        confidence_threshold=0.65,
        custom_settings={
            "debate_rounds": 2,
            "require_consensus": False,
            "min_bull_score": 0.4,
            "min_bear_score": 0.4,
            "bull_margin_to_proceed": 0.15,
            "bear_margin_to_pass": 0.2
        }
    ))
    
    ai_risk_manager: ModuleSettings = field(default_factory=lambda: ModuleSettings(
        enabled=False,
        shadow_mode=True,
        confidence_threshold=0.5,
        custom_settings={
            "max_risk_score": 7,  # Out of 10
            "block_on_high_risk": True,
            "factors": ["position_sizing", "correlation", "volatility", "news_risk", "regime_fit"]
        }
    ))
    
    institutional_flow: ModuleSettings = field(default_factory=lambda: ModuleSettings(
        enabled=False,
        shadow_mode=True,
        confidence_threshold=0.5,
        custom_settings={
            "track_13f": True,
            "volume_anomaly_threshold": 3.0,  # Standard deviations
            "rebalance_alerts": True
        }
    ))
    
    timeseries_ai: ModuleSettings = field(default_factory=lambda: ModuleSettings(
        enabled=False,
        shadow_mode=True,
        confidence_threshold=0.55,
        custom_settings={
            "model_type": "lightgbm",
            "forecast_horizon": 5,  # bars
            "min_probability": 0.55
        }
    ))
    
    # Global settings
    global_shadow_mode: bool = True  # Master switch for shadow mode
    log_all_decisions: bool = True
    
    def to_dict(self) -> Dict:
        return {
            "debate_agents": asdict(self.debate_agents),
            "ai_risk_manager": asdict(self.ai_risk_manager),
            "institutional_flow": asdict(self.institutional_flow),
            "timeseries_ai": asdict(self.timeseries_ai),
            "global_shadow_mode": self.global_shadow_mode,
            "log_all_decisions": self.log_all_decisions
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "AIModuleConfigData":
        config = cls()
        
        if "debate_agents" in data:
            config.debate_agents = ModuleSettings(**data["debate_agents"])
        if "ai_risk_manager" in data:
            config.ai_risk_manager = ModuleSettings(**data["ai_risk_manager"])
        if "institutional_flow" in data:
            config.institutional_flow = ModuleSettings(**data["institutional_flow"])
        if "timeseries_ai" in data:
            config.timeseries_ai = ModuleSettings(**data["timeseries_ai"])
        
        config.global_shadow_mode = data.get("global_shadow_mode", True)
        config.log_all_decisions = data.get("log_all_decisions", True)
        
        return config


class AIModuleConfig:
    """
    Central configuration service for all AI trading modules.
    
    Features:
    - Toggle individual modules on/off
    - Global and per-module shadow mode
    - Persists configuration to MongoDB
    - Provides status for UI display
    """
    
    COLLECTION_NAME = "ai_module_config"
    CONFIG_ID = "main_config"
    
    def __init__(self):
        self._db = None
        self._config = AIModuleConfigData()
        self._loaded = False
        
    def set_db(self, db):
        """Set database connection and load config"""
        self._db = db
        self._load_config()
        
    def _load_config(self):
        """Load configuration from database"""
        if self._db is None:
            logger.warning("AI Module Config: No database connection")
            return
            
        try:
            doc = self._db[self.COLLECTION_NAME].find_one({"_id": self.CONFIG_ID})
            if doc:
                # Remove MongoDB _id before parsing
                doc.pop("_id", None)
                self._config = AIModuleConfigData.from_dict(doc)
                logger.info("AI Module Config: Loaded from database")
            else:
                # Save defaults
                self._save_config()
                logger.info("AI Module Config: Created with defaults")
            self._loaded = True
        except Exception as e:
            logger.error(f"AI Module Config: Failed to load - {e}")
            
    def _save_config(self):
        """Save configuration to database"""
        if self._db is None:
            return False
            
        try:
            self._db[self.COLLECTION_NAME].update_one(
                {"_id": self.CONFIG_ID},
                {"$set": self._config.to_dict()},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"AI Module Config: Failed to save - {e}")
            return False
            
    # Module access methods
    def is_debate_enabled(self) -> bool:
        """Check if Bull/Bear Debate is enabled"""
        return self._config.debate_agents.enabled
        
    def is_risk_manager_enabled(self) -> bool:
        """Check if AI Risk Manager is enabled"""
        return self._config.ai_risk_manager.enabled
        
    def is_institutional_flow_enabled(self) -> bool:
        """Check if Institutional Flow tracking is enabled"""
        return self._config.institutional_flow.enabled
        
    def is_timeseries_enabled(self) -> bool:
        """Check if Time Series AI is enabled"""
        return self._config.timeseries_ai.enabled
        
    def is_shadow_mode(self, module: str = None) -> bool:
        """
        Check if shadow mode is active.
        If global shadow mode is on, all modules are in shadow mode.
        Otherwise, check per-module setting.
        """
        if self._config.global_shadow_mode:
            return True
            
        if module:
            module_settings = getattr(self._config, module, None)
            if module_settings:
                return module_settings.shadow_mode
                
        return True  # Default to shadow mode for safety
        
    def get_module_settings(self, module: str) -> Optional[ModuleSettings]:
        """Get settings for a specific module"""
        return getattr(self._config, module, None)
        
    # Configuration update methods
    def toggle_module(self, module: str, enabled: bool) -> Dict[str, Any]:
        """Enable or disable a module"""
        module_settings = getattr(self._config, module, None)
        if module_settings is None:
            return {"success": False, "error": f"Unknown module: {module}"}
            
        module_settings.enabled = enabled
        module_settings.last_updated = datetime.now(timezone.utc).isoformat()
        
        if self._save_config():
            logger.info(f"AI Module: {module} {'enabled' if enabled else 'disabled'}")
            return {"success": True, "module": module, "enabled": enabled}
        return {"success": False, "error": "Failed to save config"}
        
    def set_shadow_mode(self, module: str = None, shadow_mode: bool = True) -> Dict[str, Any]:
        """
        Set shadow mode for a module or globally.
        If module is None, sets global shadow mode.
        """
        if module is None:
            self._config.global_shadow_mode = shadow_mode
        else:
            module_settings = getattr(self._config, module, None)
            if module_settings is None:
                return {"success": False, "error": f"Unknown module: {module}"}
            module_settings.shadow_mode = shadow_mode
            module_settings.last_updated = datetime.now(timezone.utc).isoformat()
            
        if self._save_config():
            target = module or "global"
            logger.info(f"AI Module: {target} shadow mode = {shadow_mode}")
            return {"success": True, "target": target, "shadow_mode": shadow_mode}
        return {"success": False, "error": "Failed to save config"}
        
    def update_module_settings(self, module: str, settings: Dict) -> Dict[str, Any]:
        """Update custom settings for a module"""
        module_settings = getattr(self._config, module, None)
        if module_settings is None:
            return {"success": False, "error": f"Unknown module: {module}"}
            
        # Update allowed fields
        if "enabled" in settings:
            module_settings.enabled = settings["enabled"]
        if "shadow_mode" in settings:
            module_settings.shadow_mode = settings["shadow_mode"]
        if "confidence_threshold" in settings:
            module_settings.confidence_threshold = settings["confidence_threshold"]
        if "custom_settings" in settings:
            module_settings.custom_settings.update(settings["custom_settings"])
            
        module_settings.last_updated = datetime.now(timezone.utc).isoformat()
        
        if self._save_config():
            return {"success": True, "module": module, "settings": asdict(module_settings)}
        return {"success": False, "error": "Failed to save config"}
        
    def get_full_config(self) -> Dict[str, Any]:
        """Get complete configuration for API/UI"""
        return {
            "modules": {
                "debate_agents": {
                    **asdict(self._config.debate_agents),
                    "name": "Bull/Bear Debate",
                    "description": "AI agents debate trade opportunities from opposing viewpoints"
                },
                "ai_risk_manager": {
                    **asdict(self._config.ai_risk_manager),
                    "name": "AI Risk Manager",
                    "description": "Pre-trade risk assessment with multi-factor analysis"
                },
                "institutional_flow": {
                    **asdict(self._config.institutional_flow),
                    "name": "Institutional Flow",
                    "description": "Track 13F filings, volume anomalies, and rebalance events"
                },
                "timeseries_ai": {
                    **asdict(self._config.timeseries_ai),
                    "name": "Time Series AI",
                    "description": "ML-based price direction forecasting"
                }
            },
            "global_shadow_mode": self._config.global_shadow_mode,
            "log_all_decisions": self._config.log_all_decisions
        }
        
    def get_status_summary(self) -> Dict[str, Any]:
        """Get quick status summary for UI header"""
        return {
            "debate_enabled": self._config.debate_agents.enabled,
            "risk_manager_enabled": self._config.ai_risk_manager.enabled,
            "institutional_enabled": self._config.institutional_flow.enabled,
            "timeseries_enabled": self._config.timeseries_ai.enabled,
            "shadow_mode": self._config.global_shadow_mode,
            "active_modules": sum([
                self._config.debate_agents.enabled,
                self._config.ai_risk_manager.enabled,
                self._config.institutional_flow.enabled,
                self._config.timeseries_ai.enabled
            ])
        }


# Singleton instance
_ai_module_config: Optional[AIModuleConfig] = None


def get_ai_module_config() -> AIModuleConfig:
    """Get singleton instance of AI Module Config"""
    global _ai_module_config
    if _ai_module_config is None:
        _ai_module_config = AIModuleConfig()
    return _ai_module_config


def init_ai_module_config(db=None) -> AIModuleConfig:
    """Initialize AI Module Config with database"""
    config = get_ai_module_config()
    if db is not None:
        config.set_db(db)
    return config
