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
    }
