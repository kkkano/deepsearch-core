"""Example 5: Finance Use Case

演示金融领域 deep research 的最佳实践。

特性：
- policy=finance 启用金融专用 trusted domains
- 包含 SEC / 港交所 / 巨潮等中外金融源
- 自动启用 Crossref 学术源
- 提示词包含金融领域 guidance
"""

from __future__ import annotations

import asyncio

from deepsearch_core import DeepSearch


async def main():
    questions = [
        "腾讯 2025Q4 财报关键指标解读",
        "美联储 2026 年降息路径预期",
        "中国新能源车出口对欧洲市场的影响",
    ]

    async with DeepSearch() as ds:
        for q in questions:
            print(f"\n{'=' * 70}")
            print(f"📊 {q}")
            print("=" * 70)

            result = await ds.deep_search(q, depth=3, policy="finance", max_agents=4)

            if result.get("report"):
                report = result["report"]
                print(report.get("body_markdown", "")[:2000])

                if result.get("critic"):
                    critic = result["critic"]
                    print(f"\n📝 Critic confidence: {critic['confidence']:.2f}")
                    if critic.get("conflicts"):
                        print(f"⚠️  Conflicts: {critic['conflicts']}")

                usage = result.get("token_usage", {})
                print(f"\n💰 Tokens: {usage.get('total_tokens', 0)} | Elapsed: {result['elapsed_seconds']:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
