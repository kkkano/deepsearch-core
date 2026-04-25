"""测试 HIGH-2: 旧 SQLite db 自动添加 result_json/error 列。"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from deepsearch_core.store.store import EventStore


def test_migration_adds_result_json_and_error():
    """旧 db 没有这两列 → EventStore 启动后必须有。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)

    try:
        # 1. 模拟旧 schema：只有 v0.1.0 时的列
        conn = sqlite3.connect(str(path))
        conn.execute(
            """
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                goal TEXT NOT NULL,
                config_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                finished_at TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, NULL)",
            ("legacy_run", "old goal", "{}", "completed", "2026-04-01"),
        )
        conn.commit()
        conn.close()

        # 2. EventStore 启动应自动迁移
        store = EventStore(f"sqlite:///{path}")

        cur = store._conn.execute("PRAGMA table_info(runs)")
        cols = {row[1] for row in cur.fetchall()}
        assert "result_json" in cols
        assert "error" in cols

        # 3. 旧数据保留
        run = store.get_run("legacy_run")
        assert run is not None
        assert run["goal"] == "old goal"

        # 4. 新写入的字段可用
        from deepsearch_core.engine.state import RunConfig, State

        new_state = State(config=RunConfig(goal="new goal"))
        new_state = new_state.with_update(last_error="test error")
        store.create_run(new_state)
        store.finish_run(new_state)
        result = store.get_run_result(new_state.run_id)
        assert result is not None
        assert result.get("error") == "test error"

        store.close()
    finally:
        path.unlink(missing_ok=True)


def test_migration_idempotent():
    """重复启动 EventStore 不出错。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)

    try:
        store1 = EventStore(f"sqlite:///{path}")
        store1.close()
        # 第二次（列已存在）不报错
        store2 = EventStore(f"sqlite:///{path}")
        cur = store2._conn.execute("PRAGMA table_info(runs)")
        cols = {row[1] for row in cur.fetchall()}
        assert "result_json" in cols
        store2.close()
    finally:
        path.unlink(missing_ok=True)
