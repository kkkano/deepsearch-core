# Source Policy（数据源策略）

> 不同领域有不同的可信来源。Source Policy 通过 YAML 配置实现领域特化。

---

## 1. 为什么需要 Source Policy

```
通用搜索：「腾讯财报」→ 可能返回 reddit/quora/营销号 (低质量)
金融特化：「腾讯财报」→ 优先 sec.gov / hkex.com.hk / bloomberg / reuters
```

不同领域有不同的：
- **可信域名**（trusted）：加权
- **屏蔽域名**（blocked）：直接过滤
- **学术源**（academic）：是否启用 Crossref / SSRN / arXiv
- **关键词增强**（keywords）：自动追加专业术语
- **prompt 调优**（领域特化的 system prompt 片段）

---

## 2. Policy 文件结构

```yaml
# deepsearch_core/policy/policies/finance.yml

# ---- 元信息 ----
name: finance
display_name: "金融研究"
description: "Financial deep research with SEC, FOMC, Bloomberg etc."
version: 1
language: "zh-CN, en-US"

# ---- 域名规则 ----
trusted_domains:
  - sec.gov
  - federalreserve.gov
  - bls.gov
  - bloomberg.com
  - reuters.com
  - ft.com
  - wsj.com
  - hkex.com.hk            # 港交所
  - sse.com.cn             # 上交所
  - eastmoney.com          # 东方财富
  - cninfo.com.cn          # 巨潮资讯
weight_boost: 2.0          # 这些域名的检索得分 ×2.0

blocked_domains:
  - reddit.com
  - quora.com
  - "*.spam-finance.*"
  - "*.crypto-pump.*"

# ---- 学术源 ----
academic_sources:
  enabled: true
  crossref: true
  ssrn: true
  arxiv: false              # 金融领域 arxiv 较少
  semantic_scholar: false

# ---- 搜索关键词增强 ----
search_keywords:            # 检测到这些关键词时自动追加
  - keyword: "财报"
    augment: ["10-Q", "10-K", "annual report"]
  - keyword: "美联储"
    augment: ["FOMC minutes", "Fed dot plot"]
  - keyword: "估值"
    augment: ["P/E", "EV/EBITDA", "DCF"]

# ---- LLM Prompt 调优 ----
prompt_addons:
  researcher: |
    Focus on:
    - Quantitative data (revenue, margin, growth %)
    - Forward guidance from earnings calls
    - Analyst consensus from credible sources
    - Macro context (interest rates, FX, commodities)
    
    Always cite filing date and source domain.
    Never speculate beyond what filings state.
  
  critic: |
    Pay special attention to:
    - Conflicts between SEC filings vs analyst opinions
    - Survivorship bias in performance claims
    - Look-ahead bias in backtests
    - Forward-looking statements with regulatory disclaimers
  
  reporter: |
    Format final report with:
    - Executive Summary (3 bullets)
    - Financial Highlights (table)
    - Key Risks (numbered list)
    - Sources (with filing dates)

# ---- 时间敏感度 ----
freshness:
  prefer_within_days: 30      # 优先 30 天内的内容
  decay_factor: 0.9           # 越老越降权

# ---- 引用要求 ----
citation:
  min_sources: 3
  prefer_primary: true        # 一手来源优先（filings > 报道）
  require_filing_date: true   # 金融场景必须有发布日期
```

---

## 3. 内置 Policies

### 3.1 `general.yml`（默认）
```yaml
name: general
trusted_domains:
  - wikipedia.org
  - github.com
  weight_boost: 1.5
blocked_domains:
  - "*.spam.*"
academic_sources:
  enabled: false
```

### 3.2 `finance.yml`
见上文示例（完整版）。

### 3.3 `tech.yml`
```yaml
name: tech
trusted_domains:
  - github.com
  - arxiv.org
  - openai.com
  - anthropic.com
  - news.ycombinator.com
  - blog.cloudflare.com
  weight_boost: 2.0
blocked_domains:
  - reddit.com  # 可选
  - "*.medium-spam.*"
academic_sources:
  enabled: true
  arxiv: true
  semantic_scholar: true
search_keywords:
  - keyword: "benchmark"
    augment: ["evaluation", "leaderboard"]
prompt_addons:
  researcher: |
    Prefer official documentation, GitHub repos, and arxiv papers.
    Cite specific commit hashes and paper arxiv IDs when relevant.
```

### 3.4 `academic.yml`
```yaml
name: academic
trusted_domains:
  - arxiv.org
  - nature.com
  - science.org
  - acm.org
  - ieee.org
  - jstor.org
  - sciencedirect.com
  - springer.com
  weight_boost: 3.0
academic_sources:
  enabled: true
  crossref: true
  arxiv: true
  semantic_scholar: true
  ssrn: true
prompt_addons:
  researcher: |
    Strict academic mode. Only cite:
    - Peer-reviewed journals
    - Conference proceedings
    - arxiv preprints (with caveat)
    - Books from academic publishers
    
    Always include DOI when available.
    Use IEEE / APA citation format.
citation:
  format: "ieee"  # or "apa" / "chicago"
  require_doi: true
```

---

## 4. 加载与匹配

### 4.1 显式选择

```bash
# CLI
deepsearch deep "..." --policy finance

# Python
ds = DeepSearch(policy="finance")

# MCP tool args
{"query": "...", "policy": "finance"}
```

### 4.2 自动检测（heuristic）

```python
# deepsearch_core/policy/auto_detect.py

FINANCE_KEYWORDS = ["股", "财报", "估值", "美联储", "FOMC", "earnings", "P/E", ...]
TECH_KEYWORDS = ["AI", "LLM", "model", "framework", "framework", ...]

def auto_detect_policy(query: str) -> str:
    if any(kw in query for kw in FINANCE_KEYWORDS):
        return "finance"
    if any(kw in query for kw in TECH_KEYWORDS):
        return "tech"
    return "general"
```

### 4.3 用户自定义 policy

用户可以在 `~/.deepsearch/policies/my-domain.yml` 放自己的 policy：

```bash
deepsearch deep "..." --policy ~/.deepsearch/policies/my-legal.yml
```

或者 inline 传 dict：

```python
ds = DeepSearch(policy={
    "name": "custom",
    "trusted_domains": ["example.com"],
    "weight_boost": 5.0,
})
```

---

## 5. 实现：PolicyLoader

```python
# deepsearch_core/policy/loader.py

from pathlib import Path
import yaml
from pydantic import BaseModel

class PolicyConfig(BaseModel):
    name: str
    trusted_domains: list[str] = []
    weight_boost: float = 2.0
    blocked_domains: list[str] = []
    academic_sources: dict = {"enabled": False}
    search_keywords: list[dict] = []
    prompt_addons: dict[str, str] = {}
    freshness: dict = {}
    citation: dict = {}

class PolicyLoader:
    def __init__(self, policy_dir: Path | None = None):
        self.policy_dir = policy_dir or Path(__file__).parent / "policies"
        self._cache: dict[str, PolicyConfig] = {}

    def load(self, name_or_path: str) -> PolicyConfig:
        if name_or_path in self._cache:
            return self._cache[name_or_path]
        
        # 路径还是名字？
        if Path(name_or_path).exists():
            path = Path(name_or_path)
        else:
            path = self.policy_dir / f"{name_or_path}.yml"
        
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        cfg = PolicyConfig(**data)
        self._cache[name_or_path] = cfg
        return cfg
```

---

## 6. 应用：检索时的过滤与加权

```python
# deepsearch_core/retrieval/filter.py

def apply_policy_filter(
    results: list[SearchResult],
    policy: PolicyConfig,
) -> list[SearchResult]:
    filtered = []
    for r in results:
        # 1. 屏蔽
        if any(matches_pattern(r.url, b) for b in policy.blocked_domains):
            continue
        
        # 2. 加权
        if any(matches_pattern(r.url, t) for t in policy.trusted_domains):
            r.score *= policy.weight_boost
        
        # 3. 时间衰减
        if policy.freshness:
            age_days = (datetime.now() - r.published_at).days
            decay = policy.freshness.get("decay_factor", 1.0) ** age_days
            r.score *= decay
        
        filtered.append(r)
    
    return sorted(filtered, key=lambda x: -x.score)


def matches_pattern(url: str, pattern: str) -> bool:
    """支持 *.example.com / example.com 通配。"""
    import fnmatch
    domain = urlparse(url).netloc
    return fnmatch.fnmatch(domain, pattern)
```

---

## 7. Policy + Prompt 注入

policy 的 `prompt_addons` 会自动拼接到对应节点的 system prompt：

```python
# deepsearch_core/agents/researcher.py

async def researcher_node(state: State) -> tuple[State, str]:
    base_prompt = RESEARCHER_PROMPT
    addon = state.config.policy.prompt_addons.get("researcher", "")
    
    full_prompt = f"{base_prompt}\n\n## Domain-specific guidance\n{addon}"
    # ...
```

---

## 8. 贡献新 Policy

欢迎主人/社区贡献新 policy！流程：

1. 在 `deepsearch_core/policy/policies/` 加 `<your-domain>.yml`
2. 在 `tests/unit/test_policy.py` 加测试用例（至少 3 个 query 验证）
3. 在 `docs/SOURCE_POLICY.md`（本文）4 节加说明
4. 提 PR

### 计划中的 Policy

| 名字 | 适用 |
|------|------|
| `legal` | 法律研究（trusted: 法院判例、法规库） |
| `medical` | 医学研究（trusted: PubMed、cochrane） |
| `news` | 时事新闻（trusted: 主流媒体；屏蔽: 内容农场） |
| `chinese-finance` | 中国 A 股专版（巨潮、东方财富、雪球） |
| `crypto` | 加密货币（trusted: 项目方文档、官方推特；屏蔽: pump-and-dump 站） |
| `gov-policy` | 政策研究（trusted: 各国政府官网） |

---

## 9. 安全考量

| 风险 | 对策 |
|------|------|
| 用户上传恶意 policy 注入 prompt | 加载时 schema 验证 + 长度限制 |
| trusted_domains 让钓鱼站获信任 | 显式 confirm 自定义 policy 时警告用户 |
| 学术源被滥用爬取 | Crossref 走 mailto 礼貌池，arxiv 限频 |
