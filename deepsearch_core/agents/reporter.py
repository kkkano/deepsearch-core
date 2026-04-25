"""Reporter 节点：合成最终报告。"""

from __future__ import annotations

import structlog

from deepsearch_core.agents.base import AgentContext
from deepsearch_core.engine.state import Citation, Report, State
from deepsearch_core.llm.client import Message
from deepsearch_core.prompts import REPORTER_SYSTEM_PROMPT

logger = structlog.get_logger(__name__)


def make_reporter_node(ctx: AgentContext):
    async def reporter_node(state: State) -> tuple[State, str]:
        addon = ctx.policy.prompt_addons.get("reporter", "")
        system_prompt = REPORTER_SYSTEM_PROMPT + (f"\n\n## Domain guidance\n{addon}" if addon else "")

        # 格式化证据 + critic
        evidence_block = "\n\n".join(
            f"[^{i + 1}]: ({e.domain}) {e.title}\n  URL: {e.url}\n  Snippet: {e.snippet[:300]}"
            for i, e in enumerate(state.evidence[:15])
        )

        critic_block = ""
        if state.critic_report:
            critic_block = (
                f"\n\nCritic confidence: {state.critic_report.confidence:.2f}\n"
                f"Conflicts: {state.critic_report.conflicts}\n"
                f"Counter-arguments: {state.critic_report.counter_arguments}\n"
                f"Missing info: {state.critic_report.missing_info}"
            )

        user_prompt = (
            f"Goal: {state.config.goal}\n\n"
            f"Evidence:\n{evidence_block}\n"
            f"{critic_block}\n\n"
            f"Write the final report now."
        )

        try:
            resp = await ctx.llm.chat(
                model=ctx.reporter_model,
                messages=[
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=user_prompt),
                ],
                temperature=0.3,
                max_tokens=4000,
            )
            body_md = resp.content
            state.token_usage.add(resp.prompt_tokens, resp.completion_tokens, resp.cached_tokens)
        except Exception as e:
            logger.warning("reporter_fallback", error=str(e))
            body_md = f"# Research Summary\n\n{state.config.goal}\n\n*Reporter failed: {e}*"

        citations = [
            Citation(
                index=i + 1,
                url=e.url,
                title=e.title,
                snippet=e.snippet[:200],
                domain=e.domain,
            )
            for i, e in enumerate(state.evidence[:15])
        ]

        report = Report(
            summary=body_md.split("\n", 1)[0][:500],
            body_markdown=body_md,
            citations=citations,
            confidence=state.critic_report.confidence if state.critic_report else 0.5,
        )

        return state.with_update(report=report), "END"

    return reporter_node


async def reporter_node(state: State) -> tuple[State, str]:
    """占位 stub。"""
    body = f"# Stub Report\n\nGoal: {state.config.goal}\n"
    return state.with_update(report=Report(summary=body, body_markdown=body)), "END"
