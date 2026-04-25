"""Policy YAML 加载器。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from deepsearch_core.exceptions import InvalidPolicyError

DEFAULT_POLICY_DIR = Path(__file__).parent / "policies"


class SearchKeyword(BaseModel):
    keyword: str
    augment: list[str] = Field(default_factory=list)


class PolicyConfig(BaseModel):
    name: str
    display_name: str = ""
    description: str = ""
    version: int = 1
    language: str = "en-US"
    trusted_domains: list[str] = Field(default_factory=list)
    weight_boost: float = 2.0
    blocked_domains: list[str] = Field(default_factory=list)
    academic_sources: dict[str, Any] = Field(default_factory=lambda: {"enabled": False})
    search_keywords: list[SearchKeyword] = Field(default_factory=list)
    prompt_addons: dict[str, str] = Field(default_factory=dict)
    freshness: dict[str, Any] = Field(default_factory=dict)
    citation: dict[str, Any] = Field(default_factory=dict)


class PolicyLoader:
    def __init__(self, policy_dir: Path | None = None):
        self.policy_dir = policy_dir or DEFAULT_POLICY_DIR
        self._cache: dict[str, PolicyConfig] = {}

    def load(self, name_or_path: str | dict | PolicyConfig) -> PolicyConfig:
        if isinstance(name_or_path, PolicyConfig):
            return name_or_path
        if isinstance(name_or_path, dict):
            return PolicyConfig(**name_or_path)

        if name_or_path in self._cache:
            return self._cache[name_or_path]

        path = Path(name_or_path)
        if not path.exists():
            path = self.policy_dir / f"{name_or_path}.yml"
        if not path.exists():
            raise InvalidPolicyError(f"Policy not found: {name_or_path}", attempted=str(path))

        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            cfg = PolicyConfig(**data)
        except (yaml.YAMLError, ValueError) as e:
            raise InvalidPolicyError(f"Invalid policy YAML: {e}", path=str(path)) from e

        self._cache[name_or_path] = cfg
        return cfg

    def list_policies(self) -> list[str]:
        return [p.stem for p in self.policy_dir.glob("*.yml")]


@lru_cache(maxsize=1)
def _global_loader() -> PolicyLoader:
    return PolicyLoader()


def load_policy(name_or_path: str | dict | PolicyConfig) -> PolicyConfig:
    return _global_loader().load(name_or_path)
