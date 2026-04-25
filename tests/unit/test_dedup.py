"""测试结果去重。"""

from __future__ import annotations

from deepsearch_core.retrieval.dedup import deduplicate_results
from deepsearch_core.search.base import SearchResult


def test_dedup_same_url():
    results = [
        SearchResult(url="https://example.com/a", title="A1", snippet="", score=0.5),
        SearchResult(url="https://example.com/a", title="A2", snippet="", score=0.9),
        SearchResult(url="https://example.com/b", title="B", snippet="", score=0.7),
    ]
    deduped = deduplicate_results(results)
    assert len(deduped) == 2
    # 高分版本保留
    a = next(r for r in deduped if r.url.endswith("/a"))
    assert a.score == 0.9


def test_dedup_trailing_slash():
    results = [
        SearchResult(url="https://example.com/a/", title="A1", snippet="", score=0.5),
        SearchResult(url="https://example.com/a", title="A2", snippet="", score=0.7),
    ]
    deduped = deduplicate_results(results)
    assert len(deduped) == 1


def test_dedup_sorts_by_score():
    results = [
        SearchResult(url="https://a.com", title="A", snippet="", score=0.3),
        SearchResult(url="https://b.com", title="B", snippet="", score=0.9),
        SearchResult(url="https://c.com", title="C", snippet="", score=0.6),
    ]
    deduped = deduplicate_results(results)
    scores = [r.score for r in deduped]
    assert scores == sorted(scores, reverse=True)
