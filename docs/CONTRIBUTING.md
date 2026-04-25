# Contributing to deepsearch-core

> 欢迎贡献！本指南涵盖：开发环境、代码风格、PR 流程、贡献类型。

---

## 1. 开发环境

```bash
# Fork + clone
git clone https://github.com/<你的用户名>/deepsearch-core
cd deepsearch-core

# 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 同步全套依赖
uv sync --all-extras

# 配置 API keys（用于跑测试）
cp .env.example .env
# 编辑 .env

# 跑测试
uv run pytest

# 跑 lint
uv run ruff check .
uv run mypy deepsearch_core/
```

---

## 2. 代码风格

### 2.1 强制规则

- **行宽** 100 字符（ruff 默认）
- **Type hints** 强制（mypy strict）
- **Docstring** Google 风格
- **No mutation**：`state.copy(update={...})` 而非 `state.x = ...`

### 2.2 命名

| 类型 | 命名 |
|------|------|
| Class | `PascalCase` |
| 函数 | `snake_case` |
| 常量 | `UPPER_SNAKE` |
| 私有 | `_leading_underscore` |
| 节点函数 | `xxx_node`（如 `planner_node`） |
| 测试 | `test_<功能>_<场景>` |

### 2.3 imports

```python
# 标准库
from __future__ import annotations
import asyncio
from datetime import datetime
from pathlib import Path

# 第三方
import httpx
from pydantic import BaseModel

# 本项目
from deepsearch_core.engine import State
from deepsearch_core.llm import LLMClient
```

---

## 3. PR 流程

### 3.1 创建分支

```bash
git checkout -b feat/add-brave-search
```

分支命名约定：
- `feat/xxx` 新功能
- `fix/xxx` bug 修复
- `docs/xxx` 文档
- `refactor/xxx` 重构
- `test/xxx` 测试
- `policy/xxx` 新增 source policy

### 3.2 Commit Message

[Conventional Commits](https://www.conventionalcommits.org/) 格式：

```
feat(search): add Brave Search engine

- Implement BraveSearch class
- Add to search registry
- Cover with 3 unit tests

Closes #42
```

类型：`feat / fix / docs / refactor / test / chore / perf / ci`

### 3.3 Pre-PR 检查

```bash
# 浮浮酱推荐的全套检查
uv run ruff check . --fix
uv run ruff format .
uv run mypy deepsearch_core/
uv run pytest --cov=deepsearch_core --cov-report=term-missing
```

覆盖率目标：**新代码 ≥ 80%**。

### 3.4 PR 描述模板

```markdown
## Summary
What does this PR do?

## Motivation
Why is this needed?

## Changes
- Change 1
- Change 2

## Tests
- [ ] Unit tests added
- [ ] Integration tests added
- [ ] Eval cases added (if applicable)

## Eval Results (if behavior changes)
[Paste eval report]

## Checklist
- [ ] Code follows style guide
- [ ] Tests pass locally
- [ ] Docs updated
- [ ] No breaking changes (or noted in CHANGELOG)
```

---

## 4. 贡献类型

### 4.1 增加搜索引擎（最常见）

```python
# deepsearch_core/search/brave.py
from .base import BaseSearch, SearchResult

class BraveSearch(BaseSearch):
    name = "brave"
    
    def __init__(self, api_key: str):
        self.client = httpx.AsyncClient(
            base_url="https://api.search.brave.com",
            headers={"X-Subscription-Token": api_key},
        )
    
    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        resp = await self.client.get("/res/v1/web/search", params={
            "q": query, "count": max_results,
        })
        data = resp.json()
        return [
            SearchResult(
                url=r["url"],
                title=r["title"],
                snippet=r["description"],
                score=1.0 - i * 0.05,
            )
            for i, r in enumerate(data["web"]["results"])
        ]
```

```python
# tests/unit/test_search_brave.py
import pytest
from deepsearch_core.search.brave import BraveSearch

@pytest.mark.asyncio
async def test_brave_search_returns_results(mock_brave_response):
    search = BraveSearch(api_key="fake")
    results = await search.search("test query")
    assert len(results) > 0
    assert results[0].url.startswith("http")
```

### 4.2 增加 Source Policy

见 [`SOURCE_POLICY.md` § 8](SOURCE_POLICY.md#8-贡献新-policy)。

### 4.3 增加 Reranker

```python
# deepsearch_core/reranker/jina.py
from .base import BaseReranker, RerankResult

class JinaReranker(BaseReranker):
    name = "jina"
    
    async def rerank(self, query: str, docs: list[str], top_k: int = 5) -> list[RerankResult]:
        # 实现
        ...
```

### 4.4 增加新协议适配层

仿 `deepsearch_core/adapters/{mcp,http,cli}/` 结构，新增一个目录，例如 `adapters/grpc/`。

### 4.5 文档贡献

- 修正错别字
- 翻译（计划：中英日韩）
- 写教程 / 博客文章 → 加到 `docs/blog/`

### 4.6 Eval Cases

为 `eval/datasets/*.jsonl` 加新测试用例。每个领域至少 5 题：

```jsonl
{"id": "med001", "query": "Latest GLP-1 weight loss drug efficacy", "policy": "medical", "expected_facts": ["semaglutide", "tirzepatide"], "expected_min_sources": 3}
```

---

## 5. 测试规范

### 5.1 三层金字塔

```
        ┌──────────────────┐
        │  E2E (10%)       │  跑真实 LLM + 真实搜索
        ├──────────────────┤
        │ Integration(20%) │  跑真实组件，mock 外部 API
        ├──────────────────┤
        │  Unit (70%)      │  纯函数 / 类，全 mock
        └──────────────────┘
```

### 5.2 Mock LLM

```python
# tests/conftest.py
import pytest
from unittest.mock import AsyncMock

@pytest.fixture
def mock_llm():
    client = AsyncMock()
    client.complete = AsyncMock(return_value="mocked response")
    return client
```

### 5.3 Mock httpx

```python
import respx

@pytest.mark.asyncio
async def test_tavily_search(respx_mock):
    respx_mock.post("https://api.tavily.com/search").respond(
        json={"results": [{"url": "https://...", "title": "..."}]}
    )
    # ...
```

---

## 6. 性能贡献

如果你的 PR 涉及性能改进，请附上 benchmark：

```bash
uv run python scripts/benchmark.py --before main --after my-branch
```

输出示例：
```
Benchmark: deep_search depth=3 finance policy
Before:  P50=24s P95=42s tokens=8.2k
After:   P50=18s P95=31s tokens=6.5k
Delta:   -25% latency, -21% tokens
```

---

## 7. 文档贡献

文档源在 `docs/`，使用 markdown。规则：

- 一级标题用 `#`，二级 `##`，最多到四级
- 代码块标注语言
- 表格对齐
- Mermaid 图：```mermaid 围栏
- 互链用相对路径：`[xxx](OTHER.md#section)`

---

## 8. 安全披露

发现安全问题？**不要**开 public issue。

请发邮件到 `657394554@qq.com`，主题加 `[SECURITY]`。

我们承诺 7 天内回复。

---

## 9. 行为准则

- 友好、专业、包容
- 对人友善，对代码严格
- 接受批评、给予反馈
- 拒绝歧视、骚扰

---

## 10. 联系方式

- GitHub Issues: bug / 新功能讨论
- GitHub Discussions: 想法交流
- 微信群（计划中）: 中文社区
