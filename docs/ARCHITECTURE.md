# Architecture（架构设计）

> deepsearch-core 的核心架构详解：核心引擎、多 agent fan-out、事件溯源、流式输出。

---

## 1. 设计哲学

### 1.1 核心、薄；适配层、厚

```
┌──────────────────────────────────────────────────────────┐
│                    Core Engine                           │
│        (~500 LOC, 5 dependencies, no LangGraph)         │
└──────────────────────────────────────────────────────────┘
                          │
        ┌────┬────────────┼─────────────┬────┐
        ▼    ▼            ▼             ▼    ▼
       MCP  HTTP         CLI           SDK  Skill
       100  150 LOC      80 LOC        60   100 LOC
       LOC  glue         glue          LOC  bundle
```

核心引擎只做三件事：
1. **运行 graph**（5 个节点的状态机）
2. **管理 state**（结构化状态）
3. **写事件**（落 SQLite，可回放）

其他全部下沉到适配层 / 工具层 / 策略层。

### 1.2 不依赖 LangChain / LangGraph

**理由**：
- LangGraph 0.2+ 启动 2-3s（冷启动）vs 极简引擎 < 100ms
- 跨 runtime 兼容性差（Cloudflare Workers / Vercel Edge / Modal 经常出问题）
- 调试困难（节点状态机被 SDK 封装）
- bug 难定位（依赖链 100+ 包）

**deepsearch-core 选择**：手写 200-300 行的 graph runner，所有逻辑可见、可控、可移植。

### 1.3 一切皆事件（Event Sourcing）

每一次 LLM call、tool call、state 变化、用户 steer 都写入 SQLite events 表。这给我们带来：

- **完整 replay**：用户能看到 agent 跑了什么
- **A/B 测试**：同一个 query 跑两次，对比 events
- **离线 eval**：用历史 events 重放新 prompt
- **审计合规**：金融/法律场景必备

---

## 2. 核心组件

### 2.1 Graph Runner（`deepsearch_core/engine/runner.py`）

```python
class GraphRunner:
    """极简 graph 引擎，~200 行核心逻辑。"""

    def __init__(self, nodes: dict[str, NodeFunc], store: EventStore):
        self.nodes = nodes
        self.store = store

    async def run(self, state: State, start_node: str = "check_clarity") -> State:
        current = start_node
        state.status = "running"
        self.store.append(state.run_id, "run_started", state.dict())

        while current != "END":
            # 1. 检查 steer 命令（中断机制）
            if steer := self.store.pop_steer(state.run_id):
                state.steer = steer
                self.store.append(state.run_id, "steer_received", steer.dict())
                current = "planner"  # 跳回重规划
                continue

            # 2. 执行节点
            self.store.append(state.run_id, f"node_{current}_started", {})
            try:
                state, current = await self.nodes[current](state)
                self.store.append(state.run_id, f"node_{current}_completed", state.dict())
            except Exception as e:
                self.store.append(state.run_id, f"node_{current}_error", {"error": str(e)})
                raise

            # 3. 检查超时
            if state.elapsed_seconds() > state.config.timeout_seconds:
                state.status = "timeout"
                break

        state.status = "completed" if current == "END" else state.status
        self.store.append(state.run_id, "run_finished", state.dict())
        return state
```

**关键点**：
- 每个 tick 检查 steer（核心创新）
- 节点本身是纯函数 `(state) -> (state, next_node)`
- 所有状态变化都写事件
- 异常落事件（不吞）

### 2.2 五个核心节点

```
START → check_clarity → supervisor → planner → fan_out_research → critic → reporter → END
                          ▲                            │
                          └────── steer 中断 ──────────┘
```

| 节点 | 职责 | 模型 |
|------|------|------|
| `check_clarity` | 判断问题是否清晰，模糊则要求 elicitation | haiku-4-5 |
| `supervisor` | 全局决策、检查 steer、决定下一步 | sonnet-4-6 |
| `planner` | 把目标拆成 N 个子查询（fan-out 输入） | haiku-4-5 |
| `fan_out_research` | 并发启动 N 个 researcher agents | （N 个 haiku） |
| `critic` | 反方论据 + 矛盾检测 + 证据评分 | sonnet-4-6 |
| `reporter` | 生成最终 markdown 报告 + citations | opus-4-7 |

### 2.3 Multi-Agent Fan-Out（`deepsearch_core/agents/`）

```python
async def fan_out_research(state: State) -> tuple[State, str]:
    sub_queries = state.plan.sub_queries  # 来自 planner

    async def research_one(q: SubQuery) -> EvidenceBundle:
        agent = ResearcherAgent(state.config, sub_query=q)
        return await agent.run()  # 内部跑 ReAct 循环

    # 并发执行
    bundles = await asyncio.gather(*[research_one(q) for q in sub_queries])

    state.evidence = merge_and_dedup(bundles)
    return state, "critic"
```

**对比**：
- ❌ 旧模式（self-RAG 串行）：3 轮 × 8s = 24s
- ✅ 新模式（fan-out 并行）：max(N agents) ≈ 8s

### 2.4 Researcher ReAct 循环

每个 researcher agent 内部跑 ReAct：

```
sub_query
   │
   ▼
HyDE 生成假设答案 ──→ embedding ──→ 检索
   │                                  │
   ▼                                  ▼
Query 扩展 (3-5 变体)           Tavily / Serper / Crossref
                                      │
                                      ▼
                              Cohere reranker (top-k)
                                      │
                                      ▼
                          Firecrawl / Jina 全文抽取
                                      │
                                      ▼
                              Source Policy 过滤
                                      │
                                      ▼
                         证据评分 (LLM-as-Judge)
                                      │
              ┌───────────────────────┤
              ▼                       ▼
      足够？是 → 返回           缺口？是 → 精化 query 再来
                                      │
                                      └─→ 最多 max_steps 次
```

### 2.5 State 设计

```python
class State(BaseModel):
    run_id: str
    goal: str
    config: RunConfig
    started_at: datetime

    # Plan
    plan: Plan | None = None
    sub_queries: list[SubQuery] = []

    # Evidence
    evidence: list[Evidence] = []
    citations: list[Citation] = []

    # Critic
    critic_report: CriticReport | None = None

    # Final
    report: Report | None = None

    # Control
    steer: SteerCommand | None = None
    interrupt_requested: bool = False
    status: Literal["pending", "running", "interrupted", "completed", "failed", "timeout"]

    # Bookkeeping
    step_count: int = 0
    token_usage: TokenUsage = TokenUsage()
```

State 是 immutable 风格：每个节点返回**新的** state 对象（pydantic 的 `.copy(update={...})`）。

---

## 3. Event Sourcing 设计

### 3.1 SQLite Schema

```sql
-- 一次 deep research 任务
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    goal TEXT NOT NULL,
    config_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

-- 事件流（顺序追加，永不修改）
CREATE TABLE events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    type TEXT NOT NULL,         -- llm_call/tool_call/state_change/steer_received/...
    payload_json TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE INDEX idx_events_run ON events(run_id, event_id);

-- 用户 steer 命令队列
CREATE TABLE steer_commands (
    cmd_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    content TEXT NOT NULL,
    scope TEXT NOT NULL,        -- current_step / global / next_step
    applied INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    applied_at TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
```

### 3.2 事件类型

```python
class EventType(str, Enum):
    # 生命周期
    RUN_STARTED = "run_started"
    RUN_FINISHED = "run_finished"
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_ERROR = "node_error"

    # LLM
    LLM_CALL_STARTED = "llm_call_started"
    LLM_CALL_COMPLETED = "llm_call_completed"
    LLM_TOKEN_STREAM = "llm_token_stream"

    # Tool
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"

    # State / Control
    STATE_CHANGE = "state_change"
    STEER_RECEIVED = "steer_received"
    STEER_APPLIED = "steer_applied"

    # Quality
    EVIDENCE_FOUND = "evidence_found"
    CITATION_ADDED = "citation_added"
```

### 3.3 Replay

```python
class EventStore:
    def replay(self, run_id: str) -> Iterator[Event]:
        """按时间顺序重放所有事件。"""
        cursor = self.db.execute(
            "SELECT * FROM events WHERE run_id=? ORDER BY event_id",
            (run_id,)
        )
        for row in cursor:
            yield Event.from_row(row)
```

前端可以基于 replay 渲染「时间线」视图。

---

## 4. Streaming 输出

### 4.1 流式总线

```python
class EventBus:
    """全链路 streaming：node → bus → adapters → user。"""
    def __init__(self):
        self._subscribers: list[asyncio.Queue] = []

    async def publish(self, event: Event):
        for q in self._subscribers:
            await q.put(event)

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self._subscribers.append(q)
        return q
```

每个 adapter（HTTP / WS / MCP / CLI）订阅 bus，按自己的协议格式输出。

### 4.2 渐进式披露（Progressive Disclosure）

```
T=0s    [PLAN]       规划完成: 5 个子查询
T=2s    [RESEARCH]   agent-1 找到 3 个来源
T=3s    [RESEARCH]   agent-2 找到 5 个来源
T=4s    [PARTIAL]    第一轮证据可读 → 用户可决定是否够用
T=8s    [RESEARCH]   所有 agents 完成
T=10s   [CRITIC]     发现 1 个矛盾，提出反方
T=15s   [REPORT]     最终报告流式输出
T=18s   [DONE]
```

用户在 T=4s 就能看到部分结果，不用等 18s。

---

## 5. 可扩展点

| 扩展点 | 位置 | 示例 |
|--------|------|------|
| 新搜索引擎 | `search/` | 实现 `BaseSearch` 接口 |
| 新 reranker | `reranker/` | 实现 `BaseReranker` |
| 新 agent | `agents/` | 继承 `BaseAgent` |
| 新策略 | `policy/policies/*.yml` | YAML 加载 |
| 新协议 | `adapters/` | 仿 mcp/http/cli 写 glue |
| 新 LLM provider | `llm/client.py` | OpenAI 兼容自动支持 |

---

## 6. 性能目标

| 指标 | 目标 | 当前 |
|------|------|------|
| 冷启动 | < 200ms | 待测 |
| `quick_search` P50 | < 3s | 待测 |
| `quick_search` P95 | < 8s | 待测 |
| `deep_search` 首字节 | < 5s | 待测 |
| `deep_search` P95 | < 60s | 待测 |
| 单 task 内存 | < 200MB | 待测 |
| Token / query | < 10k | 待测 |

详细 benchmark 见 [`scripts/benchmark.py`](../scripts/benchmark.py)。
