"""FastAPI HTTP API：REST + SSE + WebSocket。

启动：
    uvicorn deepsearch_core.adapters.http.app:app
    或：python -m deepsearch_core.adapters.http.app
    或：deepsearch-server
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from deepsearch_core.config import get_config
from deepsearch_core.engine.state import RunConfig, State
from deepsearch_core.exceptions import DeepSearchError, TaskNotFoundError
from deepsearch_core.facade import DeepSearch

logger = structlog.get_logger(__name__)

app = FastAPI(
    title="deepsearch-core",
    version="0.1.0",
    description="Protocol-agnostic deep research engine",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_ds: DeepSearch | None = None
_running_tasks: dict[str, asyncio.Task] = {}


def get_ds() -> DeepSearch:
    global _ds
    if _ds is None:
        _ds = DeepSearch(get_config())
    return _ds


# ============================================================
# Models
# ============================================================


class QuickSearchRequest(BaseModel):
    query: str
    policy: str = "general"
    max_results: int = 5


class DeepSearchRequest(BaseModel):
    query: str
    depth: int = Field(default=3, ge=1, le=5)
    policy: str = "general"
    max_agents: int = Field(default=4, ge=1, le=8)
    timeout_seconds: int = Field(default=300, ge=30, le=600)
    enable_steer: bool = True


class SteerRequest(BaseModel):
    content: str
    scope: str = "global"


# ============================================================
# Routes
# ============================================================


@app.get("/")
def root():
    return {"name": "deepsearch-core", "version": "0.1.0", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/search/quick")
async def quick_search(req: QuickSearchRequest):
    ds = get_ds()
    try:
        result = await ds.quick_search(req.query, policy=req.policy)
        return result
    except DeepSearchError as e:
        raise HTTPException(status_code=500, detail=e.to_dict())


@app.post("/v1/search/deep")
async def deep_search(req: DeepSearchRequest):
    """同步深度搜索（不推荐，建议用 /async + /poll）。"""
    ds = get_ds()
    try:
        result = await ds.deep_search(
            req.query,
            depth=req.depth,
            policy=req.policy,
            max_agents=req.max_agents,
            timeout_seconds=req.timeout_seconds,
            enable_steer=req.enable_steer,
        )
        return result
    except DeepSearchError as e:
        raise HTTPException(status_code=500, detail=e.to_dict())


@app.post("/v1/search/deep/async")
async def deep_search_async(req: DeepSearchRequest):
    """异步启动，立即返回 task_id。"""
    ds = get_ds()

    config = RunConfig(
        goal=req.query,
        depth=req.depth,
        max_agents=req.max_agents,
        policy=req.policy,
        timeout_seconds=req.timeout_seconds,
        enable_steer=req.enable_steer,
    )
    state = State(config=config)
    ctx = ds._build_context(req.policy)
    runner = ds._build_runner(ctx)

    task = asyncio.create_task(runner.run(state, start_node="check_clarity"))
    _running_tasks[state.run_id] = task

    return {
        "task_id": state.run_id,
        "status": "running",
        "eta_seconds": 30 + req.depth * 15,
        "poll_url": f"/v1/runs/{state.run_id}",
        "stream_url": f"/v1/runs/{state.run_id}/stream",
        "steer_url": f"/v1/runs/{state.run_id}/steer",
    }


@app.get("/v1/runs/{run_id}")
async def get_run(run_id: str):
    ds = get_ds()
    run = ds.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="task not found")
    return run


@app.get("/v1/runs/{run_id}/events")
async def get_run_events(run_id: str):
    ds = get_ds()
    events = [e.model_dump(mode="json") for e in ds.list_events(run_id)]
    return {"run_id": run_id, "events": events}


@app.get("/v1/runs/{run_id}/stream")
async def stream_run(run_id: str):
    """SSE 流式订阅事件。"""
    ds = get_ds()

    async def event_gen():
        runner_task = _running_tasks.get(run_id)
        if runner_task is None:
            yield f"data: {json.dumps({'error': 'task not found'})}\n\n"
            return

        # 简化：直接把 store 里的事件流出来 + poll
        last_seq = -1
        while True:
            events = ds.list_events(run_id)
            new = [e for e in events if e.seq > last_seq]
            for e in new:
                last_seq = e.seq
                yield f"data: {json.dumps(e.model_dump(mode='json'))}\n\n"
            if runner_task.done():
                yield "data: [DONE]\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/v1/runs/{run_id}/steer")
async def steer_run(run_id: str, req: SteerRequest):
    ds = get_ds()
    if run_id not in _running_tasks and not ds.get_run(run_id):
        raise HTTPException(status_code=404, detail="task not found")

    cmd = ds.steer(run_id, req.content, scope=req.scope)
    return {
        "accepted": True,
        "cmd_id": cmd.cmd_id,
        "queued_at": cmd.created_at.isoformat(),
        "scope": cmd.scope.value,
    }


@app.delete("/v1/runs/{run_id}")
async def cancel_run(run_id: str):
    task = _running_tasks.pop(run_id, None)
    if task and not task.done():
        task.cancel()
    return {"cancelled": True}


@app.websocket("/ws/runs/{run_id}")
async def ws_run(websocket: WebSocket, run_id: str):
    """WebSocket 双向通信：服务端推送事件，客户端发送 steer。"""
    await websocket.accept()
    ds = get_ds()

    last_seq = -1
    try:
        # 启动两个 task：推送 + 接收
        async def push_events():
            nonlocal last_seq
            while True:
                events = ds.list_events(run_id)
                for e in events:
                    if e.seq > last_seq:
                        last_seq = e.seq
                        await websocket.send_json(e.model_dump(mode="json"))
                if run_id not in _running_tasks or _running_tasks[run_id].done():
                    break
                await asyncio.sleep(0.5)

        async def recv_steer():
            while True:
                msg = await websocket.receive_json()
                if msg.get("type") == "steer":
                    ds.steer(run_id, msg.get("content", ""), scope=msg.get("scope", "global"))
                    await websocket.send_json({"type": "steer_ack", "accepted": True})

        await asyncio.gather(push_events(), recv_steer(), return_exceptions=True)
    except WebSocketDisconnect:
        logger.info("ws_disconnected", run_id=run_id)


def run():
    """供 console_script 调用。"""
    import uvicorn

    cfg = get_config()
    uvicorn.run(
        "deepsearch_core.adapters.http.app:app",
        host=cfg.server.http_host,
        port=cfg.server.http_port,
        reload=False,
    )


if __name__ == "__main__":
    run()
