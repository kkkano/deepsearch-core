"""Reranker 基类。"""

from __future__ import annotations

import abc

from pydantic import BaseModel


class RerankResult(BaseModel):
    index: int
    score: float
    document: str | None = None


class BaseReranker(abc.ABC):
    name: str = "base_reranker"

    @abc.abstractmethod
    async def rerank(
        self, query: str, documents: list[str], top_k: int = 5
    ) -> list[RerankResult]:
        ...

    async def aclose(self) -> None:
        return None
