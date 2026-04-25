"""Example 2: Deep Search with Steer

演示如何在 deep search 跑的过程中注入 steer 命令重定向方向。

运行：
    python 02_deep_search_with_steer.py
"""

from __future__ import annotations

import asyncio

from deepsearch_core import DeepSearch


async def main():
    async with DeepSearch() as ds:
        # 1. 启动深度搜索（在后台 task）
        from deepsearch_core.engine.state import RunConfig, State

        config = RunConfig(goal="腾讯港股 2026 风险分析", depth=3, policy="finance")
        state = State(config=config)
        ctx = ds._build_context("finance")
        runner = ds._build_runner(ctx)

        run_task = asyncio.create_task(runner.run(state, start_node="check_clarity"))
        print(f"Started task: {state.run_id}")

        # 2. 等 5 秒，然后注入 steer
        await asyncio.sleep(5)
        cmd = ds.steer(state.run_id, "重点关注 AI 业务线，忽略游戏和社交", scope="global")
        print(f"Steered: {cmd.cmd_id} → 重点 AI 业务线")

        # 3. 等待最终结果
        final = await run_task
        print(f"\nFinal status: {final.status.value}")
        if final.report:
            print(final.report.body_markdown[:1000])


if __name__ == "__main__":
    asyncio.run(main())
