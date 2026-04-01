from __future__ import annotations

from dataclasses import dataclass

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore[assignment]


@dataclass
class UsageInfo:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    text: str
    usage: UsageInfo


class LLMRateLimitError(RuntimeError):
    pass


class LLMGateway:
    def __init__(self, default_base_url: str, default_api_key: str, timeout_seconds: int) -> None:
        self.default_base_url = default_base_url
        self.default_api_key = default_api_key
        self.timeout_seconds = timeout_seconds
        self._clients: dict[tuple[str, str], AsyncOpenAI] = {}

    async def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        client = self._get_client(base_url=base_url, api_key=api_key)
        parts: list[str] = []
        usage = UsageInfo()
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    usage.prompt_tokens = getattr(chunk.usage, "prompt_tokens", 0) or 0
                    usage.completion_tokens = getattr(chunk.usage, "completion_tokens", 0) or 0
                    usage.total_tokens = getattr(chunk.usage, "total_tokens", 0) or 0
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None)
                if content:
                    parts.append(content)
            return LLMResponse(text="".join(parts).strip(), usage=usage)
        except Exception as exc:  # pragma: no cover
            if _is_rate_limit(exc):
                raise LLMRateLimitError(str(exc)) from exc
            raise

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.close()
        self._clients.clear()

    def _get_client(self, *, base_url: str | None, api_key: str | None) -> AsyncOpenAI:
        if AsyncOpenAI is None:  # pragma: no cover
            raise RuntimeError("Для работы с LLM нужен пакет openai")
        resolved_base_url = base_url or self.default_base_url
        resolved_api_key = api_key or self.default_api_key
        cache_key = (resolved_base_url, resolved_api_key)
        client = self._clients.get(cache_key)
        if client is None:
            client = AsyncOpenAI(
                base_url=resolved_base_url,
                api_key=resolved_api_key,
                timeout=self.timeout_seconds,
            )
            self._clients[cache_key] = client
        return client


def _is_rate_limit(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True
    text = str(exc).lower()
    return "rate limit" in text or "resource_exhausted" in text or "quota" in text
