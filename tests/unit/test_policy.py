"""测试 Source Policy 加载与过滤。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from deepsearch_core.exceptions import InvalidPolicyError
from deepsearch_core.policy.loader import PolicyConfig, PolicyLoader, load_policy
from deepsearch_core.retrieval.policy_filter import apply_policy_filter
from deepsearch_core.search.base import SearchResult


def test_load_general_policy():
    cfg = load_policy("general")
    assert cfg.name == "general"
    assert "wikipedia.org" in cfg.trusted_domains


def test_load_finance_policy():
    cfg = load_policy("finance")
    assert cfg.name == "finance"
    assert "sec.gov" in cfg.trusted_domains
    assert cfg.weight_boost == 2.0
    assert cfg.academic_sources.get("crossref") is True


def test_load_tech_policy():
    cfg = load_policy("tech")
    assert "github.com" in cfg.trusted_domains
    assert "arxiv.org" in cfg.trusted_domains


def test_load_academic_policy():
    cfg = load_policy("academic")
    assert cfg.weight_boost == 3.0
    assert cfg.citation.get("require_doi") is True


def test_load_invalid_policy_raises():
    with pytest.raises(InvalidPolicyError):
        load_policy("nonexistent-policy")


def test_load_inline_dict():
    cfg = load_policy({
        "name": "custom",
        "trusted_domains": ["example.com"],
        "weight_boost": 5.0,
    })
    assert cfg.name == "custom"
    assert cfg.weight_boost == 5.0


def test_list_policies():
    loader = PolicyLoader()
    names = loader.list_policies()
    assert "general" in names
    assert "finance" in names
    assert "tech" in names
    assert "academic" in names


def test_filter_blocks_blocked_domain(general_policy):
    general_policy = general_policy.model_copy(update={"blocked_domains": ["spam.com"]})
    results = [
        SearchResult(url="https://spam.com/x", title="bad", snippet="", score=0.9),
        SearchResult(url="https://good.com/x", title="ok", snippet="", score=0.5),
    ]
    filtered = apply_policy_filter(results, general_policy)
    assert len(filtered) == 1
    assert filtered[0].url.startswith("https://good.com")


def test_filter_boosts_trusted_domain(general_policy):
    results = [
        SearchResult(url="https://other.com/x", title="other", snippet="", score=0.5),
        SearchResult(url="https://wikipedia.org/Y", title="wiki", snippet="", score=0.5),
    ]
    filtered = apply_policy_filter(results, general_policy)
    # wikipedia 应该被加权到第一
    assert filtered[0].domain == "wikipedia.org"
    assert filtered[0].score > 0.5


def test_filter_blocks_subdomain(general_policy):
    """修复子域名 bug：reddit.com 必须能屏蔽 www.reddit.com / old.reddit.com。"""
    policy = general_policy.model_copy(update={"blocked_domains": ["reddit.com"]})
    results = [
        SearchResult(url="https://www.reddit.com/r/x", title="r1", snippet="", score=0.9),
        SearchResult(url="https://old.reddit.com/y", title="r2", snippet="", score=0.8),
        SearchResult(url="https://reddit.com/z", title="r3", snippet="", score=0.7),
        SearchResult(url="https://safe.com/page", title="ok", snippet="", score=0.5),
        SearchResult(url="https://notreddit.com/x", title="other", snippet="", score=0.4),
    ]
    filtered = apply_policy_filter(results, policy)
    domains = {r.domain for r in filtered}
    # 三种 reddit 子域名都该被屏蔽
    assert "www.reddit.com" not in domains
    assert "old.reddit.com" not in domains
    assert "reddit.com" not in domains
    # 但 notreddit.com（碰巧含 reddit.com 字符串）不应被屏蔽
    assert "notreddit.com" in domains
    assert "safe.com" in domains


def test_filter_blocks_wildcard():
    """*.spam.* 通配也要继续工作。"""
    from deepsearch_core.policy.loader import PolicyConfig

    policy = PolicyConfig(name="t", blocked_domains=["*.crypto-pump.*"])
    results = [
        SearchResult(url="https://abc.crypto-pump.io/x", title="bad", snippet="", score=0.9),
        SearchResult(url="https://safe.com/x", title="ok", snippet="", score=0.5),
    ]
    filtered = apply_policy_filter(results, policy)
    domains = {r.domain for r in filtered}
    assert "abc.crypto-pump.io" not in domains
    assert "safe.com" in domains
