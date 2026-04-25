# MCP Protocol Design（MCP 协议设计）

> deepsearch-core 作为 MCP server 暴露的 tools / resources / prompts 完整规范。

---

## 1. 设计原则

### 1.1 规避 60s 超时
MCP 客户端默认 60s timeout（Claude Desktop / Cursor 都是）。我们不暴露同步的 deep_search，而是：

- **同步**：`quick_search`（< 8s）
- **异步**：`start_deep_search` + `poll_search` 长轮询
- **流式**：`resources/subscribe` 拿增量更新

### 1.2 LLM Friendly 工具设计
工具描述要让 LLM 能自主选用：
- ✅ 描述「**何时用**」（"when query is simple / factual"）
- ✅ 描述「**返回什么**」（"returns answer + 3-5 sources"）
- ✅ 不暴露内部细节（用户不需要知道有 fan-out）

---

## 2. Tools（工具）

### 2.1 `quick_search`

**用途**：快速事实查询，单轮搜索 + LLM 摘要。

```json
{
  "name": "quick_search",
  "description": "Fast single-round search for simple factual questions. Returns answer in <8 seconds with 3-5 cited sources. USE WHEN: user asks for current events, definitions, latest news, simple fact lookup. DO NOT USE FOR: complex analysis, multi-source comparison, future predictions.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "The question to search"},
      "policy": {"type": "string", "enum": ["general", "finance", "tech", "academic"], "default": "general"},
      "max_results": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10}
    },
    "required": ["query"]
  }
}
```

**返回**：
```json
{
  "answer": "Claude 4.7 was released on...",
  "citations": [
    {"index": 1, "url": "https://...", "title": "...", "snippet": "..."}
  ],
  "elapsed_seconds": 3.2,
  "cache_hit": false
}
```

### 2.2 `start_deep_search`（异步启动）

**用途**：复杂研究任务，立即返回 `task_id`，后台跑 fan-out。

```json
{
  "name": "start_deep_search",
  "description": "Launch a deep research task running in background. Returns task_id immediately. USE WHEN: question requires multi-source comparison, in-depth analysis, future predictions, or comprehensive review. After calling, use poll_search to get results.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "depth": {"type": "integer", "default": 3, "minimum": 1, "maximum": 5},
      "policy": {"type": "string", "enum": ["general", "finance", "tech", "academic"]},
      "max_agents": {"type": "integer", "default": 4, "minimum": 1, "maximum": 8}
    },
    "required": ["query"]
  }
}
```

**返回**：
```json
{
  "task_id": "run_abc123",
  "status": "running",
  "eta_seconds": 45,
  "poll_with": "poll_search",
  "steer_with": "steer",
  "resource_uri": "deepsearch://task/run_abc123"
}
```

### 2.3 `poll_search`（长轮询拿结果）

**用途**：长轮询，最多等 25s（避开 60s 超时，留 buffer）。

```json
{
  "name": "poll_search",
  "description": "Poll for deep search results. Long-polls up to wait_seconds (max 25). Returns partial result if still running, or final result if done. CALL REPEATEDLY until status='completed'.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "task_id": {"type": "string"},
      "wait_seconds": {"type": "integer", "default": 25, "minimum": 1, "maximum": 25}
    },
    "required": ["task_id"]
  }
}
```

**返回（still running）**：
```json
{
  "task_id": "run_abc123",
  "status": "running",
  "current_step": "fan_out_research",
  "progress": 0.6,
  "partial_result": {
    "evidence_count": 12,
    "sources_found": ["...", "..."],
    "interim_findings": "Initial findings suggest..."
  },
  "still_running": true
}
```

**返回（completed）**：
```json
{
  "task_id": "run_abc123",
  "status": "completed",
  "final_report": "# Research Summary\n\n...",
  "citations": [...],
  "evidence": [...],
  "elapsed_seconds": 38,
  "still_running": false
}
```

### 2.4 `steer`（中断 + 注入指令）

**用途**：在 agent 跑的时候插队改方向。

```json
{
  "name": "steer",
  "description": "Inject a steering command into a running task. The agent will pause at next safe checkpoint, apply the command, and re-plan. USE WHEN: user wants to redirect, narrow scope, or add new constraints mid-flight.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "task_id": {"type": "string"},
      "command": {"type": "string", "description": "Natural language steering command, e.g. 'focus on QT pace, ignore rate cuts'"},
      "scope": {
        "type": "string",
        "enum": ["current_step", "global", "next_step"],
        "default": "global"
      }
    },
    "required": ["task_id", "command"]
  }
}
```

**返回**：
```json
{
  "accepted": true,
  "queued_at_step": 3,
  "will_apply_at_step": 4
}
```

### 2.5 `cancel_search`

```json
{
  "name": "cancel_search",
  "description": "Cancel a running deep search task. Returns partial results if any.",
  "inputSchema": {
    "type": "object",
    "properties": {"task_id": {"type": "string"}},
    "required": ["task_id"]
  }
}
```

---

## 3. Resources（资源）

资源用于流式订阅，**支持 streaming 的客户端**（Claude Desktop / Cursor 已支持）能像 SSE 一样接收推送。

### 3.1 任务进度资源

```
URI: deepsearch://task/{task_id}/progress
MIME: application/json
```

server 主动推送 progress 通知：
```json
{
  "step": "fan_out_research",
  "progress": 0.6,
  "current_finding": "Found 8 sources..."
}
```

### 3.2 增量结果资源

```
URI: deepsearch://task/{task_id}/round-1
URI: deepsearch://task/{task_id}/round-2
URI: deepsearch://task/{task_id}/final
```

每完成一轮就 commit 一个 resource，客户端能即时读取。

### 3.3 事件回放资源

```
URI: deepsearch://task/{task_id}/events
MIME: application/jsonl
```

完整 event stream，用于 replay / 调试。

---

## 4. Prompts（提示词模板）

MCP 还能暴露 prompts，让客户端预设场景。

### 4.1 `finance-deep-research`

```yaml
name: finance-deep-research
description: Deep research with finance-specific source policy
arguments:
  - name: stock_or_topic
    description: Stock ticker or finance topic
    required: true
template: |
  Use deepsearch with policy=finance to research:
  
  {{stock_or_topic}}
  
  Focus on:
  - Latest 10-K / 10-Q filings (SEC sources)
  - Bloomberg / Reuters analyst views
  - Macro context (FOMC, BOJ, ECB)
  - Risks and competitive landscape
  
  Use start_deep_search with depth=3.
  When poll returns partial, summarize findings so far.
```

### 4.2 `tech-trend-analysis`

```yaml
name: tech-trend-analysis
description: Tech trend research with academic + news sources
arguments:
  - name: topic
    required: true
template: |
  Research the latest trends in: {{topic}}
  
  Use deepsearch with policy=tech, depth=3.
  Prefer arxiv.org, github.com, official blogs.
  Avoid marketing-heavy sites.
```

---

## 5. Transport（传输层）

> ⚠️ **v0.1.x 状态**：仅 `stdio` 落地，HTTP/SSE/streamable-http 计划于 v0.2 提供。
> 当前需要远程访问的客户端（Cherry Studio / 小龙虾 / 自研 bot）请改用 **HTTP API**
> (`uvicorn deepsearch_core.adapters.http.app:app --port 8000`)，路由功能与 MCP
> 工具完全对齐。

| Transport | v0.1.x 状态 | 用途 | 启动 |
|-----------|------------|------|------|
| **stdio** | ✅ 已实现 | 本地，Claude Desktop / Cursor / Cline | `python -m deepsearch_core.adapters.mcp` |
| **HTTP+SSE** | 🚧 v0.2 | 远程，Cherry Studio / Web | _v0.2 提供_ |
| **Streamable HTTP** | 🚧 v0.2 | 2025 新标准，单连接双向 | _v0.2 提供_ |

### 5.1 Claude Desktop 配置示例

```json
{
  "mcpServers": {
    "deepsearch": {
      "command": "python",
      "args": ["-m", "deepsearch_core.adapters.mcp"],
      "env": {
        "LLM_API_KEY": "sk-...",
        "TAVILY_API_KEY": "tvly-...",
        "DEFAULT_POLICY": "general"
      }
    }
  }
}
```

### 5.2 远程 HTTP 模式

```bash
# Server 端
deepsearch-mcp --transport http --port 8765

# Client 端（Cherry Studio 配置）
{
  "type": "http",
  "url": "https://your-server.com:8765/mcp",
  "auth": {"type": "bearer", "token": "..."}
}
```

---

## 6. Error Handling

```json
{
  "code": "TASK_NOT_FOUND",
  "message": "No task with id run_abc123",
  "data": {"task_id": "run_abc123"}
}
```

### 标准错误码

| Code | 含义 |
|------|------|
| `TASK_NOT_FOUND` | task_id 不存在 |
| `TASK_ALREADY_FINISHED` | 任务已结束，不能 steer |
| `RATE_LIMIT` | 超出 per-key 限流 |
| `LLM_ERROR` | 上游 LLM API 故障 |
| `SEARCH_ERROR` | 所有搜索引擎都失败 |
| `TIMEOUT` | 任务超时 |
| `INVALID_POLICY` | 策略文件不存在或格式错 |

---

## 7. 调用示例（端到端）

```python
# 模拟 Claude 在对话中的工具调用序列
async def claude_workflow(user_query: str):
    # 1. 启动深度搜索
    result = await mcp.call_tool("start_deep_search", {
        "query": user_query,
        "depth": 3,
        "policy": "finance"
    })
    task_id = result["task_id"]

    # 2. 长轮询，直到完成
    while True:
        poll_result = await mcp.call_tool("poll_search", {
            "task_id": task_id,
            "wait_seconds": 25
        })
        
        # 显示中间进度给用户
        if poll_result["still_running"]:
            print(f"进度 {poll_result['progress']*100:.0f}%: {poll_result['current_step']}")
            
            # 用户可以决定是否 steer
            if user_wants_to_redirect():
                await mcp.call_tool("steer", {
                    "task_id": task_id,
                    "command": "focus on QT pace, ignore rate cuts"
                })
        else:
            return poll_result["final_report"]
```

---

## 8. 兼容性矩阵

| 客户端 | stdio | HTTP+SSE | Streamable HTTP | Resources | 备注 |
|--------|-------|----------|-----------------|-----------|------|
| Claude Desktop | ✅ | ✅ | ✅ | ✅ | 全功能 |
| Claude Code | ✅ | ✅ | ✅ | ✅ | 全功能 |
| Cursor | ✅ | ✅ | ⚠️ | ⚠️ | 部分支持 |
| Cline | ✅ | ✅ | ❌ | ❌ | 基础 |
| Cherry Studio | ❌ | ✅ | ❌ | ❌ | HTTP only |
| Continue.dev | ✅ | ✅ | ⚠️ | ❌ | 基础 |
| Zed | ✅ | ❌ | ❌ | ❌ | stdio only |
| 小龙虾 / 自研 Bot | ❌ | ✅ | ❌ | ❌ | 走 HTTP API 更合适 |

→ 推荐主流场景用 **HTTP+SSE**（兼容性最广）。
