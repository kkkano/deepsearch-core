"""pytest 共享 fixture。"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepsearch_core.engine.state import RunConfig, State
from deepsearch_core.llm.client import LLMResponse
from deepsearch_core.policy.loader import PolicyConfig
from deepsearch_core.store.store import EventStore


@pytest.fixture
def tmp_db():
    """临时 SQLite 数据库。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield f"sqlite:///{path}"
    path.unlink(missing_ok=True)


@pytest.fixture
def store(tmp_db):
    s = EventStore(tmp_db)
    yield s
    s.close()


@pytest.fixture
def basic_state():
    return State(
        config=RunConfig(goal="What is MCP?", depth=1, max_agents=1),
    )


@pytest.fixture
def general_policy():
    return PolicyConfig(
        name="general",
        trusted_domains=["wikipedia.org"],
        weight_boost=1.5,
    )


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.chat = AsyncMock(
        return_value=LLMResponse(
            content='{"sub_queries": [{"text": "test query", "angle": "general", "priority": 5}]}',
            prompt_tokens=100,
            completion_tokens=50,
        )
    )
    llm.complete_json = AsyncMock(return_value={"is_clear": True})
    llm.aclose = AsyncMock()
    return llm
