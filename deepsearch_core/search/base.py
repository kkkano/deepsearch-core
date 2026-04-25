"""搜索引擎基类与通用数据模型。"""

from __future__ import annotations

import abc
from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    url: str
    title: str
    snippet: str
    score: float = 0.0
    source: str = "unknown"
    published_at: datetime | None = None
    full_text: str | None = None
    domain: str = ""

    def model_post_init(self, __context):
        if not self.domain:
            self.domain = urlparse(self.url).netloc


class BaseSearch(abc.ABC):
    """所有搜索引擎实现这个接口。"""

    name: str = "base"

    @abc.abstractmethod
    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        ...

    async def aclose(self) -> None:
        return None


class BaseReader(abc.ABC):
    """全文抽取器（Firecrawl / Jina Reader）。"""

    name: str = "base_reader"

    @abc.abstractmethod
    async def read(self, url: str) -> str:
        """返回 markdown 格式正文。"""
        ...

    async def aclose(self) -> None:
        return None
