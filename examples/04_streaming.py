"""Example 4: Streaming Events

演示如何订阅 streaming 事件流，实时展示 agent 的中间过程。

类似 Perplexity 的 thinking bubble。
"""

from __future__ import annotations

import asyncio
import json

from deepsearch_core import DeepSearch


async def main():
    async with DeepSearch() as ds:
        print("Streaming events for: 'OpenAI 最新开源模型策略'\n")

        async for event in ds.stream(
            query="OpenAI 最新开源模型策略",
            depth=2,
            policy="tech",
        ):
            payload_summary = json.dumps(event.payload, ensure_ascii=False, default=str)[:120]
            print(f"[{event.timestamp.strftime('%H:%M:%S')}] {event.type.value:30s} {payload_summary}")


if __name__ == "__main__":
    asyncio.run(main())
