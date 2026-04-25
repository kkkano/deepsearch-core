# deepsearch-core

> **A protocol-agnostic deep research engine. One core, many adapters: MCP / HTTP / CLI / SDK.**
> 协议无关的深度研究引擎，一份核心、多种适配。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-compatible-brightgreen)](https://modelcontextprotocol.io/)

---

## ✨ Why deepsearch-core

| 痛点 | 现状 | deepsearch-core 解法 |
|------|------|---------------------|
| Deep research 跑得慢，30-120s 超时 | 串行 self-RAG | **Multi-Agent Fan-Out** + Speculative Search |
| Agent 跑偏不能干预 | Fire-and-forget | **Steer 中断**：随时注入新指令 + 重规划 |
| 调用方式绑死单一客户端 | LangChain SDK only | **MCP / HTTP / CLI / SDK 四协议适配** |
| 召回质量差 | 单 query + 单引擎 | **HyDE + Query Expansion + Cohere Reranker** |
| 黑盒不可审计 | 日志靠 print | **SQLite 事件溯源**，完整 replay |
| 不同领域用不同知识 | 通用 prompt | **Source Policy YAML**：finance / tech / academic 各自配置 |
| LangGraph 启动慢、bug 多 | 重 SDK 依赖 | **零 LangGraph 依赖**，200 行手写极简引擎 |

---

## 🚀 三种使用方式

### 1. CLI（最朴素）

```bash
pip install deepsearch-core
deepsearch quick "腾讯港股最新风险"
deepsearch deep "美联储 2026 政策展望" --depth 3 --policy finance --stream
```

### 2. MCP Server（推荐，可被 Claude Desktop / Cursor / Cline 直接调）

```bash
# 一行安装到 Claude Code
claude mcp add deepsearch -- python -m deepsearch_core.adapters.mcp
```

> ⚠️ **v0.1.x**: MCP server 仅支持 stdio transport（适合本地客户端）。
> Cherry Studio / 远程客户端请使用下面的 HTTP API（`/v1/search/*` 路由），
> MCP 的 HTTP/SSE transport 计划于 v0.2 提供。

然后在 Claude Desktop 的对话里：
> 「帮我深度研究下 OpenAI 最近的开源模型策略」
> *Claude 自动调用 `deepsearch.start_deep_search` + `poll_search`，并支持 `steer` 中途干预*

### 3. HTTP API（兜底，所有平台都能用）

```python
import httpx, json

with httpx.stream("POST", "http://localhost:8000/v1/search/deep",
                 json={"query": "...", "depth": 3, "policy": "finance"}) as r:
    for line in r.iter_lines():
        print(json.loads(line))
```

### 4. Python SDK

```python
from deepsearch_core import DeepSearch

async with DeepSearch() as ds:
    async for chunk in ds.stream("query", depth=3):
        print(chunk.partial_result)
```

---

## 🏗️ 架构

```
                 ┌────────────────────────────────────────────┐
                 │   Core Engine (~500 LOC, no LangGraph)     │
                 │   ──────────────────────────────────────   │
                 │   • Graph Runner with Steer Interrupt      │
                 │   • Multi-Agent Fan-Out (N parallel)       │
                 │   • Self-Reflection Loop (max_steps)       │
                 │   • Cohere Reranker + HyDE                 │
                 │   • Streaming Result Bus                   │
                 │   • SQLite Event Sourcing                  │
                 └─────┬──────────────────────────────────────┘
                       │
       ┌───────┬───────┼───────┬─────────┬─────────┐
       ▼       ▼       ▼       ▼         ▼         ▼
   ┌──────┐┌──────┐┌─────┐┌──────┐┌─────────┐┌────────┐
   │ MCP  ││HTTP+ ││ CLI ││ SDK  ││ Skill   ││  A2A   │
   │Server││ SSE  ││     ││py/ts ││ Bundle  ││ Agent  │
   └──┬───┘└──┬───┘└──┬──┘└──┬───┘└────┬────┘└────┬───┘
      ▼      ▼       ▼      ▼          ▼          ▼
   Claude Cherry  Claude  自研      Claude     Google
   Desktop Studio Code   Agent      Code        A2A
   Cursor 小龙虾  Bash     项目    subagent   生态
   Cline ufomiao 用户             FinSight
```

详细架构请见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

---

## 🎯 核心特性

### 1. Steer 中断（杀手功能）

```
传统 deep research：用户问 → agent 跑 30s → 返回（不可干预）
deepsearch-core：用户问 → agent 跑 → 用户随时说"重点看 X" → 中断 → 重规划
```

**API**：
```bash
# 启动一个深度搜索
$ deepsearch deep "美联储 2026 政策" --async
{"task_id": "run_abc123", "steer_url": "..."}

# 中途干预
$ deepsearch steer run_abc123 "重点关注 QT 缩表节奏"
{"accepted": true, "applied_at_step": 3}
```

详见 [`docs/STEER_DESIGN.md`](docs/STEER_DESIGN.md)。

### 2. Multi-Agent Fan-Out

```
                    ┌─→ Agent-1: 官方信源 ─┐
plan(LLM) → 拆 N query ─→ Agent-2: 新闻媒体 ─┼─→ Critic Agent
                    ├─→ Agent-3: 社区论坛 ─┤    (反方论据 + 矛盾检测)
                    └─→ Agent-N: 学术论文 ─┘    │
                                                 ▼
                                          Cohere Reranker
                                                 │
                                                 ▼
                                          Streaming Output
```

### 3. Source Policy（领域特化）

```yaml
# deepsearch_core/policy/policies/finance.yml
name: finance
trusted_domains:
  - sec.gov
  - bloomberg.com
  - federalreserve.gov
  weight_boost: 2.0
blocked_domains:
  - reddit.com
  - quora.com
search_keywords:
  - "10-K filing"
  - "FOMC minutes"
academic_sources:
  - crossref
  - ssrn
```

详见 [`docs/SOURCE_POLICY.md`](docs/SOURCE_POLICY.md)。

### 4. 事件溯源 + 可回放

```python
from deepsearch_core.store import EventStore

store = EventStore("runs.db")
events = store.replay(run_id="run_abc123")
for e in events:
    print(e.timestamp, e.type, e.payload)
# llm_call / tool_call / state_change / steer_received
```

详见 [`docs/ARCHITECTURE.md#event-sourcing`](docs/ARCHITECTURE.md#event-sourcing)。

### 5. 节点级模型配置（成本优化）

```env
# .env
LLM_BASE_URL=https://api.anthropic.com/v1
LLM_API_KEY=sk-...
SUPERVISOR_MODEL=claude-sonnet-4-6
PLANNER_MODEL=claude-haiku-4-5      # 规划用 haiku，省 3x
RESEARCHER_MODEL=claude-haiku-4-5   # 大量调用，必须快
CRITIC_MODEL=claude-sonnet-4-6
REPORTER_MODEL=claude-opus-4-7      # 最终报告用 opus
```

---

## 📚 完整文档

| 文档 | 内容 |
|------|------|
| [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 架构详解：5 节点 + Fan-Out + 事件溯源 |
| [`BLUEPRINT.md`](docs/BLUEPRINT.md) | 路线图：v0.1 → v1.0 的演进计划 |
| [`MCP_PROTOCOL.md`](docs/MCP_PROTOCOL.md) | MCP server 工具/资源/提示词设计 |
| [`STEER_DESIGN.md`](docs/STEER_DESIGN.md) | Steer 中断机制：状态机 + 协议 |
| [`SOURCE_POLICY.md`](docs/SOURCE_POLICY.md) | 数据源策略：YAML 配置 + 自定义领域 |
| [`DEPLOYMENT.md`](docs/DEPLOYMENT.md) | 部署指南：Docker / Modal / Cloudflare Workers |

---

## 🛠️ 开发

```bash
# 用 uv（推荐）
git clone https://github.com/kkkano/deepsearch-core
cd deepsearch-core
uv sync
uv run pytest

# 或者 pip
pip install -e ".[dev]"
pytest tests/ -v --cov
```

---

## 📦 部署形态

| 部署方式 | 适合场景 | 命令 |
|---------|---------|------|
| **本地 stdio MCP** | Claude Desktop / Cursor 个人使用 | `claude mcp add ...` |
| **HTTP server** | Cherry Studio / 小龙虾 / 多用户共享 | `uvicorn` |
| **Docker** | 私有部署 | `docker compose up` |
| **Cloudflare Workers** | 全球边缘 < 50ms | 见 [`DEPLOYMENT.md`](docs/DEPLOYMENT.md) |
| **Modal Labs** | Serverless 长任务 | 见 [`DEPLOYMENT.md`](docs/DEPLOYMENT.md) |

---

## 🤝 致谢 & 灵感来源

- [**OpenDeepResearch**](https://github.com/DesignOps6ix9/OpenDeepResearch) — Steer 中断机制 + 事件溯源 + 极简哲学
- [**Anthropic MCP**](https://modelcontextprotocol.io/) — 协议规范
- [**GPT Researcher**](https://github.com/assafelovic/gpt-researcher) — 早期 deep research 范式

---

## 📄 License

MIT © 2026 deepsearch-core contributors
