"""Cohere Rerank API（rerank-v3.5）。"""

from __future__ import annotations

import httpx
import structlog

from deepsearch_core.exceptions import SearchError
from deepsearch_core.reranker.base import BaseReranker, RerankResult

logger = structlog.get_logger(__name__)


class CohereReranker(BaseReranker):
    name = "cohere"

    def __init__(self, api_key: str, model: str = "rerank-v3.5", timeout: float = 30.0):
        self.api_key = api_key
        self.model = model
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )

    async def rerank(self, query: str, documents: list[str], top_k: int = 5) -> list[RerankResult]:
        if not self.api_key:
            raise SearchError("COHERE_API_KEY not configured")
        if not documents:
            return []

        try:
            resp = await self._client.post(
                "https://api.cohere.com/v2/rerank",
                json={
                    "model": self.model,
                    "query": query,
                    "documents": documents,
                    "top_n": min(top_k, len(documents)),
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("cohere_rerank_failed", error=str(e))
            # 失败时返回原顺序
            return [RerankResult(index=i, score=1.0 - i * 0.05) for i in range(min(top_k, len(documents)))]

        data = resp.json()
        return [
            RerankResult(index=r["index"], score=r["relevance_score"])
            for r in data.get("results", [])
        ]

    async def aclose(self) -> None:
        await self._client.aclose()
