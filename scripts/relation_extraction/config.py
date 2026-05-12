"""Configuration for relation extraction pipeline."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_path(env_value: Optional[str], fallback: Path) -> Path:
    if env_value:
        p = Path(env_value)
        return p if p.is_absolute() else (_REPO_ROOT / p)
    return fallback


@dataclass
class RELLMConfig:
    """LLM config dedicated to RE classifier (separate from entity extraction)."""

    provider: str = "ollama"
    model: str = "gemma4:31b-it-q8_0"
    base_url: str = "http://localhost:11434"
    api_key: Optional[str] = None
    max_tokens: int = 1024
    temperature: float = 0.1
    num_ctx: int = 16384
    rate_limit_delay: float = 0.0
    max_retries: int = 3
    retry_delay: float = 5.0
    batch_size: int = 8

    @classmethod
    def from_env(cls) -> "RELLMConfig":
        provider = os.getenv("RE_LLM_PROVIDER", "ollama").lower()
        if provider == "ollama":
            base_url = os.getenv(
                "RE_OLLAMA_BASE_URL",
                os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            )
            model = os.getenv("RE_OLLAMA_MODEL", "gemma4:31b-it-q8_0")
            api_key = None
        elif provider == "claude":
            base_url = ""
            api_key = os.getenv("RE_ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_API_KEY"))
            model = os.getenv("RE_CLAUDE_MODEL", "claude-haiku-4-5")
        elif provider == "openai":
            base_url = ""
            api_key = os.getenv("RE_OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
            model = os.getenv("RE_OPENAI_MODEL", "gpt-4o-mini")
        else:
            raise ValueError(f"Unknown RE_LLM_PROVIDER: {provider}")

        return cls(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            max_tokens=int(os.getenv("RE_MAX_TOKENS", "1024")),
            temperature=float(os.getenv("RE_TEMPERATURE", "0.1")),
            num_ctx=int(os.getenv("RE_NUM_CTX", "16384")),
            rate_limit_delay=float(os.getenv("RE_RATE_LIMIT_DELAY", "0.0")),
            max_retries=int(os.getenv("RE_MAX_RETRIES", "3")),
            retry_delay=float(os.getenv("RE_RETRY_DELAY", "5.0")),
            batch_size=int(os.getenv("RE_BATCH_SIZE", "8")),
        )


@dataclass
class REPipelineConfig:
    """Knobs for the orchestrator (paths, thresholds, file locations)."""

    schema_path: Path
    priors_path: Path
    output_path: Path
    checkpoint_path: Path
    unclassified_path: Path
    same_verse_only: bool = False
    grounding_window: int = 1
    min_pair_freq: int = 1
    max_pairs_per_pericope: int = 80
    rule_confidence_floor: float = 0.85
    skip_self_loops: bool = True

    @classmethod
    def from_env(cls) -> "REPipelineConfig":
        schema = _resolve_path(
            os.getenv("RE_SCHEMA_PATH"),
            _REPO_ROOT / "config" / "relations" / "biblical_relations.yaml",
        )
        priors = _resolve_path(
            os.getenv("RE_PRIORS_PATH"),
            _REPO_ROOT / "config" / "relations" / "biblical_priors.yaml",
        )
        output = _resolve_path(
            os.getenv("RE_OUTPUT_PATH"),
            _REPO_ROOT / "output" / "relations.jsonl",
        )
        checkpoint = _resolve_path(
            os.getenv("RE_CHECKPOINT_PATH"),
            _REPO_ROOT / "output" / "relations_checkpoint.jsonl",
        )
        unclassified = _resolve_path(
            os.getenv("RE_UNCLASSIFIED_PATH"),
            _REPO_ROOT / "output" / "relations_unclassified.jsonl",
        )
        return cls(
            schema_path=schema,
            priors_path=priors,
            output_path=output,
            checkpoint_path=checkpoint,
            unclassified_path=unclassified,
            same_verse_only=os.getenv("RE_SAME_VERSE_ONLY", "false").lower() in {"1", "true", "yes"},
            grounding_window=int(os.getenv("RE_GROUNDING_WINDOW", "1")),
            min_pair_freq=int(os.getenv("RE_MIN_PAIR_FREQ", "1")),
            max_pairs_per_pericope=int(os.getenv("RE_MAX_PAIRS_PER_PERICOPE", "80")),
            rule_confidence_floor=float(os.getenv("RE_RULE_CONFIDENCE_FLOOR", "0.85")),
            skip_self_loops=os.getenv("RE_SKIP_SELF_LOOPS", "true").lower() in {"1", "true", "yes"},
        )


@dataclass
class Neo4jConfig:
    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "neo4j_password"

    @classmethod
    def from_env(cls) -> "Neo4jConfig":
        return cls(
            uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            user=os.getenv("NEO4J_USER", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", "neo4j_password"),
        )
