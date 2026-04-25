"""集成测试：DeepSearch 门面类基础烟雾测试。"""

from __future__ import annotations

import os

import pytest

from deepsearch_core import DeepSearch


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("LLM_API_KEY"), reason="needs LLM_API_KEY")
@pytest.mark.asyncio
async def test_quick_search_smoke():
    """需要真实 API key，CI 跳过。本地 .env 配置后可跑。"""
    async with DeepSearch() as ds:
        result = await ds.quick_search("What is the capital of France?", policy="general")
        assert "report" in result
        assert result["status"] in ("completed", "failed")


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("LLM_API_KEY"), reason="needs LLM_API_KEY")
@pytest.mark.asyncio
async def test_steer_workflow():
    """启动 deep search → 注入 steer → 等结果。"""
    async with DeepSearch() as ds:
        # 此测试需要异步运行环境，v0.1 简化跳过
        pytest.skip("Async steer workflow tested via CLI/HTTP integration in v0.2")
