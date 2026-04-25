# Deployment（部署指南）

> deepsearch-core 多种部署形态：本地、Docker、Cloudflare Workers、Modal Labs、自建 VPS。

---

## 1. 本地开发

### 1.1 用 uv（推荐）

```bash
# 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 克隆仓库
git clone https://github.com/kkkano/deepsearch-core
cd deepsearch-core

# 同步依赖（自动建虚拟环境）
uv sync --all-extras

# 复制配置
cp .env.example .env
# 编辑 .env 填入 API keys

# 跑测试
uv run pytest

# 跑 CLI
uv run deepsearch quick "What is MCP?"

# 跑 MCP server
uv run deepsearch-mcp

# 跑 HTTP server
uv run deepsearch-server --port 8000
```

### 1.2 用 pip

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev,reranker]"
cp .env.example .env
pytest
```

---

## 2. Claude Desktop 集成（MCP stdio）

### 2.1 一行安装

```bash
claude mcp add deepsearch -- python -m deepsearch_core.adapters.mcp
```

### 2.2 手动配置 `claude_desktop_config.json`

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "deepsearch": {
      "command": "python",
      "args": ["-m", "deepsearch_core.adapters.mcp"],
      "env": {
        "LLM_BASE_URL": "https://api.anthropic.com/v1",
        "LLM_API_KEY": "sk-ant-...",
        "TAVILY_API_KEY": "tvly-...",
        "DEFAULT_POLICY": "general"
      }
    }
  }
}
```

重启 Claude Desktop，对话里说「用 deepsearch 调研 ...」即可。

---

## 3. Docker 部署

### 3.1 单容器

```bash
docker pull ghcr.io/kkkano/deepsearch-core:latest

docker run -d \
  --name deepsearch \
  -p 8000:8000 \
  -p 8765:8765 \
  -e LLM_API_KEY=sk-... \
  -e TAVILY_API_KEY=tvly-... \
  -v $(pwd)/data:/data \
  ghcr.io/kkkano/deepsearch-core:latest
```

### 3.2 docker-compose（推荐）

```yaml
# docker-compose.yml
version: "3.9"
services:
  deepsearch:
    image: ghcr.io/kkkano/deepsearch-core:latest
    container_name: deepsearch
    restart: unless-stopped
    ports:
      - "8000:8000"   # HTTP API
      - "8765:8765"   # MCP HTTP
    environment:
      LLM_BASE_URL: ${LLM_BASE_URL}
      LLM_API_KEY: ${LLM_API_KEY}
      TAVILY_API_KEY: ${TAVILY_API_KEY}
      COHERE_API_KEY: ${COHERE_API_KEY}
      DEFAULT_POLICY: general
    volumes:
      - ./data:/data
      - ./policies:/app/deepsearch_core/policy/policies/custom
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
```

```bash
docker compose up -d
```

### 3.3 配合 Cloudflare Tunnel（主人现有套路）

```yaml
# 加一个 cloudflared 服务
  cloudflared:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    command: tunnel --no-autoupdate run
    environment:
      TUNNEL_TOKEN: ${CF_TUNNEL_TOKEN}
    depends_on:
      - deepsearch
```

主人就能用 `deepsearch.your-domain.com` 全球访问，零端口暴露。

---

## 4. Cloudflare Workers（边缘部署）

> 全球 50ms 延迟，免费额度每天 10w 请求。

### 4.1 限制
- Cloudflare Workers 不能跑完整 Python 运行时
- 但是可以跑 **Pyodide**（Python via WebAssembly）
- 或者用 **TypeScript port**（计划在 v0.3 提供）

### 4.2 使用 wrangler

```bash
npm install -g wrangler
wrangler login

# 在 deepsearch-core 仓库内
wrangler init --type python
wrangler deploy
```

### 4.3 Workers + R2 + D1 架构

```
┌─────────────────┐
│ Cloudflare      │
│ Workers (Edge)  │
│                 │
│ ┌─────────────┐ │      ┌─────────┐
│ │ Engine      │ │ ───→ │ Anthropic│ (LLM)
│ │ + Adapters  │ │      └─────────┘
│ └─────────────┘ │      ┌─────────┐
│        │        │ ───→ │ Tavily  │ (Search)
│        ▼        │      └─────────┘
│ ┌─────────────┐ │
│ │ D1 (SQLite) │ │  ← Event store
│ │ R2 (Object) │ │  ← Long reports
│ └─────────────┘ │
└─────────────────┘
```

详细配置见 `scripts/deploy_cloudflare.sh`（v0.2 提供）。

---

## 5. Modal Labs（Serverless 长任务）

> 适合 deep_search 这种 30-120s 长任务。

### 5.1 安装

```bash
pip install modal
modal token new
```

### 5.2 部署

```python
# modal_deploy.py
import modal

stub = modal.Stub("deepsearch")
image = modal.Image.debian_slim().pip_install("deepsearch-core")

@stub.function(
    image=image,
    timeout=300,  # 5 分钟
    secret=modal.Secret.from_name("deepsearch-keys"),
)
def deep_search(query: str, depth: int = 3) -> dict:
    from deepsearch_core import DeepSearch
    ds = DeepSearch()
    return ds.deep_search_sync(query, depth=depth)

@stub.web_endpoint(method="POST")
def api(query: str, depth: int = 3):
    return deep_search.remote(query, depth)
```

```bash
modal deploy modal_deploy.py
# 拿到 https://your-org--deepsearch-api.modal.run
```

---

## 6. 自建 VPS（主人当前方式）

### 6.1 systemd service

```ini
# /etc/systemd/system/deepsearch.service
[Unit]
Description=deepsearch-core HTTP server
After=network.target

[Service]
Type=simple
User=allen
WorkingDirectory=/opt/deepsearch-core
EnvironmentFile=/opt/deepsearch-core/.env
ExecStart=/opt/deepsearch-core/.venv/bin/uvicorn deepsearch_core.adapters.http.app:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now deepsearch
sudo systemctl status deepsearch
```

### 6.2 Nginx 反代

```nginx
server {
    listen 443 ssl http2;
    server_name deepsearch.example.com;
    
    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 300s;     # SSE 长连接
        proxy_buffering off;          # SSE 不缓冲
    }
}
```

---

## 7. Telegram Bot 集成（OpenClaw / ufomiaobot）

主人可以让 ufomiaobot 接 deepsearch-core，给用户提供深度调研：

```python
# 在 OpenClaw 里加一个 tool
from deepsearch_core import DeepSearch

ds = DeepSearch(base_url=os.getenv("DEEPSEARCH_URL"))

@bot.message_handler(commands=["research"])
async def cmd_research(msg):
    query = msg.text.replace("/research", "").strip()
    if not query:
        await bot.reply_to(msg, "用法：/research <你的问题>")
        return
    
    progress_msg = await bot.reply_to(msg, "🔍 正在调研...")
    
    async for chunk in ds.stream(query, depth=3):
        # 每隔 5s 更新一次消息
        if chunk.is_progress:
            await bot.edit_message_text(
                f"🔍 {chunk.current_step}: {chunk.partial_summary}",
                msg.chat.id, progress_msg.message_id
            )
    
    await bot.edit_message_text(chunk.final_report, msg.chat.id, progress_msg.message_id)
```

---

## 8. 性能调优

### 8.1 LLM 节点级配置（成本优化）

```env
# 规划/研究用 haiku（便宜 3x）
PLANNER_MODEL=claude-haiku-4-5
RESEARCHER_MODEL=claude-haiku-4-5

# 关键节点用更强模型
SUPERVISOR_MODEL=claude-sonnet-4-6
CRITIC_MODEL=claude-sonnet-4-6
REPORTER_MODEL=claude-opus-4-7
```

### 8.2 Prompt Caching（Anthropic API）

```env
ENABLE_PROMPT_CACHING=true
PROMPT_CACHE_TTL=3600       # 1 hour
```

启用后：system prompt + tool definitions + agent persona 全部 cache，token 成本 -90%。

### 8.3 并发控制

```env
MAX_CONCURRENT_AGENTS=8       # fan-out 并发上限
MAX_CONCURRENT_TASKS=20       # 整个进程同时跑的任务数
```

### 8.4 缓存层

```env
ENABLE_QUERY_CACHE=true
QUERY_CACHE_TTL=86400         # 24h
QUERY_CACHE_BACKEND=sqlite    # sqlite / redis / memcached
```

---

## 9. 监控

### 9.1 健康检查

```bash
curl http://localhost:8000/health
# {"status": "ok", "version": "0.1.0", "uptime_seconds": 3600}

curl http://localhost:8000/metrics
# Prometheus format
```

### 9.2 Langfuse 集成

```env
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
LANGFUSE_HOST=https://cloud.langfuse.com
```

每个 task 自动上报：traces / spans / generations。

### 9.3 OpenTelemetry

```env
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME=deepsearch-core
```

---

## 10. 故障排查

| 症状 | 可能原因 | 排查 |
|------|---------|------|
| MCP 不出现在 Claude Desktop | 配置路径错 / 进程启动失败 | 看 Claude Desktop 日志 |
| `quick_search` 超时 | 搜索引擎 key 没配 / 网络 | `deepsearch healthcheck` |
| Steer 不生效 | scope 错配 / 任务已结束 | 查 events 表 `steer_received` |
| Token 消耗暴涨 | 没启 prompt caching | 看 `LLM_TOKEN_USAGE` 事件 |
| 中文搜索质量差 | policy 用错了 | 显式 `--policy chinese-finance` |

```bash
# 健康检查全套
deepsearch healthcheck

# 输出：
# ✅ LLM endpoint reachable
# ✅ Tavily key valid
# ⚠️ Cohere key not set (reranker disabled)
# ✅ SQLite store writable
```

---

## 11. 升级

```bash
# uv
uv lock --upgrade-package deepsearch-core
uv sync

# pip
pip install -U deepsearch-core

# Docker
docker pull ghcr.io/kkkano/deepsearch-core:latest
docker compose up -d
```

升级前看 [CHANGELOG.md](../CHANGELOG.md)。
