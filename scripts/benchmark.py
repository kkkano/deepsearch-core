"""简易性能 benchmark：跑 10 个查询统计 P50/P95/平均 token 消耗。"""

from __future__ import annotations

import asyncio
import statistics
import time

QUERIES = [
    "What is MCP?",
    "Latest OpenAI features",
    "Claude 4.7 release notes",
    "Difference between RAG and fine-tuning",
    "Python async/await best practices",
    "Rust ownership system",
    "FastAPI vs Flask performance",
    "Docker compose v3 syntax",
    "GitHub Actions caching",
    "Kubernetes vs Docker Swarm",
]


async def main():
    from deepsearch_core import DeepSearch

    latencies = []
    tokens = []

    async with DeepSearch() as ds:
        for q in QUERIES:
            t0 = time.time()
            result = await ds.quick_search(q, policy="tech")
            elapsed = time.time() - t0
            latencies.append(elapsed)
            tokens.append((result.get("token_usage") or {}).get("total_tokens", 0))
            print(f"  {q[:50]:50s} {elapsed:.2f}s  {tokens[-1]} tok")

    print("\n=== Benchmark Results ===")
    print(f"P50 latency: {statistics.median(latencies):.2f}s")
    print(f"P95 latency: {statistics.quantiles(latencies, n=20)[18]:.2f}s" if len(latencies) >= 20 else f"Max latency: {max(latencies):.2f}s")
    print(f"Avg tokens:  {statistics.mean(tokens):.0f}")


if __name__ == "__main__":
    asyncio.run(main())
