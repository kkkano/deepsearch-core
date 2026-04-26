"""测试 v0.1.3 MEDIUM: _build_completed_payload error 字段类型统一。"""

from __future__ import annotations

from deepsearch_core.engine.manager import RunManager


class _StubStore:
    def get_run(self, task_id):
        return self._run


class _FakeDS:
    def __init__(self, store):
        self.store = store


def _make_manager(run, persisted=None):
    store = _StubStore()
    store._run = run
    fake_ds = _FakeDS(store)
    return RunManager(fake_ds), persisted  # type: ignore


def test_error_is_none_when_completed_cleanly():
    manager, _ = _make_manager({"status": "completed"})
    payload = manager._build_completed_payload("t1", {"status": "completed"}, persisted=None)
    assert payload["error"] is None
    assert isinstance(payload["error"], type(None))


def test_error_is_str_when_persisted_error_present():
    manager, _ = _make_manager({"status": "failed"})
    persisted = {"error": "LLM 502 from upstream"}
    payload = manager._build_completed_payload("t1", {"status": "failed"}, persisted)
    assert payload["error"] == "LLM 502 from upstream"
    assert isinstance(payload["error"], str)


def test_error_is_str_when_status_failed_no_message():
    manager, _ = _make_manager({"status": "timeout"})
    payload = manager._build_completed_payload("t1", {"status": "timeout"}, persisted=None)
    assert payload["error"] == "timeout"
    assert isinstance(payload["error"], str)


def test_error_is_never_bool():
    """关键回归：旧实现会返回 bool，新实现禁止。"""
    for status in ("failed", "timeout", "cancelled", "completed", "running"):
        manager, _ = _make_manager({"status": status})
        payload = manager._build_completed_payload("t1", {"status": status}, persisted=None)
        assert not isinstance(payload["error"], bool), (
            f"error must never be bool, got {type(payload['error'])} for status={status}"
        )
