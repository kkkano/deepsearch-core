"""按 Source Policy 过滤 + 加权检索结果。"""

from __future__ import annotations

import fnmatch
from datetime import datetime
from urllib.parse import urlparse

from deepsearch_core.policy.loader import PolicyConfig
from deepsearch_core.search.base import SearchResult


def _matches(domain: str, pattern: str) -> bool:
    return fnmatch.fnmatch(domain, pattern.lower())


def apply_policy_filter(
    results: list[SearchResult],
    policy: PolicyConfig,
) -> list[SearchResult]:
    """按 policy 屏蔽 + 加权 + 时间衰减。"""
    boost = policy.weight_boost
    decay_factor = policy.freshness.get("decay_factor", 1.0) if policy.freshness else 1.0
    blocked = [b.lower() for b in policy.blocked_domains]
    trusted = [t.lower() for t in policy.trusted_domains]

    filtered: list[SearchResult] = []
    for r in results:
        domain = urlparse(r.url).netloc.lower()

        # 1. 屏蔽
        if any(_matches(domain, b) for b in blocked):
            continue

        # 2. 加权
        if any(_matches(domain, t) for t in trusted):
            r.score *= boost

        # 3. 时间衰减
        if r.published_at and decay_factor < 1.0:
            age_days = (datetime.utcnow() - r.published_at).days
            if age_days > 0:
                r.score *= decay_factor**min(age_days, 365)

        filtered.append(r)

    return sorted(filtered, key=lambda x: -x.score)
