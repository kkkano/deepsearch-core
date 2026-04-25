"""Critic 节点：冲突检测 + 反方论据 + 缺口识别。"""

from __future__ import annotations

import json

import structlog

from deepsearch_core.agents.base import AgentContext
from deepsearch_core.engine.state import CriticReport, State
from deepsearch_core.llm.client import Message
from deepsearch_core.prompts import CRITIC_SYSTEM_PROMPT

logger = structlog.get_logger(__name__)


def make_critic_node(ctx: AgentContext):
    async def critic_node(state: State) -> tuple[State, str]:
        if not state.evidence:
            return state.with_update(critic_report=CriticReport(confidence=0.0)), "reporter"

        addon = ctx.policy.prompt_addons.get("critic", "")
        system_prompt = CRITIC_SYSTEM_PROMPT + (f"\n\n## Domain guidance\n{addon}" if addon else "")

        evidence_summary = "\n\n".join(
            f"[{i + 1}] ({e.domain}) {e.title}\n{e.snippet[:400]}"
            for i, e in enumerate(state.evidence[:20])
        )

        user_prompt = (
            f"Goal: {state.config.goal}\n\n"
            f"Evidence collected:\n{evidence_summary}\n\n"
            f"Analyze and output strict JSON."
        )

        try:
            resp = await ctx.llm.chat(
                model=ctx.critic_model,
                messages=[
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=user_prompt),
                ],
                temperature=0.2,
                max_tokens=1500,
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.content)
            state.token_usage.add(resp.prompt_tokens, resp.completion_tokens, resp.cached_tokens)
        except Exception as e:
            logger.warning("critic_fallback", error=str(e))
            data = {
                "confidence": 0.6,
                "conflicts": [],
                "counter_arguments": [],
                "missing_info": [],
                "verdict": "READY_TO_REPORT",
            }

        report = CriticReport(
            confidence=float(data.get("confidence", 0.5)),
            conflicts=list(data.get("conflicts", [])),
            counter_arguments=list(data.get("counter_arguments", [])),
            missing_info=list(data.get("missing_info", [])),
        )

        new_state = state.with_update(critic_report=report)
        return new_state, "reporter"

    return critic_node


async def critic_node(state: State) -> tuple[State, str]:
    """占位 stub。"""
    report = CriticReport(confidence=0.7)
    return state.with_update(critic_report=report), "reporter"
