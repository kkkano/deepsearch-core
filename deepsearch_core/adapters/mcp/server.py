"""MCP Server：暴露 quick_search / start_deep_search / poll_search / steer / cancel_search 工具。

支持的 transport（v0.1.x）：
  - stdio (✅ 已实现，Claude Desktop / Cursor / Cline)

计划在 v0.2 提供：
  - http (Cherry Studio / 远程)
  - sse / streamable-http (2025 spec)

如果当前版本需要远程访问，请改用 HTTP API（FastAPI on port 8000），路由覆盖
与 MCP 工具一一对应：
  - POST /v1/search/quick       ↔ quick_search
  - POST /v1/search/deep/async  ↔ start_deep_search
  - GET  /v1/runs/{id}/poll     ↔ poll_search
  - POST /v1/runs/{id}/steer    ↔ steer
  - DELETE /v1/runs/{id}        ↔ cancel_search

启动：
  python -m deepsearch_core.adapters.mcp                      # stdio (only)
  # 远程访问改用 HTTP API:
  uvicorn deepsearch_core.adapters.http.app:app --port 8000
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import structlog

from deepsearch_core import __version__
from deepsearch_core.config import get_config
from deepsearch_core.exceptions import (
    DeepSearchError,
)
from deepsearch_core.facade import DeepSearch

logger = structlog.get_logger(__name__)


# 全局单例 DeepSearch（其内置 RunManager 跨适配统一）
_global_ds: DeepSearch | None = None


def _get_ds() -> DeepSearch:
    global _global_ds
    if _global_ds is None:
        _global_ds = DeepSearch(get_config())
    return _global_ds


# ============================================================
# Tool Implementations
# ============================================================


async def tool_quick_search(query: str, policy: str = "general", max_results: int = 5) -> dict:
    """Fast single-round search for simple factual questions."""
    ds = _get_ds()
    result = await ds.quick_search(query, policy=policy)
    return {
        "answer": result.get("report", {}).get("body_markdown", "") if result.get("report") else "",
        "citations": result.get("citations", [])[:max_results],
        "elapsed_seconds": result.get("elapsed_seconds", 0),
        "cache_hit": False,
    }


async def tool_start_deep_search(
    query: str,
    depth: int = 3,
    policy: str = "general",
    max_agents: int = 4,
) -> dict:
    """Launch deep search task in background, return task_id immediately."""
    ds = _get_ds()
    return await ds.manager.start(query=query, depth=depth, policy=policy, max_agents=max_agents)


async def tool_poll_search(task_id: str, wait_seconds: int = 25) -> dict:
    """Long-poll for deep search results, max 25s wait. Real report returned when complete."""
    ds = _get_ds()
    return await ds.manager.poll(task_id, wait_seconds=wait_seconds)


async def tool_steer(task_id: str, command: str, scope: str = "global") -> dict:
    """Inject a steer command into a running task."""
    ds = _get_ds()
    cmd = ds.manager.steer(task_id, command, scope=scope)
    return {
        "accepted": True,
        "cmd_id": cmd.cmd_id,
        "queued_at": cmd.created_at.isoformat(),
        "scope": cmd.scope.value,
    }


async def tool_cancel_search(task_id: str) -> dict:
    """Cancel a running search task."""
    ds = _get_ds()
    return await ds.manager.cancel(task_id)


# ============================================================
# MCP Protocol Wiring
# ============================================================


def main():
    parser = argparse.ArgumentParser(description="deepsearch-core MCP server")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "http", "sse"])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    try:
        # 导入官方 mcp SDK
        import mcp.types as types
        from mcp.server import NotificationOptions, Server
        from mcp.server.models import InitializationOptions
    except ImportError:
        print("ERROR: mcp package not installed. Run: pip install mcp>=1.0.0", file=sys.stderr)
        sys.exit(1)

    server = Server("deepsearch-core")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="quick_search",
                description=(
                    "Fast single-round search for simple factual questions. "
                    "Returns answer in <8 seconds with 3-5 cited sources. "
                    "USE WHEN: user asks for current events, definitions, latest news, simple fact lookup. "
                    "DO NOT USE FOR: complex analysis, multi-source comparison, future predictions."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "policy": {
                            "type": "string",
                            "enum": ["general", "finance", "tech", "academic"],
                            "default": "general",
                        },
                        "max_results": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="start_deep_search",
                description=(
                    "Launch a deep research task running in background. "
                    "Returns task_id immediately. "
                    "USE WHEN: question requires multi-source comparison, in-depth analysis, "
                    "future predictions, or comprehensive review. "
                    "After calling, use poll_search to get results."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "depth": {"type": "integer", "default": 3, "minimum": 1, "maximum": 5},
                        "policy": {"type": "string", "default": "general"},
                        "max_agents": {"type": "integer", "default": 4},
                    },
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="poll_search",
                description=(
                    "Poll for deep search results. Long-polls up to wait_seconds (max 25). "
                    "Returns partial result if still running, or final result if done. "
                    "CALL REPEATEDLY until status='completed'."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "wait_seconds": {"type": "integer", "default": 25, "maximum": 25},
                    },
                    "required": ["task_id"],
                },
            ),
            types.Tool(
                name="steer",
                description=(
                    "Inject a steering command into a running task. "
                    "The agent will pause at next safe checkpoint, apply the command, and re-plan."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "command": {"type": "string"},
                        "scope": {
                            "type": "string",
                            "enum": ["current_step", "global", "next_step"],
                            "default": "global",
                        },
                    },
                    "required": ["task_id", "command"],
                },
            ),
            types.Tool(
                name="cancel_search",
                description="Cancel a running deep search task.",
                inputSchema={
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        try:
            if name == "quick_search":
                result = await tool_quick_search(**arguments)
            elif name == "start_deep_search":
                result = await tool_start_deep_search(**arguments)
            elif name == "poll_search":
                result = await tool_poll_search(**arguments)
            elif name == "steer":
                result = await tool_steer(**arguments)
            elif name == "cancel_search":
                result = await tool_cancel_search(**arguments)
            else:
                result = {"error": f"Unknown tool: {name}"}
        except DeepSearchError as e:
            result = e.to_dict()
        except Exception as e:
            logger.exception("tool_error", tool=name)
            result = {"error": str(e), "type": type(e).__name__}

        import json

        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    # Run server
    if args.transport == "stdio":
        from mcp.server.stdio import stdio_server

        async def run_stdio():
            async with stdio_server() as (read_stream, write_stream):
                await server.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name="deepsearch-core",
                        server_version=__version__,
                        capabilities=server.get_capabilities(
                            notification_options=NotificationOptions(),
                            experimental_capabilities={},
                        ),
                    ),
                )

        asyncio.run(run_stdio())
    elif args.transport in ("http", "sse"):
        # HTTP / SSE 模式（v0.2 完善）
        print(f"HTTP transport on :{args.port} — coming in v0.2", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
