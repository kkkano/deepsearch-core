# deepsearch-core Agent Notes

本文件记录仓库骨架与文档职责。后续改架构、移动目录、增加关键文档时必须同步更新。

## 架构原则

- 核心引擎保持薄：状态机、状态对象、事件写入。
- 适配层保持厚：HTTP / MCP / CLI 只做协议转换，不藏业务规则。
- 搜索、LLM、reranker、reader 都是可替换 provider。
- 任何 provider 失败都应降级，不应让整个 run 静默崩溃。
- 事件溯源是审计线，不能绕过。

## 目录树

```text
deepsearch-core/
|-- deepsearch_core/
|   |-- adapters/          # HTTP / MCP / CLI 协议适配
|   |-- agents/            # planner / researcher / critic / reporter 节点
|   |-- engine/            # State / GraphRunner / RunManager / EventBus
|   |-- llm/               # OpenAI-compatible LLM client 与 JSON 兼容层
|   |-- policy/            # Source policy 加载与内置 YAML 策略
|   |-- retrieval/         # query expansion / HyDE / dedup / policy filter
|   |-- search/            # Tavily / Serper / DuckDuckGo / Crossref / readers
|   |-- store/             # SQLite event store 与 schema
|   |-- reranker/          # Cohere reranker 抽象与实现
|   |-- prompts/           # 节点提示词
|   |-- facade.py          # SDK 主入口 DeepSearch
|   |-- config.py          # 环境变量与全局配置
|   |-- exceptions.py      # 稳定错误类型
|-- docs/                  # 架构、协议、部署、生产化文档
|-- eval/                  # 数据集与质量评测 runner
|-- examples/              # SDK 使用示例
|-- scripts/               # benchmark / install 脚本
|-- tests/                 # unit / integration 测试
|-- pyproject.toml         # 包、依赖、ruff、mypy、pytest 配置
|-- Dockerfile             # 容器构建入口
|-- docker-compose.yml     # 本地/私有部署编排
|-- README.md              # 项目入口说明
|-- CHANGELOG.md           # 变更记录
```

## 关键文件职责

- `deepsearch_core/facade.py`：组装配置、store、LLM、search provider，向 SDK/adapter 暴露统一 API。
- `deepsearch_core/config.py`：读取 `.env`、`DEEPSEARCH_ENV_FILE` 和 provider 环境变量别名。
- `deepsearch_core/llm/client.py`：OpenAI-compatible chat client，负责 provider JSON 解析、降级重试、错误归一。
- `deepsearch_core/engine/runner.py`：执行 graph 节点、处理 timeout/cancel/steer、写运行事件。
- `deepsearch_core/engine/manager.py`：跨 HTTP/MCP/SDK 的任务生命周期单一真相源。
- `deepsearch_core/engine/state.py`：RunConfig、State、Evidence、Report 等核心数据模型。
- `deepsearch_core/store/store.py`：SQLite runs/events/steer/query cache 持久化。
- `deepsearch_core/agents/planner.py`：把用户目标拆成 sub queries，必须容忍不同模型 JSON 形态。
- `deepsearch_core/agents/researcher.py`：执行 HyDE、query expansion、搜索、reader、证据转换。
- `deepsearch_core/agents/critic.py`：识别冲突、反方观点、缺口。
- `deepsearch_core/agents/reporter.py`：合成最终 markdown 报告与 citations。
- `deepsearch_core/engine/fast_lane.py`：quick_search 快速路径，绕过完整 graph。
- `deepsearch_core/retrieval/policy_filter.py`：按 source policy 做 block/boost/freshness。
- `eval/runner.py`：质量评测入口，负责 factual/source/citation/latency 汇总。

## 文档职责

- `docs/ARCHITECTURE.md`：解释核心架构和状态机。
- `docs/BLUEPRINT.md`：路线图和版本演进。
- `docs/PRODUCTION_SPEC.md`：生产级定义、SLO、API/LLM/Search/Eval/Security/Persistence 合同。
- `docs/PRODUCTION_TODO.md`：生产化执行清单、验收命令、里程碑。
- `docs/MCP_PROTOCOL.md`：MCP tools/resources/prompts 协议设计。
- `docs/STEER_DESIGN.md`：中途 steer 的状态机与语义。
- `docs/SOURCE_POLICY.md`：source policy YAML 与领域策略。
- `docs/EVAL_HARNESS.md`：eval 框架设计。
- `docs/DEPLOYMENT.md`：本地、Docker、VPS、云部署。
- `docs/CONTRIBUTING.md`：贡献流程。

## 依赖边界

- `facade.py` 可以依赖 config/store/llm/search/retrieval/agents/engine。
- `engine/` 不应依赖 HTTP/MCP/CLI。
- `agents/` 可以依赖 LLM、retrieval、search、policy，但不应依赖 adapter。
- `adapters/` 只调用 `DeepSearch` / `RunManager`，不直接拼核心流程。
- `eval/` 可以调用 SDK，但不要污染 runtime package。

## 质量命令

```bash
python -m ruff check .
python -m mypy deepsearch_core
python -m pytest
```

真实搜索/LLM smoke 示例：

```bash
set DEEPSEARCH_ENV_FILE=D:\AgentProject\FinSight\.env
set LLM_BASE_URL=https://x666.me/v1
set LLM_API_KEY=...
set DEEPSEARCH_MODEL=gemini-3-flash-preview
python -m deepsearch_core.adapters.cli.main quick "What is MCP?" --policy tech --timeout 45 --json
```

## 变更日志

- 2026-04-26：新增生产级规范与 TODO，明确生产门槛、SLO、质量闸门和执行路径。
