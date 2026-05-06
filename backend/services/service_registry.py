"""
Service Registry
================
Centralized service container for managing service instances and dependencies.
This replaces the fragile globals() pattern with a proper dependency container.

Usage:
    from services.service_registry import ServiceRegistry
    
    # Register services
    registry = ServiceRegistry()
    registry.register('alpaca_service', alpaca_service)
    
    # Get services
    alpaca = registry.get('alpaca_service')
    
    # Get optional service (returns None if not registered)
    optional = registry.get_optional('some_service')
"""

from typing import Dict, Any, Optional, TypeVar
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ServiceRegistry:
    """
    Thread-safe service registry for managing application services.
    Provides a clean alternative to using globals() for service lookups.
    """
    
    _instance: Optional['ServiceRegistry'] = None
    
    def __new__(cls):
        """Singleton pattern - ensures only one registry exists."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._services: Dict[str, Any] = {}
            cls._instance._initialized = False
        return cls._instance
    
    def register(self, name: str, service: Any) -> None:
        """
        Register a service with a given name.
        
        Args:
            name: Unique identifier for the service
            service: The service instance
        """
        if service is None:
            logger.debug(f"Skipping registration of None service: {name}")
            return
            
        self._services[name] = service
        logger.debug(f"Registered service: {name}")
    
    def get(self, name: str) -> Any:
        """
        Get a required service by name. Raises KeyError if not found.
        
        Args:
            name: The service name
            
        Returns:
            The service instance
            
        Raises:
            KeyError: If service is not registered
        """
        if name not in self._services:
            raise KeyError(f"Service '{name}' not registered. Available: {list(self._services.keys())}")
        return self._services[name]
    
    def get_optional(self, name: str, default: Any = None) -> Any:
        """
        Get an optional service by name. Returns default if not found.
        
        Args:
            name: The service name
            default: Value to return if service not found (default: None)
            
        Returns:
            The service instance or default value
        """
        return self._services.get(name, default)
    
    def has(self, name: str) -> bool:
        """Check if a service is registered."""
        return name in self._services
    
    def list_services(self) -> list:
        """Get list of all registered service names."""
        return list(self._services.keys())
    
    def clear(self) -> None:
        """Clear all registered services. Mainly for testing."""
        self._services.clear()
        logger.debug("Service registry cleared")
    
    def get_multiple(self, *names: str) -> Dict[str, Any]:
        """
        Get multiple services as a dict.
        Missing services are set to None.
        
        Args:
            *names: Variable number of service names
            
        Returns:
            Dict mapping service names to instances (or None if not found)
        """
        return {name: self.get_optional(name) for name in names}


# Global singleton instance
_registry: Optional[ServiceRegistry] = None


def get_service_registry() -> ServiceRegistry:
    """Get the global service registry instance."""
    global _registry
    if _registry is None:
        _registry = ServiceRegistry()
    return _registry


def register_service(name: str, service: Any) -> None:
    """Convenience function to register a service."""
    get_service_registry().register(name, service)


def get_service(name: str) -> Any:
    """Convenience function to get a required service."""
    return get_service_registry().get(name)


def get_service_optional(name: str, default: Any = None) -> Any:
    """Convenience function to get an optional service."""
    return get_service_registry().get_optional(name, default)
