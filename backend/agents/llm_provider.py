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
    """Ollama provider - direct local connection"""
    
    # Dedicated thread pool for LLM calls — immune to main pool exhaustion
    import concurrent.futures as _cf
    _llm_pool = _cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="llm")
    
    def __init__(self):
        # Direct Ollama URL — use 127.0.0.1 (not localhost) to avoid IPv6 hang
        self.ollama_url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
        # Primary model: GPT-OSS 120B cloud (best reasoning, 1s response, zero GPU cost)
        self.default_model = os.environ.get("OLLAMA_MODEL", "gpt-oss:120b-cloud")
        # Local fallback: Qwen3 30B (works offline, runs on GB10)
        self.fallback_model = os.environ.get("OLLAMA_FALLBACK_MODEL", "qwen3:30b")
    
    async def generate(self, prompt: str, model: str = None,
                      system_prompt: str = None, temperature: float = 0.7,
                      max_tokens: int = 1000) -> LLMResponse:
        """Generate using Ollama — direct local connection (proxy no longer needed)"""
        import time
        start = time.time()
        
        model = model or self.default_model
        
        # Direct Ollama API call (Ollama runs on Spark localhost)
        response = await self._call_ollama_direct(prompt, model, system_prompt, temperature, max_tokens)
        if response.success:
            return response
        
        # Fallback model (if not already using it)
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
            error="Ollama not available. Check: ollama serve",
            latency_ms=(time.time() - start) * 1000
        )
    
    async def _call_ollama_direct(self, prompt: str, model: str, system_prompt: str = None,
                                  temperature: float = 0.7, max_tokens: int = 1000) -> LLMResponse:
        """Direct Ollama API call — uses sync requests in thread to avoid event loop blocking"""
        import time
        start = time.time()
        
        try:
            import requests as sync_requests
            
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            timeout = 90 if "cloud" not in model else 30
            
            def _sync_call():
                r = sync_requests.post(
                    f"{self.ollama_url}/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": False,
                        "options": {
                            "temperature": temperature,
                            "num_predict": max_tokens
                        }
                    },
                    timeout=timeout
                )
                return r.status_code, r.json()
            
            # Use raw thread — immune to ThreadPoolExecutor exhaustion
            import threading
            loop = asyncio.get_event_loop()
            future = loop.create_future()
            
            def _threaded_call():
                try:
                    result = _sync_call()
                    loop.call_soon_threadsafe(future.set_result, result)
                except Exception as ex:
                    loop.call_soon_threadsafe(future.set_exception, ex)
            
            t = threading.Thread(target=_threaded_call, daemon=True)
            t.start()
            status_code, data = await asyncio.wait_for(future, timeout=float(timeout))
            
            if status_code == 200:
                if "error" in data:
                    return LLMResponse(
                        content="",
                        model=model,
                        provider="ollama",
                        success=False,
                        error=data["error"]
                    )
                content = data.get("message", {}).get("content", "")
                if not content:
                    return LLMResponse(
                        content="",
                        model=model,
                        provider="ollama",
                        success=False,
                        error="Empty response from Ollama"
                    )
                
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
                    error=f"Ollama returned {status_code}"
                )
                    
        except Exception as e:
            logger.error(f"Ollama direct call error ({model}): {type(e).__name__}: {e}")
            return LLMResponse(
                content="",
                model=model,
                provider="ollama",
                success=False,
                error=str(e)
            )
    
    def get_available_models(self) -> List[str]:
        return ["gpt-oss:120b-cloud", "qwen3:30b", "llama3.3:70b"]


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
