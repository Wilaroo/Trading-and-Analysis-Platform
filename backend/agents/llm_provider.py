"""
LLM Provider Abstraction Layer
Allows swapping LLM providers without changing agent code.
Supports: Ollama (local/cloud), OpenAI, Anthropic, Groq, Local LLaMA
"""
import os
import logging
import asyncio
import httpx
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class LLMProviderType(str, Enum):
    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GROQ = "groq"
    LOCAL = "local"


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider"""
    content: str
    model: str
    provider: str
    tokens_used: Optional[int] = None
    latency_ms: Optional[float] = None
    success: bool = True
    error: Optional[str] = None


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    @abstractmethod
    async def generate(self, prompt: str, model: str = None, 
                      system_prompt: str = None, temperature: float = 0.7,
                      max_tokens: int = 1000) -> LLMResponse:
        """Generate a response from the LLM"""
        pass
    
    @abstractmethod
    def get_available_models(self) -> List[str]:
        """Get list of available models for this provider"""
        pass


class OllamaProvider(BaseLLMProvider):
    """Ollama provider - uses WebSocket proxy or direct connection"""
    
    def __init__(self):
        # Direct Ollama URL from environment
        self.ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
        # Primary model: GPT-OSS cloud, Fallback: llama3.5 8b local
        self.default_model = os.environ.get("OLLAMA_MODEL", "gpt-oss:120b-cloud")
        self.fallback_model = "llama3:8b"  # Local fallback
        # Track if we should use the proxy
        self._use_proxy = True
    
    async def generate(self, prompt: str, model: str = None,
                      system_prompt: str = None, temperature: float = 0.7,
                      max_tokens: int = 1000) -> LLMResponse:
        """Generate using Ollama - tries proxy first, then direct URL, then fallback model"""
        import time
        start = time.time()
        
        model = model or self.default_model
        
        # Try 1: Use the WebSocket proxy (if local client is connected)
        if self._use_proxy:
            response = await self._call_via_proxy(prompt, model, system_prompt, temperature, max_tokens)
            if response.success:
                return response
            logger.warning(f"Proxy method failed: {response.error}")
        
        # Try 2: Direct Ollama API call with primary model
        response = await self._call_ollama_direct(prompt, model, system_prompt, temperature, max_tokens)
        if response.success:
            return response
        
        # Try 3: Fallback model (if not already using it)
        if model != self.fallback_model:
            logger.warning(f"Primary model {model} failed, trying fallback {self.fallback_model}")
            response = await self._call_ollama_direct(prompt, self.fallback_model, system_prompt, temperature, max_tokens)
            if response.success:
                response = LLMResponse(
                    content=response.content,
                    model=f"{self.fallback_model} (fallback)",
                    provider="ollama",
                    latency_ms=(time.time() - start) * 1000,
                    success=True
                )
                return response
        
        # All methods failed
        return LLMResponse(
            content="",
            model=model,
            provider="ollama",
            success=False,
            error="Ollama not available. Local IB pusher may be offline.",
            latency_ms=(time.time() - start) * 1000
        )
    
    async def _call_via_proxy(self, prompt: str, model: str, system_prompt: str = None,
                             temperature: float = 0.7, max_tokens: int = 1000) -> LLMResponse:
        """Call Ollama through the proxy (HTTP or WebSocket)"""
        import time
        start = time.time()
        
        # Try HTTP proxy first (more reliable)
        try:
            from server import is_http_ollama_proxy_connected, call_ollama_via_http_proxy
            
            if is_http_ollama_proxy_connected():
                logger.info(f"🔌 Agent using HTTP Ollama proxy for model: {model}")
                
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})
                
                result = await call_ollama_via_http_proxy(
                    model=model,
                    messages=messages,
                    options={"temperature": temperature, "num_predict": max_tokens},
                    timeout=120.0
                )
                
                if result.get("success"):
                    # Handle nested response structure from proxy
                    response_data = result.get("response", {})
                    if isinstance(response_data, dict) and "response" in response_data:
                        # Nested structure: {response: {response: {message: {content: ...}}}}
                        inner_response = response_data.get("response", {})
                        content = inner_response.get("message", {}).get("content", "")
                    else:
                        # Flat structure: {response: {message: {content: ...}}}
                        content = response_data.get("message", {}).get("content", "")
                    
                    if content:
                        return LLMResponse(
                            content=content,
                            model=model,
                            provider="ollama",
                            latency_ms=(time.time() - start) * 1000,
                            success=True
                        )
                    else:
                        # Check for error in response (403 from cloud model)
                        error = response_data.get("error") or response_data.get("response", {}).get("error", "")
                        if error:
                            logger.warning(f"Model returned error: {error}")
                
                # Get error message
                error = result.get("error", "HTTP proxy call failed")
                if not error and result.get("response", {}).get("error"):
                    error = result.get("response", {}).get("error")
                logger.warning(f"HTTP proxy failed: {error}")
                
                # Try fallback model if primary failed (cloud models or any failure)
                if model != self.fallback_model:
                    logger.info(f"🔄 Trying fallback model: {self.fallback_model}")
                    fallback_result = await call_ollama_via_http_proxy(
                        model=self.fallback_model,
                        messages=messages,
                        options={"temperature": temperature, "num_predict": max_tokens},
                        timeout=60.0
                    )
                    if fallback_result.get("success"):
                        # Handle nested response for fallback too
                        fb_response = fallback_result.get("response", {})
                        if isinstance(fb_response, dict) and "response" in fb_response:
                            inner = fb_response.get("response", {})
                            content = inner.get("message", {}).get("content", "")
                        else:
                            content = fb_response.get("message", {}).get("content", "")
                        
                        if content:
                            return LLMResponse(
                                content=content,
                                model=f"{self.fallback_model} (fallback)",
                                provider="ollama",
                                latency_ms=(time.time() - start) * 1000,
                                success=True
                            )
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"HTTP proxy error: {e}")
        
        # Fallback to WebSocket proxy
        try:
            from services.ollama_proxy_manager import ollama_proxy_manager
            
            if not ollama_proxy_manager.is_connected:
                return LLMResponse(
                    content="",
                    model=model,
                    provider="ollama",
                    success=False,
                    error="No proxy connected"
                )
            
            # Format messages
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            result = await ollama_proxy_manager.chat(
                model=model,
                messages=messages,
                options={"temperature": temperature, "num_predict": max_tokens}
            )
            
            if result.get("success"):
                return LLMResponse(
                    content=result.get("content", ""),
                    model=model,
                    provider="ollama",
                    latency_ms=(time.time() - start) * 1000,
                    success=True
                )
            else:
                return LLMResponse(
                    content="",
                    model=model,
                    provider="ollama",
                    success=False,
                    error=result.get("error", "Proxy call failed")
                )
                
        except Exception as e:
            logger.error(f"WebSocket proxy call error: {e}")
            return LLMResponse(
                content="",
                model=model,
                provider="ollama",
                success=False,
                error=str(e)
            )
    
    async def _call_ollama_direct(self, prompt: str, model: str, system_prompt: str = None,
                                  temperature: float = 0.7, max_tokens: int = 1000) -> LLMResponse:
        """Direct Ollama API call (fallback when proxy not available)"""
        import time
        start = time.time()
        
        try:
            # Direct Ollama API call with shorter timeout for quick failure
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Format messages
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})
                
                response = await client.post(
                    f"{self.ollama_url}/api/chat",
                    headers={"ngrok-skip-browser-warning": "true"},
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": False,
                        "options": {
                            "temperature": temperature,
                            "num_predict": max_tokens
                        }
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    content = data.get("message", {}).get("content", "")
                    
                    return LLMResponse(
                        content=content,
                        model=model,
                        provider="ollama",
                        latency_ms=(time.time() - start) * 1000,
                        success=True
                    )
                else:
                    return LLMResponse(
                        content="",
                        model=model,
                        provider="ollama",
                        success=False,
                        error=f"Ollama returned {response.status_code}"
                    )
                    
        except Exception as e:
            logger.error(f"Ollama direct call error: {e}")
            return LLMResponse(
                content="",
                model=model,
                provider="ollama",
                success=False,
                error=str(e)
            )
    
    def get_available_models(self) -> List[str]:
        return ["gpt-oss:120b-cloud", "llama3:8b", "mistral:7b"]


class OpenAIProvider(BaseLLMProvider):
    """OpenAI provider - for GPT-4, etc."""
    
    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.default_model = "gpt-4"
    
    async def generate(self, prompt: str, model: str = None,
                      system_prompt: str = None, temperature: float = 0.7,
                      max_tokens: int = 1000) -> LLMResponse:
        import time
        start = time.time()
        
        model = model or self.default_model
        
        if not self.api_key:
            return LLMResponse(
                content="",
                model=model,
                provider="openai",
                success=False,
                error="OpenAI API key not configured"
            )
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})
                
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    tokens = data.get("usage", {}).get("total_tokens")
                    
                    return LLMResponse(
                        content=content,
                        model=model,
                        provider="openai",
                        tokens_used=tokens,
                        latency_ms=(time.time() - start) * 1000,
                        success=True
                    )
                else:
                    return LLMResponse(
                        content="",
                        model=model,
                        provider="openai",
                        success=False,
                        error=f"OpenAI returned {response.status_code}: {response.text}"
                    )
                    
        except Exception as e:
            logger.error(f"OpenAI generate error: {e}")
            return LLMResponse(
                content="",
                model=model,
                provider="openai",
                success=False,
                error=str(e)
            )
    
    def get_available_models(self) -> List[str]:
        return ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"]


class AnthropicProvider(BaseLLMProvider):
    """Anthropic provider - for Claude models"""
    
    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.default_model = "claude-3-sonnet-20240229"
    
    async def generate(self, prompt: str, model: str = None,
                      system_prompt: str = None, temperature: float = 0.7,
                      max_tokens: int = 1000) -> LLMResponse:
        import time
        start = time.time()
        
        model = model or self.default_model
        
        if not self.api_key:
            return LLMResponse(
                content="",
                model=model,
                provider="anthropic",
                success=False,
                error="Anthropic API key not configured"
            )
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                request_body = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}]
                }
                if system_prompt:
                    request_body["system"] = system_prompt
                
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01"
                    },
                    json=request_body
                )
                
                if response.status_code == 200:
                    data = response.json()
                    content = data["content"][0]["text"]
                    tokens = data.get("usage", {}).get("input_tokens", 0) + \
                             data.get("usage", {}).get("output_tokens", 0)
                    
                    return LLMResponse(
                        content=content,
                        model=model,
                        provider="anthropic",
                        tokens_used=tokens,
                        latency_ms=(time.time() - start) * 1000,
                        success=True
                    )
                else:
                    return LLMResponse(
                        content="",
                        model=model,
                        provider="anthropic",
                        success=False,
                        error=f"Anthropic returned {response.status_code}"
                    )
                    
        except Exception as e:
            logger.error(f"Anthropic generate error: {e}")
            return LLMResponse(
                content="",
                model=model,
                provider="anthropic",
                success=False,
                error=str(e)
            )
    
    def get_available_models(self) -> List[str]:
        return ["claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"]


class LLMProvider:
    """
    Main LLM Provider class - abstracts away the specific provider.
    Agents use this class, allowing easy provider swapping.
    """
    
    def __init__(self, provider: str = "ollama", fallback_provider: str = None):
        self.primary_provider = provider
        self.fallback_provider = fallback_provider
        
        # Initialize all providers (lazy loading could be added)
        self._providers: Dict[str, BaseLLMProvider] = {
            "ollama": OllamaProvider(),
            "openai": OpenAIProvider(),
            "anthropic": AnthropicProvider(),
        }
        
        logger.info(f"LLMProvider initialized with primary={provider}, fallback={fallback_provider}")
    
    def get_provider(self, name: str = None) -> BaseLLMProvider:
        """Get a specific provider instance"""
        name = name or self.primary_provider
        return self._providers.get(name)
    
    async def generate(self, prompt: str, model: str = None,
                      system_prompt: str = None, temperature: float = 0.7,
                      max_tokens: int = 1000,
                      provider_override: str = None) -> LLMResponse:
        """
        Generate response from LLM.
        Uses primary provider, falls back to fallback_provider on failure.
        """
        provider_name = provider_override or self.primary_provider
        provider = self._providers.get(provider_name)
        
        if not provider:
            return LLMResponse(
                content="",
                model=model or "unknown",
                provider=provider_name,
                success=False,
                error=f"Unknown provider: {provider_name}"
            )
        
        # Try primary provider
        response = await provider.generate(
            prompt=prompt,
            model=model,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        # If failed and we have a fallback, try it
        if not response.success and self.fallback_provider:
            logger.warning(f"Primary provider {provider_name} failed, trying fallback {self.fallback_provider}")
            fallback = self._providers.get(self.fallback_provider)
            if fallback:
                response = await fallback.generate(
                    prompt=prompt,
                    model=model,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
        
        return response
    
    def switch_provider(self, new_provider: str):
        """Hot-swap the primary provider"""
        if new_provider in self._providers:
            old = self.primary_provider
            self.primary_provider = new_provider
            logger.info(f"Switched LLM provider from {old} to {new_provider}")
        else:
            raise ValueError(f"Unknown provider: {new_provider}")
    
    def get_available_providers(self) -> List[str]:
        """Get list of available providers"""
        return list(self._providers.keys())


# Singleton instance for global access
_llm_provider: Optional[LLMProvider] = None


def get_llm_provider() -> LLMProvider:
    """Get the global LLM provider instance"""
    global _llm_provider
    if _llm_provider is None:
        _llm_provider = LLMProvider(
            provider="ollama",
            fallback_provider=None  # Can set to "openai" for redundancy
        )
    return _llm_provider


def init_llm_provider(provider: str = "ollama", fallback: str = None) -> LLMProvider:
    """Initialize the global LLM provider with custom settings"""
    global _llm_provider
    _llm_provider = LLMProvider(provider=provider, fallback_provider=fallback)
    return _llm_provider
