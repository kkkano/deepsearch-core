"""轻量 LLM client：httpx 直连任何 OpenAI 兼容 endpoint。

支持的 provider：
- Anthropic（通过 OpenAI compatibility layer）
- OpenAI
- DeepSeek
- Qwen
- x666.me（主人现有）
- 本地 vLLM / SGLang
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx
import structlog
from pydantic import BaseModel

from deepsearch_core.exceptions import LLMError

logger = structlog.get_logger(__name__)


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class LLMResponse(BaseModel):
    content: str
    tool_calls: list[ToolCall] = []
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    raw: dict[str, Any] | None = None


class LLMClient:
    """OpenAI 兼容 chat completion client。

    示例：
        client = LLMClient(base_url="https://api.anthropic.com/v1", api_key="sk-...")
        resp = await client.chat(
            model="claude-sonnet-4-6",
            messages=[Message(role="user", content="Hello")],
        )
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 120.0,
        max_retries: int = 2,
        extra_headers: dict[str, str] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                **(extra_headers or {}),
            },
        )

    async def chat(
        self,
        model: str,
        messages: list[Message],
        temperature: float = 0.0,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        response_format: dict | None = None,
        cache_control: bool = False,
    ) -> LLMResponse:
        """非流式 chat completion。"""
        body: dict[str, Any] = {
            "model": model,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
        if response_format:
            body["response_format"] = response_format

        # Anthropic prompt caching：在最后一条 system message 上加 cache_control
        if cache_control and messages and messages[0].role == "system":
            body["messages"][0]["cache_control"] = {"type": "ephemeral"}

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = await self._client.post(f"{self.base_url}/chat/completions", json=body)
                if resp.status_code >= 400:
                    raise LLMError(
                        f"LLM API {resp.status_code}: {resp.text[:200]}",
                        status_code=resp.status_code,
                        body=resp.text[:500],
                    )
                data = resp.json()
                return self._parse_response(data)
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_err = e
                if attempt < self.max_retries:
                    logger.warning("llm_retry", attempt=attempt + 1, error=str(e))
                    continue
                raise LLMError(f"LLM network error: {e}") from e

        if last_err:
            raise LLMError(f"LLM call failed: {last_err}") from last_err
        raise LLMError("LLM call failed: unknown")

    async def stream(
        self,
        model: str,
        messages: list[Message],
        temperature: float = 0.0,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[dict]:
        """流式输出，每个 chunk 是 OpenAI 标准 delta dict。"""
        body: dict[str, Any] = {
            "model": model,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            body["tools"] = tools

        async with self._client.stream("POST", f"{self.base_url}/chat/completions", json=body) as resp:
            if resp.status_code >= 400:
                content = await resp.aread()
                raise LLMError(f"LLM stream {resp.status_code}: {content[:200]}")
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[len("data: ") :]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    yield json.loads(data_str)
                except json.JSONDecodeError:
                    continue

    def _parse_response(self, data: dict) -> LLMResponse:
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        usage = data.get("usage", {})

        tool_calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                args = {}
            tool_calls.append(ToolCall(id=tc.get("id", ""), name=tc["function"]["name"], arguments=args))

        return LLMResponse(
            content=msg.get("content") or "",
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", "stop"),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            cached_tokens=usage.get("cache_read_input_tokens", 0),
            raw=data,
        )

    async def complete_json(self, model: str, prompt: str, schema: dict | None = None) -> dict:
        """便利方法：返回 JSON 对象。"""
        messages = [Message(role="user", content=prompt)]
        kwargs: dict = {}
        if schema:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": schema}
        else:
            kwargs["response_format"] = {"type": "json_object"}
        resp = await self.chat(model=model, messages=messages, **kwargs)
        try:
            return json.loads(resp.content)
        except json.JSONDecodeError as e:
            raise LLMError(f"Expected JSON, got: {resp.content[:200]}") from e

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()
