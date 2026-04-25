"""Example 3: Custom Policy

演示如何用 inline dict 自定义 source policy。

适用场景：临时调研某个领域，不想新建 YAML 文件。
"""

from __future__ import annotations

import asyncio

from deepsearch_core import DeepSearch


CUSTOM_POLICY = {
    "name": "crypto",
    "display_name": "Crypto Research",
    "trusted_domains": [
        "ethereum.org",
        "bitcoin.org",
        "vitalik.ca",
        "coindesk.com",
        "messari.io",
    ],
    "weight_boost": 2.5,
    "blocked_domains": [
        "*.pump-and-dump.*",
        "*.shitcoin-shilling.*",
    ],
    "academic_sources": {"enabled": True, "arxiv": True},
    "search_keywords": [
        {"keyword": "tokenomics", "augment": ["whitepaper", "supply schedule"]},
    ],
    "prompt_addons": {
        "researcher": "Distinguish on-chain data from speculation. Cite block numbers when relevant.",
        "critic": "Flag any anonymous claims or paid promotion. Demand on-chain evidence.",
    },
    "freshness": {"prefer_within_days": 7, "decay_factor": 0.85},
    "citation": {"min_sources": 3, "prefer_primary": True},
}


async def main():
    async with DeepSearch() as ds:
        result = await ds.deep_search(
            query="Latest EigenLayer restaking risks",
            depth=3,
            policy=CUSTOM_POLICY,  # 直接传 dict
        )
        if result.get("report"):
            print(result["report"]["body_markdown"])


if __name__ == "__main__":
    asyncio.run(main())
