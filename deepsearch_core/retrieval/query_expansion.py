"""Query Expansion: 把 1 个 query 扩成 N 个变体。"""

from __future__ import annotations

import structlog

from deepsearch_core.llm.client import LLMClient, Message, json_list, parse_json_payload

logger = structlog.get_logger(__name__)

EXPANSION_PROMPT = """Generate {n} diverse search query variations for the following question.

Variations should:
- Cover different angles (official, news, academic, community)
- Use different keyword combinations
- Range from broad to specific
- Be in the same language as the input

Output a JSON array of strings, e.g. ["query 1", "query 2", "query 3"].

Question: {question}

JSON array:"""


class QueryExpander:
    def __init__(self, llm: LLMClient, model: str):
        self.llm = llm
        self.model = model

    async def expand(self, question: str, n: int = 3) -> list[str]:
        prompt = EXPANSION_PROMPT.format(question=question, n=n)
        resp = await self.llm.chat(
            model=self.model,
            messages=[Message(role="user", content=prompt)],
            temperature=0.5,
            max_tokens=1000,
            response_format={"type": "json_object"},
        )
        try:
            data = json_list(parse_json_payload(resp.content))
            if not data:
                return [question]
            return [question, *[str(q) for q in data[:n]]]
        except ValueError:
            logger.warning("query_expansion_parse_failed", content=resp.content[:100])
            return [question]
