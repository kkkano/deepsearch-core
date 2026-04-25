# Steer Design（中断机制设计）

> Steer 是 deepsearch-core 的杀手级功能：用户在 agent 跑的过程中**实时打断 + 注入新指令 + 重规划**。

灵感来自 [OpenDeepResearch](https://github.com/DesignOps6ix9/OpenDeepResearch) 的 interruption gateway。

---

## 1. 为什么需要 Steer

### 1.1 传统 Deep Research 的痛点

```
T=0s   用户问："帮我分析腾讯港股"
T=2s   agent 开始计划（规划 5 个子查询）
T=5s   agent 跑子查询 1：财报数据 ✅
T=10s  agent 跑子查询 2：分析师观点
T=15s  ↑ 用户突然意识到：「等等，我其实只关心 AI 业务线，
       不需要游戏和社交」
T=15s  ❌ 但 agent 还在跑，用户只能干等 30s
T=45s  agent 返回完整报告，但 80% 是用户不要的
T=46s  用户重新问，从头再来 → 浪费 45s + 一堆 token
```

### 1.2 Steer 模式

```
T=0s   用户问："帮我分析腾讯港股"
T=15s  用户中途说："只关心 AI 业务线"
T=15s  → POST /api/runs/{id}/steer
T=15.5s supervisor 在下一个 checkpoint 检测到 steer
T=16s  supervisor 决定「current_step 是分析师观点，先收尾」
T=18s  current_step 完成，跳回 planner 重规划
T=20s  planner 重规划：只保留 AI 相关的子查询，cancel 其他
T=35s  返回精准答案 (省了 10s + 50% token)
```

---

## 2. Scope（范围）

steer 命令有三种 scope：

| Scope | 行为 | 用例 |
|-------|------|------|
| **`current_step`** | 立即影响当前正在执行的节点 | "正在搜索的 query 加上 'site:sec.gov'" |
| **`global`** | 修改全局目标，触发重规划 | "其实我只关心 AI 业务线" |
| **`next_step`** | 下个节点开始时应用，不打断当前 | "等当前 research 跑完，重点 critique 一下" |

**默认是 `global`**（最强力，触发完整重规划）。

---

## 3. 状态机

```
                                  ┌──────────────┐
                                  │ steer_received│
                                  └──────┬───────┘
                                         │
                                         ▼
              ┌─────────────────────┴──────────────────────┐
              │                                            │
   scope=global│                            scope=current_step
              │                                            │
              ▼                                            ▼
   ┌──────────────────┐                    ┌──────────────────────┐
   │ wait_for_safe_   │                    │ inject_to_current_   │
   │ checkpoint        │                    │ node_context         │
   └────────┬─────────┘                    └──────────┬───────────┘
            │                                         │
            ▼                                         ▼
   ┌──────────────────┐                    ┌──────────────────────┐
   │ jump_to_planner  │                    │ continue_with_steer  │
   │ (current step    │                    │ (current node sees  │
   │ finishes first)  │                    │  state.steer)        │
   └────────┬─────────┘                    └──────────┬───────────┘
            │                                         │
            └──────────────────┬──────────────────────┘
                               │
                               ▼
                    ┌────────────────────┐
                    │ steer_applied      │
                    │ (event written)     │
                    └────────────────────┘
```

---

## 4. 实现细节

### 4.1 数据库表

```sql
CREATE TABLE steer_commands (
    cmd_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    content TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'global',  -- current_step / global / next_step
    applied INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    applied_at TEXT,
    applied_at_step TEXT,                  -- 哪个节点应用的
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE INDEX idx_steer_pending ON steer_commands(run_id, applied);
```

### 4.2 Runner 中的检查点

```python
async def run(self, state: State, start_node: str = "check_clarity") -> State:
    current = start_node
    
    while current != "END":
        # ---- 检查点 1: 节点开始前 ----
        steer = self.store.pop_pending_steer(state.run_id)
        if steer:
            state = self._apply_steer(state, steer, when="before_node")
            if steer.scope == "global":
                current = "planner"  # 跳回重规划
                continue
        
        # ---- 执行节点 ----
        state, next_node = await self.nodes[current](state)
        
        # ---- 检查点 2: 节点完成后 ----
        steer = self.store.pop_pending_steer(state.run_id)
        if steer:
            state = self._apply_steer(state, steer, when="after_node")
            if steer.scope in ("global", "next_step"):
                current = "planner" if steer.scope == "global" else next_node
                continue
        
        current = next_node
```

### 4.3 节点内的 steer 感知

子节点可以在 LLM 调用时把 `state.steer` 注入 prompt：

```python
async def researcher_node(state: State) -> tuple[State, str]:
    sub_query = state.current_sub_query
    
    # 把 steer 注入 system prompt（如果存在）
    extra_instruction = ""
    if state.steer and state.steer.scope == "current_step":
        extra_instruction = f"\n\n## User mid-flight directive\n{state.steer.content}"
    
    response = await llm.complete(
        system=RESEARCHER_PROMPT + extra_instruction,
        user=sub_query.text,
    )
    # ...
```

---

## 5. API 暴露

### 5.1 HTTP API

```http
POST /api/runs/{run_id}/steer
Content-Type: application/json

{
  "content": "重点关注 QT 缩表节奏，忽略降息",
  "scope": "global"
}
```

返回：
```json
{
  "accepted": true,
  "cmd_id": 42,
  "queued_at_step": "fan_out_research",
  "estimated_apply_at": "next_checkpoint"
}
```

### 5.2 MCP Tool

见 [`MCP_PROTOCOL.md` - 2.4 steer](MCP_PROTOCOL.md#24-steer中断--注入指令)。

### 5.3 CLI

```bash
# 启动异步任务
$ deepsearch deep "美联储 2026 政策" --async
{"task_id": "run_abc123"}

# 在另一个终端 steer
$ deepsearch steer run_abc123 "重点关注 QT" --scope global
{"accepted": true}

# 查看进度
$ deepsearch status run_abc123
```

### 5.4 WebSocket

```javascript
// 前端 JS
const ws = new WebSocket("ws://localhost:8000/ws/run_abc123");

ws.onmessage = (e) => {
  const event = JSON.parse(e.data);
  console.log(event.type, event.payload);
};

// 用户点击 "redirect" 按钮
function steer(content) {
  ws.send(JSON.stringify({type: "steer", content, scope: "global"}));
}
```

---

## 6. UX 模式

### 6.1 推荐前端 UX

```
┌────────────────────────────────────────────────────────────┐
│ 📊 调研进度                                          [⏸ 暂停]│
├────────────────────────────────────────────────────────────┤
│ ✅ 计划制定 (5 个子查询)                            2.1s    │
│ ✅ Agent-1: 财报数据                                3.4s    │
│ ⏳ Agent-2: 分析师观点                                       │
│ ⏳ Agent-3: 行业对比                                         │
│ ⏳ Agent-4: 宏观经济                                         │
├────────────────────────────────────────────────────────────┤
│ 💬 中途指令（agent 会在下个检查点应用）                      │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ 例如：「重点关注 AI 业务线，忽略游戏」                  │ │
│ └────────────────────────────────────────────────────────┘ │
│                                                  [发送 ➜]   │
└────────────────────────────────────────────────────────────┘
```

### 6.2 Claude 对话流（MCP）

```
👤 用户：帮我研究下腾讯港股
🤖 Claude（调用 start_deep_search）：
    好的，已经启动深度调研，预计 30-45 秒。
    [显示进度气泡] 正在分析财报数据...

👤 用户：等等，我其实只关心 AI 业务线
🤖 Claude（调用 steer）：
    收到，已经发送指令给 agent。
    [显示进度气泡] 正在重新规划，聚焦 AI 业务线...
    [若干秒后] 调研完成。

🤖 Claude：
    根据精准调研，腾讯 AI 业务线...
```

---

## 7. 边界情况

### 7.1 重复 steer

如果用户连续发了 3 次 steer，按 FIFO 顺序应用，每次都触发一次重规划。

### 7.2 steer 与 cancel

`cancel_search` 优先级高于 steer。如果用户发了 cancel，pending steer 全部废弃。

### 7.3 steer 与超时

steer 不重置超时计时器。如果整个任务跑了超过 `task_timeout_seconds`，依然会被强制结束。

### 7.4 跨节点的 steer

如果 steer 在 `reporter` 节点期间到达，scope=global 会触发：
1. 当前 reporter 完成（出 partial report）
2. 跳回 planner
3. 重新规划 + research
4. 重新生成 reporter

⚠️ **谨慎使用**：在 reporter 阶段 steer 会让任务时长接近翻倍。

### 7.5 steer 风暴

如果 1 秒内收到 10 个 steer，自动合并：
- 取最后一个 `global` 作为最终方向
- 把所有 `current_step` 拼接成单一指令
- 写一个 `steer_burst_merged` 事件

---

## 8. 安全考量

| 风险 | 对策 |
|------|------|
| Prompt injection 攻击 | steer content 也走 system prompt 隔离 + 输入长度限制 (max 500 char) |
| 用户恶意频繁 steer | per-task 限流：最多 10 次 steer / minute |
| Steer 让 agent 跑出预算 | task_timeout 不重置 |
| 跨用户 steer | run_id 必须 token 验证（HTTP / MCP transport 自带） |

---

## 9. 测试用例

```python
# tests/unit/test_steer.py

async def test_global_steer_triggers_replan(runner, store):
    state = await runner.run_until(state, target_step="fan_out_research")
    
    store.add_steer(state.run_id, "focus on AI", scope="global")
    
    final = await runner.run(state)
    
    # 应该回到 planner
    events = list(store.replay(state.run_id))
    assert any(e.type == "steer_applied" for e in events)
    assert any(e.payload.get("node") == "planner" 
               for e in events 
               if e.type == "node_started")

async def test_current_step_steer_inline(runner, store):
    # current_step scope 不重规划，只注入 prompt
    state = await runner.run_until(state, target_step="researcher")
    store.add_steer(state.run_id, "add site:sec.gov", scope="current_step")
    
    final = await runner.run(state)
    
    # 当前 researcher 应该用了新指令
    research_events = [e for e in store.replay(state.run_id) 
                       if e.type == "tool_call_started"]
    assert any("sec.gov" in str(e.payload) for e in research_events)
```

---

## 10. 与 OpenDeepResearch 的对比

| 维度 | OpenDeepResearch | deepsearch-core |
|------|------------------|------------------|
| Steer 触发 | supervisor 节点 poll | runner 每 tick check |
| Steer 持久化 | SQLite steer_commands | 同 |
| Scope 支持 | global only | global / current_step / next_step |
| 与 fan-out 兼容 | 单 researcher，简单 | N agents 并行，需要协调 |
| 重规划粒度 | 全部重做 | 智能复用：未受影响的子查询保留结果 |
| MCP 暴露 | 无 | ✅ steer tool |
| CLI 暴露 | 无 | ✅ deepsearch steer 命令 |

deepsearch-core 在 ODR 基础上增强了 scope、fan-out 兼容、协议暴露。
