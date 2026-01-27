"""
LLM Service - Portable AI Layer
Supports multiple LLM providers with fallback chain:
1. OpenAI API (portable - works anywhere)
2. Anthropic API (optional)
3. Emergent LLM Key (development fallback)
4. Local LLM via Ollama (future)

Configure via environment variables:
- OPENAI_API_KEY: Your OpenAI API key
- ANTHROPIC_API_KEY: Your Anthropic API key (optional)
- EMERGENT_LLM_KEY: Emergent platform key (auto-detected)
- LLM_PROVIDER: Force a specific provider (openai, anthropic, emergent, local)
"""
import os
import json
import logging
from typing import Optional, Dict, Any, List
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    @abstractmethod
    def generate(self, prompt: str, system_prompt: str = None, max_tokens: int = 2000, temperature: float = 0.7) -> str:
        """Generate text from prompt"""
        pass
    
    @abstractmethod
    def generate_json(self, prompt: str, system_prompt: str = None, max_tokens: int = 2000) -> Dict[str, Any]:
        """Generate JSON response from prompt"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is configured and available"""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging"""
        pass


class OpenAIProvider(LLMProvider):
    """OpenAI API provider - fully portable"""
    
    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4o")
        self._client = None
    
    @property
    def name(self) -> str:
        return "OpenAI"
    
    def is_available(self) -> bool:
        return bool(self.api_key)
    
    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)
        return self._client
    
    def generate(self, prompt: str, system_prompt: str = None, max_tokens: int = 2000, temperature: float = 0.7) -> str:
        try:
            client = self._get_client()
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI generation error: {e}")
            raise
    
    def generate_json(self, prompt: str, system_prompt: str = None, max_tokens: int = 2000) -> Dict[str, Any]:
        try:
            client = self._get_client()
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.3,  # Lower temp for structured output
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"OpenAI JSON generation error: {e}")
            raise


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider - portable"""
    
    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        self._client = None
    
    @property
    def name(self) -> str:
        return "Anthropic"
    
    def is_available(self) -> bool:
        return bool(self.api_key)
    
    def _get_client(self):
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self.api_key)
        return self._client
    
    def generate(self, prompt: str, system_prompt: str = None, max_tokens: int = 2000, temperature: float = 0.7) -> str:
        try:
            client = self._get_client()
            response = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system_prompt or "You are a helpful trading assistant.",
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Anthropic generation error: {e}")
            raise
    
    def generate_json(self, prompt: str, system_prompt: str = None, max_tokens: int = 2000) -> Dict[str, Any]:
        json_prompt = f"{prompt}\n\nRespond with valid JSON only, no other text."
        response = self.generate(json_prompt, system_prompt, max_tokens, temperature=0.3)
        # Extract JSON from response
        try:
            # Try to find JSON in response
            if response.strip().startswith("{"):
                return json.loads(response)
            # Look for JSON block
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
            raise ValueError("No JSON found in response")
        except Exception as e:
            logger.error(f"Anthropic JSON parsing error: {e}")
            raise


class EmergentProvider(LLMProvider):
    """Emergent LLM Key provider - for development on Emergent platform"""
    
    def __init__(self):
        self.api_key = os.environ.get("EMERGENT_LLM_KEY")
        self.model = "gpt-4o"
    
    @property
    def name(self) -> str:
        return "Emergent"
    
    def is_available(self) -> bool:
        return bool(self.api_key)
    
    def generate(self, prompt: str, system_prompt: str = None, max_tokens: int = 2000, temperature: float = 0.7) -> str:
        try:
            from emergentintegrations.llm.chat import LlmChat
            import uuid
            
            session_id = str(uuid.uuid4())
            sys_msg = system_prompt or "You are a helpful trading assistant."
            
            chat = LlmChat(
                api_key=self.api_key,
                session_id=session_id,
                system_message=sys_msg
            ).with_model("openai", "gpt-4o")
            
            response = chat.send_message(prompt)
            return response
        except Exception as e:
            logger.error(f"Emergent generation error: {e}")
            raise
    
    def generate_json(self, prompt: str, system_prompt: str = None, max_tokens: int = 2000) -> Dict[str, Any]:
        json_prompt = f"{prompt}\n\nRespond with valid JSON only, no other text or markdown."
        response = self.generate(json_prompt, system_prompt, max_tokens)
        try:
            # Clean up response
            cleaned = response.strip()
            if cleaned.startswith("```"):
                # Remove markdown code blocks
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
            return json.loads(cleaned)
        except Exception as e:
            logger.error(f"Emergent JSON parsing error: {e}")
            # Try to extract JSON
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
            raise


class LLMService:
    """
    Main LLM service with automatic provider selection.
    
    Priority order (configurable via LLM_PROVIDER env var):
    1. OpenAI (if OPENAI_API_KEY is set)
    2. Anthropic (if ANTHROPIC_API_KEY is set)
    3. Emergent (if EMERGENT_LLM_KEY is set)
    """
    
    def __init__(self):
        self.providers: Dict[str, LLMProvider] = {
            "openai": OpenAIProvider(),
            "anthropic": AnthropicProvider(),
            "emergent": EmergentProvider()
        }
        self._active_provider: Optional[LLMProvider] = None
        self._select_provider()
    
    def _select_provider(self):
        """Select the best available provider"""
        forced_provider = os.environ.get("LLM_PROVIDER", "").lower()
        
        # If a specific provider is forced, try it first
        if forced_provider and forced_provider in self.providers:
            provider = self.providers[forced_provider]
            if provider.is_available():
                self._active_provider = provider
                logger.info(f"Using forced LLM provider: {provider.name}")
                return
            else:
                logger.warning(f"Forced provider {forced_provider} not available, falling back")
        
        # Try providers in priority order
        priority = ["openai", "anthropic", "emergent"]
        for name in priority:
            provider = self.providers[name]
            if provider.is_available():
                self._active_provider = provider
                logger.info(f"Using LLM provider: {provider.name}")
                return
        
        logger.warning("No LLM provider available!")
        self._active_provider = None
    
    @property
    def is_available(self) -> bool:
        """Check if any LLM provider is available"""
        return self._active_provider is not None
    
    @property
    def provider_name(self) -> str:
        """Get the name of the active provider"""
        return self._active_provider.name if self._active_provider else "None"
    
    def generate(self, prompt: str, system_prompt: str = None, max_tokens: int = 2000, temperature: float = 0.7) -> str:
        """Generate text using the active provider"""
        if not self._active_provider:
            raise RuntimeError("No LLM provider available. Set OPENAI_API_KEY or EMERGENT_LLM_KEY.")
        return self._active_provider.generate(prompt, system_prompt, max_tokens, temperature)
    
    def generate_json(self, prompt: str, system_prompt: str = None, max_tokens: int = 2000) -> Dict[str, Any]:
        """Generate JSON using the active provider"""
        if not self._active_provider:
            raise RuntimeError("No LLM provider available. Set OPENAI_API_KEY or EMERGENT_LLM_KEY.")
        return self._active_provider.generate_json(prompt, system_prompt, max_tokens)
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all providers"""
        return {
            "active_provider": self.provider_name,
            "providers": {
                name: {
                    "available": provider.is_available(),
                    "name": provider.name
                }
                for name, provider in self.providers.items()
            }
        }


# Singleton instance
_llm_service: Optional[LLMService] = None

def get_llm_service() -> LLMService:
    """Get the singleton LLM service instance"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
