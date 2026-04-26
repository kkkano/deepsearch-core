# Production Spec

> 本文定义 deepsearch-core 从 PoC 进入生产级服务的验收标准。  
> 原则：能被长期运行、能被审计、能被回滚、能被度量，才叫生产级。

## 1. 当前结论

deepsearch-core 当前状态是 alpha / PoC，可在配置稳定搜索源和 LLM endpoint 后完成 quick search 与 deep search，但尚未达到生产级。

已验证能力：

- Python 包、CLI、HTTP adapter、MCP stdio adapter 可以加载。
- 单元测试主干可通过。
- Tavily + OpenAI-compatible LLM 可跑通 quick search。
- deep search 可完成 planner -> fan_out -> critic -> reporter 主链路。
- SQLite event store 已具备基础事件溯源能力。

主要差距：

- 搜索源可靠性、来源质量排序、reader 超时隔离仍不足。
- eval 仍是 smoke 级，不能证明事实准确性和引用准确性。
- 观测、限流、认证、租户隔离、部署安全、数据保留策略缺失。
- 持久化仍以 SQLite 为主，不适合多实例水平扩展。
- LLM provider 兼容仅覆盖 OpenAI-compatible 常见形态，未形成完整 provider contract。

## 2. 生产级定义

生产级不是“能跑”，而是满足以下条件：

```text
correct enough  + observable enough + safe enough + operable enough
```

最低门槛：

- 正确性：回答必须由可追溯证据支持，不能把检索失败伪装成结论。
- 稳定性：单个搜索源、reader、LLM 节点失败不得拖垮整个任务。
- 可观测：每个 run 能看到耗时、token、来源、错误、重试、节点状态。
- 安全性：API key、用户 query、source content、event payload 有明确边界和脱敏策略。
- 可运维：可部署、可回滚、可限流、可健康检查、可容量规划。

## 3. SLO 与质量门槛

v1.0 发布必须达到：

- Availability：HTTP API 月可用性 >= 99.9%。
- quick_search P50 <= 8s，P95 <= 20s。
- deep_search P50 <= 60s，P95 <= 180s。
- quick_search 成功率 >= 98%，deep_search 成功率 >= 95%。
- eval factual accuracy >= 0.85。
- eval source coverage >= 0.80。
- eval citation support accuracy >= 0.85。
- 每个 completed run 必须至少包含一个 report、citation list、token usage、event trace。
- failed / timeout / cancelled run 必须有稳定 `error: str | null`。

v0.2 可接受的 hardening 门槛：

- quick_search P95 <= 30s。
- deep_search P95 <= 240s。
- general / tech / finance smoke eval 总通过率 >= 70%。
- 所有 adapter 的 task lifecycle 行为一致。

## 4. API Contract

所有公开接口必须保持以下响应形态稳定。

### 4.1 quick_search

输入：

```json
{
  "query": "string",
  "policy": "general | finance | tech | academic | custom",
  "max_results": 5,
  "timeout_seconds": 30
}
```

输出：

```json
{
  "run_id": "run_xxx",
  "status": "completed | failed | timeout | cancelled",
  "elapsed_seconds": 0.0,
  "report": {
    "summary": "string",
    "body_markdown": "string",
    "citations": []
  },
  "evidence_count": 0,
  "citations": [],
  "token_usage": {},
  "error": null
}
```

要求：

- `status=completed` 不代表答案一定正确，只代表流程完成；质量由 eval 和 confidence 负责。
- 无证据时必须明确说没有足够来源，不能编造。
- `error` 只能是 `null` 或字符串。

### 4.2 deep_search

同步接口只用于本地 SDK 和调试；生产推荐异步：

```text
POST /v1/search/deep/async
GET  /v1/runs/{run_id}/poll
GET  /v1/runs/{run_id}/stream
POST /v1/runs/{run_id}/steer
DELETE /v1/runs/{run_id}
```

要求：

- `start` 必须在返回 `task_id` 前持久化 run 行。
- `poll` 必须支持 completed 与 running 两种状态。
- `stream` 必须能在 run 结束时可靠输出 `[DONE]`。
- `steer` 必须区分 accepted / rejected / already_finished。
- `cancel` 必须区分 not_found / already_finished / cancelled。

## 5. LLM Provider Contract

目标：OpenAI、Gemini、Claude compatible endpoint、国产 OpenAI-compatible endpoint 都可接入。

必须支持：

- `chat.completions` 非流式调用。
- `model`、`messages`、`temperature`、`max_tokens` 基础字段。
- provider 不支持 `response_format` 时自动降级重试。
- JSON 输出兼容对象、数组、markdown fenced JSON、文本包裹 JSON。
- token usage 缺失时不能导致流程失败。
- 4xx/5xx 必须转成稳定 `LLMError`，并带 status code 和截断 body。

必须补齐：

- provider capability 探测。
- provider-specific timeout / retry / rate limit 配置。
- schema repair：JSON 解析失败后可用低成本模型或规则修复一次。
- prompt budget 管理：节点按剩余时间和 token 预算裁剪输入。

## 6. Search And Retrieval Contract

生产环境必须至少配置两个稳定搜索源：

- 主搜索：Tavily / Serper / Brave / Bing / Exa 之一。
- 兜底搜索：SearXNG / DuckDuckGo / 自建 search proxy 之一。

要求：

- 单搜索源失败只降级，不失败整个 run。
- 搜索结果必须记录 engine、query、latency、status、result_count。
- policy 必须能按 domain 做 boost / block / freshness decay。
- reader 只做增强，reader 失败不得丢弃 snippet。
- Crossref 只能在 academic 或明确需要论文时启用，不能污染 general / tech 默认召回。

来源质量分层：

- Tier 0：官方文档、官方博客、GitHub org、监管机构、原始论文。
- Tier 1：权威媒体、云厂商文档、行业数据库。
- Tier 2：技术博客、教程、社区讨论。
- Tier 3：内容农场、低可信聚合页、SEO 页面。

默认报告应优先引用 Tier 0 / Tier 1。

## 7. Eval Contract

eval 必须从 smoke 走向质量门禁。

数据集：

- general：不少于 50 条。
- tech：不少于 50 条。
- finance：不少于 50 条。
- academic：不少于 30 条。
- adversarial：不少于 30 条。
- multilingual：不少于 30 条。

指标：

- factual accuracy：回答是否覆盖 expected facts。
- source coverage：引用来源是否覆盖 expected domains。
- citation support：引用是否真的支持对应 claim。
- latency：P50 / P95。
- cost：prompt / completion tokens。
- failure taxonomy：失败原因归因到 LLM / search / reader / timeout / parse / policy。

CI 策略：

- 每个 PR 跑 smoke subset。
- main 分支每日跑 full eval。
- 若 factual/source/citation 任一指标下降超过阈值，阻止发布。

## 8. Observability Contract

每个 run 必须具备：

- run_id。
- user / tenant / api_key hash。
- node spans。
- LLM latency / token / model / provider。
- search latency / engine / query / result_count。
- reader latency / status。
- reranker latency / top_k。
- final status / error。

必须暴露：

- `/health`：进程存活。
- `/ready`：依赖可用，包含 LLM/search/store。
- `/metrics`：Prometheus 格式。
- OpenTelemetry traces。
- event replay API。

日志要求：

- JSON structured logs。
- 默认不记录明文 API key。
- query 与 source content 可按配置脱敏或采样。

## 9. Security Contract

必须具备：

- API key 鉴权。
- per-key rate limit。
- request body size limit。
- task timeout hard cap。
- outbound domain allow/deny list。
- prompt injection source tagging。
- event payload 脱敏。
- secret 不进入 git、不进入响应、不进入普通日志。
- CORS 默认拒绝 `*`，本地开发可显式开启。

企业版本必须具备：

- tenant_id 隔离。
- scoped API keys。
- RBAC。
- audit log。
- retention policy。
- export / delete 用户数据能力。

## 10. Persistence Contract

v0.2 可继续使用 SQLite，但必须明确为单实例模式。

生产多实例需要：

- PostgreSQL 存储 runs/events/steer_commands。
- Redis 或 Postgres advisory lock 管理 task concurrency。
- object storage 保存长报告与大 source payload。
- migration 工具和 schema version。
- event schema versioning。

数据保留：

- 默认 events 保留 30 天。
- report 和 citations 保留 90 天。
- 可配置永久审计模式。
- 支持按 tenant 删除。

## 11. Deployment Contract

必须提供：

- Dockerfile 多阶段构建。
- docker-compose production profile。
- healthcheck。
- non-root user。
- read-only filesystem 兼容。
- graceful shutdown。
- env schema 文档。
- systemd 示例。
- reverse proxy 示例。

Kubernetes / Helm 进入 v0.5：

- Deployment。
- Service。
- Ingress。
- Secret。
- ConfigMap。
- HPA。
- PodDisruptionBudget。

## 12. Release Gates

任何生产发布必须通过：

```bash
python -m ruff check .
python -m mypy deepsearch_core
python -m pytest
python eval/runner.py --dataset smoke
python scripts/benchmark.py --profile production-smoke
```

人工检查：

- API contract 是否破坏。
- 新增配置是否有文档。
- 新增 provider 是否有真实 smoke。
- 新增搜索源是否有降级路径。
- 数据库 migration 是否可重复执行。
- CHANGELOG 是否记录。

## 13. Non-goals

v1.0 之前不做：

- 通用浏览器自动操作。
- 完整多模态理解。
- GraphRAG 持久知识图谱。
- 自训练模型。
- 复杂前端研究 IDE。

这些可以在核心稳定后作为 v2.0 方向。

## 14. ADR

Decision：

deepsearch-core 的生产化路线优先加固现有核心，而不是引入 LangGraph / LangChain 重写。

Rationale：

- 当前核心价值是协议无关、状态机可控、事件可回放。
- 生产问题主要在边界：provider 兼容、搜索可靠性、eval、观测、安全、部署。
- 重写会增加不可控复杂度，不能直接提高正确性。

Consequences：

- 短期内继续维护手写 runner。
- 必须补齐严肃的测试、eval 和 observability。
- 只有当状态机复杂度超过本项目可维护边界时，才重新评估工作流框架。
