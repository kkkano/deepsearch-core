"""Supervisor 与 check_clarity 节点。"""

from __future__ import annotations

import structlog

from deepsearch_core.agents.base import AgentContext
from deepsearch_core.engine.state import State

logger = structlog.get_logger(__name__)


CLARITY_PROMPT = """Decide if the user's research goal is clear enough to start.

Goal: {goal}

Respond with strict JSON:
{{
  "is_clear": true/false,
  "reason": "...",
  "clarification_needed": "What to ask the user, if any"
}}

A goal is clear if it has a definite subject and decidable scope.
Be lenient — only return is_clear=false for genuinely vague goals like "tell me something".
"""


def make_check_clarity_node(ctx: AgentContext):
    async def check_clarity_node(state: State) -> tuple[State, str]:
        # v0.1: 简化 — 默认 clear，跳过澄清
        # v0.2: 真实调 LLM 判断，模糊则触发 elicitation
        return state.with_update(clarification="ok"), "supervisor"

    return check_clarity_node


def make_supervisor_node(ctx: AgentContext):
    async def supervisor_node(state: State) -> tuple[State, str]:
        # 决策路由：根据当前 state 判断下一步
        # v0.1 简化版：固定路径 planner -> fan_out -> critic -> reporter

        if state.plan is None:
            return state, "planner"
        if not state.evidence:
            return state, "fan_out_research"
        if state.critic_report is None:
            return state, "critic"
        if state.report is None:
            return state, "reporter"

        return state, "END"

    return supervisor_node


# 简化导出（runner 直接 import）
async def check_clarity_node(state: State) -> tuple[State, str]:
    return state.with_update(clarification="ok"), "supervisor"


async def supervisor_node(state: State) -> tuple[State, str]:
    if state.plan is None:
        return state, "planner"
    if not state.evidence:
        return state, "fan_out_research"
    if state.critic_report is None:
        return state, "critic"
    if state.report is None:
        return state, "reporter"
    return state, "END"
