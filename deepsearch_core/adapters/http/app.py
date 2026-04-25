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

from deepsearch_core import __version__
from deepsearch_core.config import get_config
from deepsearch_core.engine.state import RunConfig, State
from deepsearch_core.exceptions import DeepSearchError, TaskNotFoundError
from deepsearch_core.facade import DeepSearch

logger = structlog.get_logger(__name__)

app = FastAPI(
    title="deepsearch-core",
    version=__version__,
    description="Protocol-agnostic deep research engine",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_ds: DeepSearch | None = None


def get_ds() -> DeepSearch:
    """全局单例，所有路由共享同一个 DeepSearch（含 manager + provider pool）。"""
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
    return {"name": "deepsearch-core", "version": __version__, "docs": "/docs"}


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
    """异步启动，立即返回 task_id（走统一 RunManager）。"""
    ds = get_ds()
    payload = await ds.manager.start(
        query=req.query,
        depth=req.depth,
        policy=req.policy,
        max_agents=req.max_agents,
        timeout_seconds=req.timeout_seconds,
        enable_steer=req.enable_steer,
    )
    task_id = payload["task_id"]
    payload.update(
        {
            "poll_url": f"/v1/runs/{task_id}",
            "long_poll_url": f"/v1/runs/{task_id}/poll",
            "stream_url": f"/v1/runs/{task_id}/stream",
            "steer_url": f"/v1/runs/{task_id}/steer",
        }
    )
    return payload


@app.get("/v1/runs/{run_id}/poll")
async def poll_run(run_id: str, wait_seconds: int = 25):
    """长轮询：最多等 25s 拿结果。"""
    ds = get_ds()
    try:
        return await ds.manager.poll(run_id, wait_seconds=wait_seconds)
    except Exception as e:
        raise HTTPException(status_code=404, detail={"code": getattr(e, "code", "NOT_FOUND"), "message": str(e)}) from e


@app.get("/v1/runs/{run_id}/result")
async def result_run(run_id: str):
    """直接拿持久化的最终结果（不等待）。"""
    ds = get_ds()
    result = ds.manager.result(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="result not available yet")
    return result


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
    """SSE 流式订阅事件（轮询 store + 检测 manager 任务终态）。"""
    ds = get_ds()

    async def event_gen():
        last_seq = -1
        while True:
            events = ds.list_events(run_id)
            new = [e for e in events if e.seq > last_seq]
            for e in new:
                last_seq = e.seq
                yield f"data: {json.dumps(e.model_dump(mode='json'))}\n\n"

            # 任务结束（无 in-flight task 且 store 已 finished）→ 退出
            run = ds.store.get_run(run_id)
            if run and run.get("finished_at"):
                yield "data: [DONE]\n\n"
                break
            if run is None:
                yield f"data: {json.dumps({'error': 'task not found'})}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/v1/runs/{run_id}/steer")
async def steer_run(run_id: str, req: SteerRequest):
    ds = get_ds()
    if not ds.get_run(run_id):
        raise HTTPException(status_code=404, detail="task not found")
    try:
        cmd = ds.manager.steer(run_id, req.content, scope=req.scope)
    except Exception as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {
        "accepted": True,
        "cmd_id": cmd.cmd_id,
        "queued_at": cmd.created_at.isoformat(),
        "scope": cmd.scope.value,
    }


@app.delete("/v1/runs/{run_id}")
async def cancel_run(run_id: str):
    ds = get_ds()
    return await ds.manager.cancel(run_id)


@app.websocket("/ws/runs/{run_id}")
async def ws_run(websocket: WebSocket, run_id: str):
    """WebSocket 双向通信：服务端推送事件，客户端发送 steer。

    ---- 修复 MEDIUM-3 ----
    用 FIRST_COMPLETED + cancel pending：push_events 完成（任务结束）就退出 recv_steer，
    避免 recv_steer 永远 await 卡住整个 ws handler。
    """
    await websocket.accept()
    ds = get_ds()

    last_seq = -1

    async def push_events():
        nonlocal last_seq
        while True:
            events = ds.list_events(run_id)
            for e in events:
                if e.seq > last_seq:
                    last_seq = e.seq
                    await websocket.send_json(e.model_dump(mode="json"))
            run = ds.store.get_run(run_id)
            if run and run.get("finished_at"):
                break
            await asyncio.sleep(0.5)

    async def recv_steer():
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "steer":
                try:
                    ds.manager.steer(run_id, msg.get("content", ""), scope=msg.get("scope", "global"))
                    await websocket.send_json({"type": "steer_ack", "accepted": True})
                except Exception as e:
                    await websocket.send_json({"type": "steer_ack", "accepted": False, "error": str(e)})

    push_task = asyncio.create_task(push_events())
    recv_task = asyncio.create_task(recv_steer())
    try:
        done, pending = await asyncio.wait(
            [push_task, recv_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        # 重新抛出异常（如果 push 异常退出）
        for t in done:
            exc = t.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
                logger.warning("ws_task_error", run_id=run_id, error=str(exc))
    except WebSocketDisconnect:
        logger.info("ws_disconnected", run_id=run_id)
        push_task.cancel()
        recv_task.cancel()


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
