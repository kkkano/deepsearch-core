# Blueprint（路线图蓝图）

> 从 v0.1（PoC）到 v1.0（生产）的完整演进路线。
> 生产级验收标准见 [`PRODUCTION_SPEC.md`](PRODUCTION_SPEC.md)，执行队列见 [`PRODUCTION_TODO.md`](PRODUCTION_TODO.md)。

---

## 总览

```
v0.1 (Now)    →  v0.2          →  v0.3            →  v0.5         →  v1.0
PoC 骨架        Steer + Eval     生态接入           企业特性        生产稳定
                                                                    
- 5 节点         - SQLite 事件     - Skill bundle    - 多租户        - SLA 99.9%
- Tavily         - Steer 中断     - Cherry Studio   - RBAC          - 多区域
- httpx 直连     - 100 题 eval    - Cloudflare       - 私有部署     - 完整 SDK
- MCP/HTTP/CLI                    Workers           - 审计日志
```

---

## 🚀 v0.1.0 — Foundation（PoC 骨架）

**目标**：跑通最小可用闭环，证明架构合理。

### 已完成
- [x] 仓库 + 目录结构
- [x] 顶层文档（README、ARCHITECTURE、BLUEPRINT、MCP_PROTOCOL、STEER_DESIGN、SOURCE_POLICY、DEPLOYMENT）
- [x] pyproject.toml + 5 依赖核心
- [x] Graph Runner（200 行）
- [x] 5 节点骨架（check_clarity / supervisor / planner / fan_out_research / critic / reporter）
- [x] httpx LLM client（OpenAI 兼容）
- [x] Tavily / Serper / Crossref / DuckDuckGo 搜索
- [x] Cohere reranker
- [x] HyDE + Query expansion
- [x] SQLite event store
- [x] MCP server（FastMCP）
- [x] HTTP server（FastAPI + WebSocket）
- [x] CLI（Typer）
- [x] 4 个 source policies（general / finance / tech / academic）
- [x] 5 个 examples
- [x] 单元测试基础

### 验收标准
```bash
# 1. CLI 跑得通
deepsearch quick "What's new in Claude 4.7?"

# 2. MCP 在 Claude Desktop 可调
claude mcp add deepsearch
# 在对话里说"用 deepsearch 调研 ..."

# 3. HTTP 流式可消费
curl -N http://localhost:8000/v1/search/deep -d '{"query": "..."}'

# 4. Steer 可中断
deepsearch deep "..." --async &
deepsearch steer <task_id> "重点看 X"
```

---

## 📦 v0.2.0 — Robustness（鲁棒性）

**目标**：能扛住真实负载，可对外发布。

### 计划
- [ ] **Eval Harness**：100 题中文 + 100 题英文测试集
  - 来源：FinSight 12 题 + ODR 范例 + 自建
  - 指标：准确率、召回率、引用准确性、平均延迟
- [ ] **Prompt Caching**：Anthropic API 上 system + tools cache（省 90%）
- [ ] **Speculative Search**：LLM 生成时后台预 fetch
- [ ] **Reranker 本地化**：BGE-reranker-v2-m3（无 Cohere 依赖也能用）
- [ ] **错误恢复**：单个 agent 挂了不影响整体（partial result）
- [ ] **限流**：per-key / per-IP rate limit
- [ ] **观测**：OpenTelemetry traces + Prometheus metrics
- [ ] **Docker 镜像**：多阶段构建，< 300MB
- [ ] **PyPI 发布**：`pip install deepsearch-core`
- [ ] **Demo 站点**：deepsearch.dev（Cloudflare Pages）

### 性能目标
| 指标 | v0.1 | v0.2 |
|------|------|------|
| `quick_search` P50 | 3s | 1.5s |
| `deep_search` 首字节 | 5s | 2s |
| `deep_search` P95 | 60s | 30s |
| Token 成本 / query | 10k | 3k |

---

## 🌍 v0.3.0 — Ecosystem（生态接入）

**目标**：让全 LLM 客户端都能 1 行装上。

### 计划
- [ ] **Skill bundle**：发布 Claude Code skill
- [ ] **OpenAI Function Calling 一键导出**：自动生成 schema
- [ ] **A2A endpoint**：Google Agent-to-Agent 协议
- [ ] **Cherry Studio 内置插件**：PR 上游
- [ ] **Cloudflare Workers** 部署模板（边缘 50ms）
- [ ] **Modal Labs** Serverless 模板
- [ ] **Vercel AI SDK** 适配
- [ ] **LangChain Tool** 包装（兼容老用户）
- [ ] **n8n / Zapier** workflow 节点
- [ ] **Telegram Bot** 模板（@your-bot 直接问）

### 部署矩阵
| 平台 | 形态 | 延迟 |
|------|------|------|
| Cloudflare Workers + R2 | HTTP API | 全球 50ms |
| Modal Labs | 长任务 | 启动 2s |
| Fly.io | VPS-like | 100ms |
| 自建 VPS | Docker compose | 主人当前方式 |

---

## 🏢 v0.5.0 — Enterprise（企业特性）

**目标**：做 SaaS 和 B 端私有化。

### 计划
- [ ] **多租户**：tenant_id 隔离 + 配额
- [ ] **RBAC**：Admin / User / Viewer
- [ ] **API Key 管理**：rotate / revoke / scoped
- [ ] **审计日志**：每个 query 谁问的、看了什么、引用了哪些源
- [ ] **私有数据源**：upload PDF / 内部知识库
- [ ] **Webhook 集成**：Slack / Discord / 企微
- [ ] **SOC2 ready**：加密存储、传输、密钥管理
- [ ] **私有部署 helm chart**：K8s 一键部署
- [ ] **企业版仪表板**：用量 / 成本 / 质量监控
- [ ] **微调**：基于 events 持续优化 prompt（DSPy / TextGrad）

---

## 🎯 v1.0.0 — Production（生产稳定）

**目标**：长期稳定运行，可作为公司核心服务。

### 计划
- [ ] SLA 99.9%（多区域 + 故障切换）
- [ ] 完整 SDK（Python / TypeScript / Go）
- [ ] 文档站点（mkdocs-material）
- [ ] 视频教程（5 集）
- [ ] 社区（Discord / 微信群）
- [ ] 商业模式：开源核心 + 托管 API + 企业版

---

## 💡 长期想法（v2.0+）

| 想法 | 说明 |
|------|------|
| **多模态** | PDF/图表/视频转文本分析 |
| **Browser Use** | Anthropic Computer Use 抓需登录的源 |
| **GraphRAG** | 实体关系图 + 跨文档 reasoning |
| **持续学习** | 用 events 做 RLAIF 微调 |
| **Agent 团队** | 模拟分析师团队（量化 + 行业 + 宏观）|
| **离线模式** | 全本地 LLM + 本地搜索（Ollama + SearXNG）|
| **可视化研究 IDE** | 像 Jupyter 但是 agent 中心 |

---

## 📅 时间表（建议）

| 版本 | 时间 | 里程碑 |
|------|------|--------|
| v0.1 | 2026-04-25 | PoC 完成 |
| v0.1.1 | 2026-05-10 | bug fix + Demo 视频 |
| v0.2 | 2026-06 | PyPI 发布 + 100 stars |
| v0.3 | 2026-08 | Skill / Cherry Studio 上线 |
| v0.5 | 2026-11 | 第一个企业客户 |
| v1.0 | 2027-03 | 长期稳定 |

---

## 🤝 贡献机会

| 优先级 | 任务 | 难度 |
|--------|------|------|
| P0 | 增加搜索引擎（Brave / SearXNG / Bing） | ⭐⭐ |
| P0 | 新 source policy（legal / medical） | ⭐ |
| P1 | TypeScript SDK | ⭐⭐⭐ |
| P1 | Browser Use 集成 | ⭐⭐⭐⭐ |
| P2 | 多模态扩展 | ⭐⭐⭐⭐⭐ |
| P2 | DSPy 自动 prompt 优化 | ⭐⭐⭐⭐⭐ |
