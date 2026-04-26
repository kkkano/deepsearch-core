# Production Todo

> 本清单是把 deepsearch-core 推到生产级的执行队列。  
> 每一项必须有验收命令、指标或可观察结果；没有验收标准的任务不进入主线。

## 0. 当前基线

最近一次本地验证：

```text
ruff check .                         pass
mypy deepsearch_core                 pass
pytest                               72 passed, 2 skipped
integration smoke                    1 passed, 1 skipped
quick search with Tavily + x666      completed
deep search with Tavily + x666       completed
general eval                         3 / 5 pass, factual avg 0.75
```

当前最大风险：

- deep_search 仍慢，真实任务约 2 分钟。
- general eval 仍不稳定，短问题可能被 max_seconds 卡死。
- source ranking 会混入二手博客。
- reader / search / LLM 没有完整 failure taxonomy。
- 安全、限流、租户隔离、生产部署仍缺。

## P0: 生产闸门基础

目标：让系统在单实例环境里稳定、可测、可观测。

- [ ] 建立 provider capability 层。
  - 文件：`deepsearch_core/llm/client.py`, `deepsearch_core/config.py`
  - 要求：识别 `response_format`、stream、usage、max_tokens、JSON mode 能力。
  - 验收：OpenAI-compatible、Gemini proxy、Claude compatible、国产 endpoint 各 1 条 smoke。

- [ ] LLM JSON schema repair。
  - 文件：`deepsearch_core/llm/client.py`, `deepsearch_core/agents/planner.py`, `deepsearch_core/agents/critic.py`
  - 要求：对象、数组、fenced JSON、截断 JSON、空 content 都有稳定行为。
  - 验收：新增至少 20 条 parser 单测。

- [ ] 搜索源可靠性矩阵。
  - 文件：`deepsearch_core/search/`
  - 要求：Tavily / Serper / Brave 或 Exa 至少两个可配置；DuckDuckGo 只做弱兜底。
  - 验收：任一搜索源超时，quick_search 仍能 completed 或明确 no_sources。

- [ ] Source tier ranking。
  - 文件：`deepsearch_core/retrieval/policy_filter.py`, `deepsearch_core/policy/policies/*.yml`
  - 要求：官方源优先，SEO/Medium/TDS 等降权或按 policy 禁用。
  - 验收：tech eval 中官方源占前 5 citations 的比例 >= 60%。

- [ ] Reader timeout isolation。
  - 文件：`deepsearch_core/agents/researcher.py`, `deepsearch_core/engine/fast_lane.py`
  - 要求：reader 失败不影响 snippet 证据；reader 总预算可配置。
  - 验收：模拟 reader 全部超时，deep_search 仍进入 critic/reporter。

- [ ] 事件级耗时统计。
  - 文件：`deepsearch_core/engine/events.py`, `deepsearch_core/engine/runner.py`, `deepsearch_core/store/store.py`
  - 要求：node、LLM、search、reader、rerank 都有 latency_ms。
  - 验收：任一 run replay 可算出瓶颈节点。

- [ ] `/ready` 与 `/metrics`。
  - 文件：`deepsearch_core/adapters/http/app.py`
  - 要求：ready 检查 LLM/search/store；metrics 输出 Prometheus text。
  - 验收：无 key 时 `/ready` 返回 degraded；有 key 时 ready。

- [ ] Eval smoke 门禁。
  - 文件：`eval/runner.py`, `eval/datasets/`
  - 要求：smoke 数据集稳定，不使用虚构版本或不可验证事实。
  - 验收：`python eval/runner.py --dataset smoke` 通过率 >= 80%。

## P1: 正确性与质量

目标：回答可信，引用可审计。

- [ ] 扩充 eval 数据集。
  - general >= 50。
  - tech >= 50。
  - finance >= 50。
  - academic >= 30。
  - adversarial >= 30。
  - multilingual >= 30。

- [ ] 引用支撑验证。
  - 文件：`eval/runner.py`
  - 要求：抽取 answer 中带 citation 的 claim，验证 source snippet/full_text 是否支持。
  - 验收：citation support accuracy 可计算并进入 summary。

- [ ] LLM-as-judge 可替换。
  - 文件：`eval/runner.py`
  - 要求：judge provider 与业务 provider 解耦。
  - 验收：可用 `EVAL_LLM_MODEL` 单独配置 judge。

- [ ] policy schema version。
  - 文件：`deepsearch_core/policy/loader.py`
  - 要求：YAML schema 校验、未知字段报错或 warning。
  - 验收：坏 policy 单测覆盖。

- [ ] query plan 质量控制。
  - 文件：`deepsearch_core/agents/planner.py`
  - 要求：planner 输出去重、空 query 过滤、过长 query 裁剪。
  - 验收：planner fuzz test 通过。

- [ ] 报告结构标准化。
  - 文件：`deepsearch_core/agents/reporter.py`
  - 要求：summary、findings、risks、sources 分区稳定。
  - 验收：报告 parser 可稳定提取章节。

## P2: 安全与多用户

目标：可以对外提供 HTTP 服务。

- [ ] API key 鉴权。
  - 文件：`deepsearch_core/adapters/http/app.py`
  - 要求：所有 `/v1/*` 路由需要 key，本地开发可关闭。
  - 验收：无 key 401，错 key 403，正确 key 200。

- [ ] Rate limit。
  - 文件：`deepsearch_core/adapters/http/app.py`
  - 要求：per-key QPS、并发任务数、每日 token 上限。
  - 验收：超过限制返回 429，且错误体稳定。

- [ ] Request size 与 timeout hard cap。
  - 文件：`deepsearch_core/adapters/http/app.py`, `deepsearch_core/config.py`
  - 要求：超大 query、过高 timeout、过多 agents 被拒绝。
  - 验收：边界测试覆盖。

- [ ] Secret redaction。
  - 文件：logging / exception / event payload 路径。
  - 要求：API key 不进入 logs/events/responses。
  - 验收：secret scanner 在仓库与测试输出中无命中。

- [ ] CORS 生产默认收紧。
  - 文件：`deepsearch_core/adapters/http/app.py`
  - 要求：默认不允许 `*`，由 env 显式配置。
  - 验收：生产配置 snapshot。

- [ ] Tenant model。
  - 文件：`deepsearch_core/store/schema.py`, `deepsearch_core/store/store.py`
  - 要求：runs/events/api_keys 可按 tenant 隔离。
  - 验收：tenant A 无法读取 tenant B run。

## P3: 可扩展存储与部署

目标：从单实例进入可水平扩展。

- [ ] PostgreSQL event store。
  - 文件：`deepsearch_core/store/`
  - 要求：SQLite 与 PostgreSQL 同一接口。
  - 验收：同一套 store 单测跑两遍。

- [ ] Redis / Postgres task coordination。
  - 要求：多进程下 start/poll/cancel/steer 一致。
  - 验收：两个 worker 同时运行，poll 能看到正确状态。

- [ ] Docker production image。
  - 文件：`Dockerfile`, `docker-compose.yml`
  - 要求：non-root、多阶段、healthcheck、只写 `/data`。
  - 验收：容器内 pytest smoke，HTTP health pass。

- [ ] Graceful shutdown。
  - 要求：SIGTERM 后停止接新任务，等待或取消 in-flight，落 cancelled/timeout。
  - 验收：集成测试模拟 SIGTERM。

- [ ] Helm chart。
  - 文件：`deploy/helm/`
  - 要求：Deployment、Service、Ingress、Secret、ConfigMap、HPA。
  - 验收：kind 集群安装成功。

## P4: SDK 与生态

目标：外部用户可稳定集成。

- [ ] Python SDK contract freeze。
  - 要求：`DeepSearch.quick_search`, `deep_search`, `stream`, `steer`, `get_run` 类型稳定。
  - 验收：public API snapshot test。

- [ ] TypeScript SDK。
  - 要求：HTTP async/poll/stream/steer 全覆盖。
  - 验收：Node smoke。

- [ ] MCP remote transport。
  - 要求：stdio 保持，HTTP/SSE 或 streamable-http 另行实现。
  - 验收：Claude Desktop stdio 与远程客户端各一条 smoke。

- [ ] OpenAPI 文档。
  - 要求：所有 HTTP request/response schema 可生成。
  - 验收：`/openapi.json` 与 docs 同步。

## 发布检查单

每次发版前执行：

```bash
python -m ruff check .
python -m mypy deepsearch_core
python -m pytest
python eval/runner.py --dataset smoke
python scripts/benchmark.py --profile production-smoke
```

人工检查：

- [ ] CHANGELOG 已更新。
- [ ] README 文档入口已更新。
- [ ] 新增 env 已写入部署文档。
- [ ] 新增 API 已写入 spec。
- [ ] 新增数据表有 migration。
- [ ] 新增 provider/search 源有降级路径。
- [ ] 没有 secret 进入 git。

## 里程碑

v0.2 Production Hardening：

- P0 全部完成。
- smoke eval >= 80%。
- quick_search P95 <= 30s。
- deep_search P95 <= 240s。

v0.5 Service Ready：

- P1 + P2 完成。
- API key + rate limit + metrics + Docker production 可用。
- full eval 总通过率 >= 80%。

v1.0 Production：

- P3 完成。
- SLA 99.9% 运行方案落地。
- full eval factual/source/citation 三项均达标。
- SDK contract freeze。
