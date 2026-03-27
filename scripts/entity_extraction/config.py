"""
Configuration management for entity extraction.
Loads settings from environment variables.
"""

import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

# Load .env file
load_dotenv()


@dataclass
class LLMConfig:
    """LLM configuration from environment variables."""
    provider: str = "claude"  # "claude", "gemini", or "openai"
    model: str = "claude-3-5-haiku-20241022"
    api_key: Optional[str] = None
    max_tokens: int = 1024
    temperature: float = 0.1
    rate_limit_delay: float = 1.0
    max_retries: int = 3
    retry_delay: float = 2.0

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Create LLMConfig from environment variables."""
        provider = os.getenv("LLM_PROVIDER", "claude").lower()
        
        # Get API key based on provider
        api_key = None
        model = None
        
        if provider == "claude":
            api_key = os.getenv("ANTHROPIC_API_KEY")
            model = os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022")
        elif provider == "gemini":
            api_key = os.getenv("GOOGLE_API_KEY")
            model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        elif provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        elif provider == "ollama":
            api_key = None
            model = os.getenv("OLLAMA_MODEL", "gemma3:4b")
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")
        
        return cls(
            provider=provider,
            model=model,
            api_key=api_key,
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1024")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
            rate_limit_delay=float(os.getenv("LLM_RATE_LIMIT_DELAY", "1.0")),
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
            retry_delay=float(os.getenv("LLM_RETRY_DELAY", "2.0")),
        )


@dataclass
class EntityExtractLLMConfig:
    """LLM config for grounded entity extraction pipeline."""
    provider: str = "ollama"
    model: str = "gemma3:4b"
    api_key: Optional[str] = None
    base_url: str = "http://localhost:11434"
    max_tokens: int = 1024
    temperature: float = 0.1
    rate_limit_delay: float = 0.5
    max_retries: int = 3
    retry_delay: float = 2.0

    @classmethod
    def from_env(cls) -> "EntityExtractLLMConfig":
        provider = os.getenv("ENTITY_EXTRACT_LLM_PROVIDER", "ollama").lower()

        api_key = None
        model = None
        base_url = ""

        if provider == "ollama":
            base_url = os.getenv(
                "ENTITY_EXTRACT_OLLAMA_BASE_URL",
                os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            )
            model = os.getenv(
                "ENTITY_EXTRACT_OLLAMA_MODEL",
                os.getenv("OLLAMA_MODEL", "gemma3:4b"),
            )
        elif provider == "claude":
            api_key = os.getenv(
                "ENTITY_EXTRACT_ANTHROPIC_API_KEY",
                os.getenv("ANTHROPIC_API_KEY"),
            )
            model = os.getenv("ENTITY_EXTRACT_CLAUDE_MODEL", "claude-3-5-haiku-20241022")
        elif provider == "openai":
            api_key = os.getenv(
                "ENTITY_EXTRACT_OPENAI_API_KEY",
                os.getenv("OPENAI_API_KEY"),
            )
            model = os.getenv("ENTITY_EXTRACT_OPENAI_MODEL", "gpt-4o-mini")
        elif provider == "gemini":
            api_key = os.getenv(
                "ENTITY_EXTRACT_GOOGLE_API_KEY",
                os.getenv("GOOGLE_API_KEY"),
            )
            model = os.getenv("ENTITY_EXTRACT_GEMINI_MODEL", "gemini-1.5-flash")
        else:
            raise ValueError(f"Unknown ENTITY_EXTRACT_LLM_PROVIDER: {provider}")

        return cls(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_tokens=int(os.getenv("ENTITY_EXTRACT_MAX_TOKENS", "1024")),
            temperature=float(os.getenv("ENTITY_EXTRACT_TEMPERATURE", "0.1")),
            rate_limit_delay=float(os.getenv("ENTITY_EXTRACT_RATE_LIMIT_DELAY", "0.5")),
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
            retry_delay=float(os.getenv("LLM_RETRY_DELAY", "2.0")),
        )


@dataclass
class GroundedConfig:
    """Pipeline parameters for grounded extraction."""
    min_freq: int = 3
    rule_confidence: float = 0.8

    @classmethod
    def from_env(cls) -> "GroundedConfig":
        return cls(
            min_freq=int(os.getenv("ENTITY_EXTRACT_MIN_FREQ", "3")),
            rule_confidence=float(os.getenv("ENTITY_EXTRACT_RULE_CONFIDENCE", "0.8")),
        )


@dataclass
class CKIPConfig:
    """CKIP configuration from environment variables."""
    use_gpu: bool = False

    @classmethod
    def from_env(cls) -> "CKIPConfig":
        """Create CKIPConfig from environment variables."""
        use_gpu_str = os.getenv("CKIP_USE_GPU", "false").lower()
        use_gpu = use_gpu_str in ("true", "1", "yes")
        
        return cls(use_gpu=use_gpu)


@dataclass
class ExtractionConfig:
    """General extraction configuration."""
    batch_size: int = 5
    verbose: bool = False

    @classmethod
    def from_env(cls) -> "ExtractionConfig":
        """Create ExtractionConfig from environment variables."""
        verbose_str = os.getenv("VERBOSE", "false").lower()
        verbose = verbose_str in ("true", "1", "yes")
        
        return cls(
            batch_size=int(os.getenv("BATCH_SIZE", "5")),
            verbose=verbose,
        )


def get_config():
    """Get all configuration from environment."""
    return {
        "llm": LLMConfig.from_env(),
        "ckip": CKIPConfig.from_env(),
        "extraction": ExtractionConfig.from_env(),
        "entity_extract_llm": EntityExtractLLMConfig.from_env(),
        "grounded": GroundedConfig.from_env(),
    }
