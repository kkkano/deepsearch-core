"""HyDE: Hypothetical Document Embedding。

通过让 LLM 先生成"假设性回答"，再用假设回答去检索。比直接用 query embedding 召回率更高。
"""

from __future__ import annotations

from deepsearch_core.llm.client import LLMClient, Message

HYDE_PROMPT = """You are a search query optimizer.

Task: Given a user's question, write a concise, fact-dense **hypothetical answer** (100-200 words) as if you knew the answer perfectly. This will be used to find relevant documents via embedding search.

Rules:
- Use specific terminology, names, dates, numbers (even if invented)
- Match the style of authoritative sources (news, papers, official docs)
- Single paragraph, no headings
- No "I think" or hedging language
- Output ONLY the hypothetical answer, no preamble

Question: {question}

Hypothetical answer:"""


class HyDEGenerator:
    """HyDE: 用 LLM 生成假设性回答用于检索。"""

    def __init__(self, llm: LLMClient, model: str):
        self.llm = llm
        self.model = model

    async def generate(self, question: str) -> str:
        resp = await self.llm.chat(
            model=self.model,
            messages=[Message(role="user", content=HYDE_PROMPT.format(question=question))],
            temperature=0.3,
            max_tokens=400,
        )
        return resp.content.strip()
