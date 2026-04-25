"""Planner 节点：把目标拆成 N 个子查询。"""

from __future__ import annotations

import json

import structlog

from deepsearch_core.agents.base import AgentContext
from deepsearch_core.engine.state import Plan, State, SubQuery
from deepsearch_core.llm.client import Message
from deepsearch_core.prompts import PLANNER_SYSTEM_PROMPT

logger = structlog.get_logger(__name__)


def make_planner_node(ctx: AgentContext):
    async def planner_node(state: State) -> tuple[State, str]:
        n_queries = min(state.config.max_agents, 5)

        addon = ctx.policy.prompt_addons.get("planner", "")
        system_prompt = PLANNER_SYSTEM_PROMPT
        if addon:
            system_prompt += f"\n\n## Domain-specific guidance\n{addon}"

        # 注入 steer 内容（如果存在）
        steer_addon = ""
        if state.steer_payload:
            steer_addon = f"\n\n## ⚠️ User mid-flight directive\n{state.steer_payload['content']}"

        user_prompt = (
            f"Research goal: {state.config.goal}\n\n"
            f"Generate {n_queries} sub-queries.\n"
            f"Source policy: {ctx.policy.name}\n"
            f"{steer_addon}\n\n"
            f"Output JSON now."
        )

        revision = (state.plan.revision + 1) if state.plan else 1

        try:
            resp = await ctx.llm.chat(
                model=ctx.planner_model,
                messages=[
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=user_prompt),
                ],
                temperature=0.0,
                max_tokens=2000,
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.content)
            state.token_usage.add(resp.prompt_tokens, resp.completion_tokens, resp.cached_tokens)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("planner_fallback", error=str(e))
            # Fallback: 单 query 直通
            data = {
                "rationale": "Fallback: planner failed, using goal as single query.",
                "sub_queries": [{"text": state.config.goal, "angle": "general", "priority": 5}],
                "expected_outputs": ["Direct answer to the goal"],
            }

        sub_queries = [
            SubQuery(
                text=sq.get("text", ""),
                angle=sq.get("angle", "general"),
                priority=int(sq.get("priority", 5)),
            )
            for sq in data.get("sub_queries", [])
            if sq.get("text")
        ]

        # 兜底：保证至少一个 sub_query
        if not sub_queries:
            sub_queries = [SubQuery(text=state.config.goal, angle="general")]

        plan = Plan(
            rationale=data.get("rationale", ""),
            sub_queries=sub_queries,
            expected_outputs=data.get("expected_outputs", []),
            revision=revision,
        )

        new_state = state.with_update(plan=plan, steer_payload=None)
        return new_state, "fan_out_research"

    return planner_node


# Default fallback node (用于测试 / 单独 import)
async def planner_node(state: State) -> tuple[State, str]:
    """占位实现：实际请通过 make_planner_node(ctx) 创建。"""
    plan = Plan(
        rationale="Stub plan",
        sub_queries=[SubQuery(text=state.config.goal, angle="general")],
    )
    return state.with_update(plan=plan), "fan_out_research"
