"""结果去重 + 合并。"""

from __future__ import annotations

from urllib.parse import urlparse

from deepsearch_core.search.base import SearchResult


def _normalize_url(url: str) -> str:
    """简化的 url 规范化：去掉 trailing slash、去掉 query 中的 utm_xxx。"""
    p = urlparse(url.rstrip("/").lower())
    return f"{p.scheme}://{p.netloc}{p.path}"


def deduplicate_results(results: list[SearchResult]) -> list[SearchResult]:
    """url 去重，相同 url 保留 score 最高的。"""
    by_url: dict[str, SearchResult] = {}
    for r in results:
        key = _normalize_url(r.url)
        if key not in by_url or by_url[key].score < r.score:
            by_url[key] = r
    return sorted(by_url.values(), key=lambda x: -x.score)
