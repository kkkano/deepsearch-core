"""EventStore: SQLite 事件溯源 + steer 队列 + query cache。

线程/异步安全：使用 sqlite3 的 isolation level 配合显式事务。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from deepsearch_core.engine.events import Event, EventType
from deepsearch_core.engine.state import State
from deepsearch_core.engine.steer import SteerCommand, SteerScope
from deepsearch_core.store.schema import SCHEMA_SQL


def _parse_dsn(dsn: str) -> str:
    """支持 'sqlite:///path/to.db' 或纯路径。"""
    if dsn.startswith("sqlite:///"):
        return dsn[len("sqlite:///") :]
    return dsn


class EventStore:
    """SQLite 事件存储。"""

    # ---- 修复 HIGH-2：增量迁移声明 ----
    # 每个 (table, column, ddl) 元组：发现旧 db 缺列时执行 ALTER TABLE ADD COLUMN
    _MIGRATIONS: list[tuple[str, str, str]] = [
        ("runs", "result_json", "ALTER TABLE runs ADD COLUMN result_json TEXT"),
        ("runs", "error", "ALTER TABLE runs ADD COLUMN error TEXT"),
    ]

    def __init__(self, dsn: str = "sqlite:///./runs.db"):
        self.path = _parse_dsn(dsn)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA_SQL)
        self._migrate()

    def _migrate(self) -> None:
        """旧 db 升级：CREATE TABLE IF NOT EXISTS 不会改 schema，必须显式 ALTER。"""
        for table, column, ddl in self._MIGRATIONS:
            cur = self._conn.execute(f"PRAGMA table_info({table})")
            existing = {row[1] for row in cur.fetchall()}
            if column not in existing:
                try:
                    self._conn.execute(ddl)
                except sqlite3.OperationalError:
                    # 并发场景：另一个进程刚加过，忽略
                    pass

    # ---------- runs ----------

    def create_run(self, state: State) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO runs (run_id, goal, config_json, status, created_at) VALUES (?,?,?,?,?)",
                (
                    state.run_id,
                    state.config.goal,
                    state.config.model_dump_json(),
                    state.status.value,
                    state.started_at.isoformat(),
                ),
            )

    def update_run_status(self, run_id: str, status: str, finished_at: datetime | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET status=?, finished_at=? WHERE run_id=?",
                (status, finished_at.isoformat() if finished_at else None, run_id),
            )

    def finish_run(self, state: State) -> None:
        """运行结束时持久化最终结果（report / evidence / critic / token_usage / error）。"""
        result = {
            "report": state.report.model_dump(mode="json") if state.report else None,
            "evidence": [e.model_dump(mode="json") for e in state.evidence],
            "critic": state.critic_report.model_dump(mode="json") if state.critic_report else None,
            "token_usage": state.token_usage.model_dump(mode="json"),
            "elapsed_seconds": state.elapsed_seconds(),
            "step_count": state.step_count,
        }
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET status=?, finished_at=?, result_json=?, error=? WHERE run_id=?",
                (
                    state.status.value,
                    (state.finished_at or datetime.utcnow()).isoformat(),
                    json.dumps(result, default=str, ensure_ascii=False),
                    state.last_error,
                    state.run_id,
                ),
            )

    def get_run_result(self, run_id: str) -> dict[str, Any] | None:
        """读取已持久化的最终结果。未结束返回 None。"""
        cur = self._conn.execute("SELECT result_json, error FROM runs WHERE run_id=?", (run_id,))
        row = cur.fetchone()
        if not row:
            return None
        result_json, error = row
        if not result_json:
            return None
        data = json.loads(result_json)
        if error:
            data["error"] = error
        return data

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        cur = self._conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row, strict=False))

    def list_runs(self, limit: int = 50, status: str | None = None) -> list[dict]:
        if status:
            cur = self._conn.execute(
                "SELECT * FROM runs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            cur = self._conn.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]

    # ---------- events ----------

    def append_event(self, event: Event) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (run_id, seq, type, payload_json, timestamp) VALUES (?,?,?,?,?)",
                (
                    event.run_id,
                    event.seq,
                    event.type.value,
                    json.dumps(event.payload, default=str, ensure_ascii=False),
                    event.timestamp.isoformat(),
                ),
            )

    def replay(self, run_id: str) -> Iterator[Event]:
        cur = self._conn.execute(
            "SELECT run_id, seq, type, payload_json, timestamp FROM events WHERE run_id=? ORDER BY event_id",
            (run_id,),
        )
        for run_id_, seq, type_, payload, ts in cur:
            yield Event(
                run_id=run_id_,
                seq=seq,
                type=EventType(type_),
                payload=json.loads(payload),
                timestamp=datetime.fromisoformat(ts),
            )

    # ---------- steer ----------

    def add_steer(self, run_id: str, content: str, scope: SteerScope = SteerScope.GLOBAL) -> SteerCommand:
        cmd = SteerCommand(run_id=run_id, content=content, scope=scope)
        with self._lock:
            self._conn.execute(
                "INSERT INTO steer_commands (cmd_id, run_id, content, scope, applied, created_at) VALUES (?,?,?,?,0,?)",
                (cmd.cmd_id, cmd.run_id, cmd.content, cmd.scope.value, cmd.created_at.isoformat()),
            )
        return cmd

    def pop_pending_steer(self, run_id: str) -> SteerCommand | None:
        """取出最早的 unapplied steer，但**不**标 applied（runner 应用后再标）。"""
        with self._lock:
            cur = self._conn.execute(
                "SELECT cmd_id, run_id, content, scope, created_at FROM steer_commands "
                "WHERE run_id=? AND applied=0 ORDER BY created_at LIMIT 1",
                (run_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        cmd_id, rid, content, scope, created_at = row
        return SteerCommand(
            cmd_id=cmd_id,
            run_id=rid,
            content=content,
            scope=SteerScope(scope),
            created_at=datetime.fromisoformat(created_at),
            applied=False,
        )

    def mark_steer_applied(self, cmd: SteerCommand) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE steer_commands SET applied=1, applied_at=?, applied_at_step=? WHERE cmd_id=?",
                (
                    (cmd.applied_at or datetime.utcnow()).isoformat(),
                    cmd.applied_at_step,
                    cmd.cmd_id,
                ),
            )

    def list_steer(self, run_id: str) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM steer_commands WHERE run_id=? ORDER BY created_at",
            (run_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]

    # ---------- query cache ----------

    def cache_get(self, query_hash: str) -> dict | None:
        cur = self._conn.execute(
            "SELECT response_json, expires_at FROM query_cache WHERE query_hash=?",
            (query_hash,),
        )
        row = cur.fetchone()
        if not row:
            return None
        response, expires_at = row
        if datetime.fromisoformat(expires_at) < datetime.utcnow():
            return None
        return json.loads(response)

    def cache_put(self, query_hash: str, query: str, policy: str, response: dict, ttl_seconds: int = 86400) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO query_cache (query_hash, query, policy, response_json, created_at, expires_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    query_hash,
                    query,
                    policy,
                    json.dumps(response, default=str, ensure_ascii=False),
                    datetime.utcnow().isoformat(),
                    (datetime.utcnow() + timedelta(seconds=ttl_seconds)).isoformat(),
                ),
            )

    def cache_evict_expired(self) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM query_cache WHERE expires_at < ?",
                (datetime.utcnow().isoformat(),),
            )
            return cur.rowcount

    def close(self) -> None:
        self._conn.close()
