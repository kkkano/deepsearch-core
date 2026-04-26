"""测试 HIGH-1: facade 的 deep_search/quick_search/stream 不再有 kwargs 重复传参 TypeError。"""

from __future__ import annotations

import inspect

from deepsearch_core.agents.planner import _normalize_plan_payload
from deepsearch_core.engine.state import RunConfig
from deepsearch_core.facade import DeepSearch
from deepsearch_core.llm.client import json_list, json_object, parse_json_payload


def test_deep_search_signature_explicit_params():
    """deep_search 必须显式接受 max_agents/timeout_seconds/enable_steer。"""
    sig = inspect.signature(DeepSearch.deep_search)
    params = sig.parameters
    assert "max_agents" in params
    assert "timeout_seconds" in params
    assert "enable_steer" in params
    # 多余的 kwargs 应该是 **extra（不再叫 kwargs，避免冲突）
    assert any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())


def test_quick_search_signature_explicit_timeout():
    sig = inspect.signature(DeepSearch.quick_search)
    assert "timeout_seconds" in sig.parameters


def test_stream_signature_explicit_params():
    sig = inspect.signature(DeepSearch.stream)
    assert "max_agents" in sig.parameters
    assert "timeout_seconds" in sig.parameters
    assert "enable_steer" in sig.parameters


def test_run_config_extra_field_accepts_dict():
    """RunConfig.extra 接受任意 dict，多余 kwargs 进这里。"""
    cfg = RunConfig(goal="x", extra={"foo": "bar", "depth_override": 99})
    assert cfg.extra["foo"] == "bar"


def test_parse_json_payload_accepts_fenced_object():
    data = parse_json_payload('```json\n{"sub_queries": [{"text": "q"}]}\n```')
    assert json_object(data)["sub_queries"][0]["text"] == "q"


def test_parse_json_payload_accepts_text_wrapped_array():
    data = parse_json_payload('Here is the JSON:\n[{"text": "q1"}, {"text": "q2"}]\nDone.')
    assert json_list(data)[1]["text"] == "q2"


def test_json_object_wraps_array_for_planner_compatibility():
    data = json_object([{"text": "q1"}, {"text": "q2"}])
    assert data["items"][0]["text"] == "q1"


def test_planner_accepts_provider_array_payload():
    data = _normalize_plan_payload([
        {
            "rationale": "single wrapper",
            "sub_queries": [{"text": "q1", "priority": 10}],
        }
    ])
    assert data["sub_queries"][0]["text"] == "q1"


def test_planner_treats_array_as_sub_queries():
    data = _normalize_plan_payload([{"text": "q1"}, {"text": "q2"}])
    assert data["sub_queries"][1]["text"] == "q2"
