"""Example 1: Quick Search

最基础用法：单轮快速搜索。

运行：
    cp ../.env.example ../.env  # 配置 LLM_API_KEY 等
    python 01_quick_search.py
"""

from __future__ import annotations

import asyncio

from deepsearch_core import DeepSearch


async def main():
    async with DeepSearch() as ds:
        result = await ds.quick_search(
            query="What is the Model Context Protocol (MCP)?",
            policy="tech",
        )
        report = result.get("report") or {}
        print("=" * 60)
        print(f"Status: {result['status']}")
        print(f"Elapsed: {result['elapsed_seconds']:.1f}s")
        print(f"Evidence: {result['evidence_count']} sources")
        print("=" * 60)
        print(report.get("body_markdown", "(no answer)"))


if __name__ == "__main__":
    asyncio.run(main())
