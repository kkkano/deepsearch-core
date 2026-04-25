"""全局配置加载（从 .env / 环境变量）。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class LLMConfig(BaseModel):
    base_url: str = Field(default_factory=lambda: os.getenv("LLM_BASE_URL", "https://api.anthropic.com/v1"))
    api_key: str = Field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    supervisor_model: str = Field(default_factory=lambda: os.getenv("SUPERVISOR_MODEL", "claude-sonnet-4-6"))
    planner_model: str = Field(default_factory=lambda: os.getenv("PLANNER_MODEL", "claude-haiku-4-5"))
    researcher_model: str = Field(default_factory=lambda: os.getenv("RESEARCHER_MODEL", "claude-haiku-4-5"))
    critic_model: str = Field(default_factory=lambda: os.getenv("CRITIC_MODEL", "claude-sonnet-4-6"))
    reporter_model: str = Field(default_factory=lambda: os.getenv("REPORTER_MODEL", "claude-opus-4-7"))
    enable_caching: bool = Field(default_factory=lambda: os.getenv("ENABLE_PROMPT_CACHING", "false").lower() == "true")

    def model_for(self, role: str) -> str:
        return {
            "supervisor": self.supervisor_model,
            "planner": self.planner_model,
            "researcher": self.researcher_model,
            "critic": self.critic_model,
            "reporter": self.reporter_model,
        }.get(role, self.supervisor_model)

    def temperature_for(self, role: str) -> float:
        env_key = f"{role.upper()}_TEMPERATURE"
        return float(os.getenv(env_key, "0"))


class SearchConfig(BaseModel):
    tavily_api_key: str = Field(default_factory=lambda: os.getenv("TAVILY_API_KEY", ""))
    serper_api_key: str = Field(default_factory=lambda: os.getenv("SERPER_API_KEY", ""))
    firecrawl_api_key: str = Field(default_factory=lambda: os.getenv("FIRECRAWL_API_KEY", ""))
    jina_reader_api_key: str = Field(default_factory=lambda: os.getenv("JINA_READER_API_KEY", ""))
    crossref_base_url: str = Field(default_factory=lambda: os.getenv("CROSSREF_BASE_URL", "https://api.crossref.org"))
    crossref_mailto: str = Field(default_factory=lambda: os.getenv("CROSSREF_MAILTO", ""))
    cohere_api_key: str = Field(default_factory=lambda: os.getenv("COHERE_API_KEY", ""))
    cohere_rerank_model: str = Field(default_factory=lambda: os.getenv("COHERE_RERANK_MODEL", "rerank-v3.5"))
    max_results_per_query: int = Field(default_factory=lambda: int(os.getenv("SEARCH_MAX_RESULTS_PER_QUERY", "10")))
    max_sources_per_step: int = Field(default_factory=lambda: int(os.getenv("MAX_SOURCES_PER_STEP", "5")))
    max_read_sources_per_step: int = Field(default_factory=lambda: int(os.getenv("MAX_READ_SOURCES_PER_STEP", "3")))


class EngineConfig(BaseModel):
    max_agents_fan_out: int = Field(default_factory=lambda: int(os.getenv("MAX_AGENTS_FAN_OUT", "4")))
    max_steps_per_research: int = Field(default_factory=lambda: int(os.getenv("MAX_STEPS_PER_RESEARCH", "8")))
    task_timeout_seconds: int = Field(default_factory=lambda: int(os.getenv("TASK_TIMEOUT_SECONDS", "300")))
    default_policy: str = Field(default_factory=lambda: os.getenv("DEFAULT_POLICY", "general"))
    policy_dir: Path = Field(default_factory=lambda: Path(os.getenv("POLICY_DIR", "")) if os.getenv("POLICY_DIR") else Path(__file__).parent / "policy" / "policies")


class StoreConfig(BaseModel):
    dsn: str = Field(default_factory=lambda: os.getenv("EVENT_STORE_DSN", "sqlite:///./runs.db"))
    enable_event_sourcing: bool = Field(default_factory=lambda: os.getenv("ENABLE_EVENT_SOURCING", "true").lower() == "true")


class ServerConfig(BaseModel):
    http_host: str = Field(default_factory=lambda: os.getenv("HTTP_HOST", "0.0.0.0"))
    http_port: int = Field(default_factory=lambda: int(os.getenv("HTTP_PORT", "8000")))
    mcp_transport: str = Field(default_factory=lambda: os.getenv("MCP_TRANSPORT", "stdio"))
    mcp_port: int = Field(default_factory=lambda: int(os.getenv("MCP_PORT", "8765")))


class GlobalConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    engine: EngineConfig = Field(default_factory=EngineConfig)
    store: StoreConfig = Field(default_factory=StoreConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    log_level: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))


@lru_cache(maxsize=1)
def get_config() -> GlobalConfig:
    """单例配置。测试时可以 get_config.cache_clear()。"""
    return GlobalConfig()
