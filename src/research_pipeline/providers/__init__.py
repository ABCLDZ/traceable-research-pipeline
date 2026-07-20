"""LLM Provider 抽象层。"""

from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class LLMRequest(BaseModel):
    prompt_name: str
    prompt_version: str
    system_prompt: str = ""
    user_prompt: str
    temperature: float = 0.1
    max_tokens: int = 4096
    model: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    retry_count: int = 0
    cached: bool = False
    error: Optional[str] = None
    raw_response: Optional[dict[str, Any]] = None


class LLMCallRecord(BaseModel):
    request: LLMRequest
    response: LLMResponse
    prompt_hash: str
    input_hash: str
    called_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    estimated_cost_usd: float = 0.0


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...

    @abstractmethod
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        ...


class LLMCache:
    def __init__(self, cache_dir: str | Path | None = None) -> None:
        self._memory: dict[str, LLMResponse] = {}
        self._cache_dir = Path(cache_dir) if cache_dir else None
        if self._cache_dir:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _make_key(self, provider: str, model: str, request: LLMRequest) -> str:
        payload = {
            "provider": provider,
            "provider_model": model,
            "request_model": request.model,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "prompt_name": request.prompt_name,
            "prompt_version": request.prompt_version,
            "system_prompt": request.system_prompt,
            "user_prompt": request.user_prompt,
            "metadata": request.metadata,
        }
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, provider: str, model: str, request: LLMRequest) -> Optional[LLMResponse]:
        key = self._make_key(provider, model, request)
        if key in self._memory:
            resp = self._memory[key]
            resp.cached = True
            return resp
        if self._cache_dir:
            path = self._cache_dir / f"{key}.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                resp = LLMResponse.model_validate(data)
                resp.cached = True
                self._memory[key] = resp
                return resp
        return None

    def set(self, provider: str, model: str, request: LLMRequest, response: LLMResponse) -> None:
        key = self._make_key(provider, model, request)
        resp_copy = response.model_copy()
        resp_copy.cached = False
        self._memory[key] = resp_copy
        if self._cache_dir:
            path = self._cache_dir / f"{key}.json"
            path.write_text(
                json.dumps(resp_copy.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def clear(self) -> None:
        self._memory.clear()


class DeepSeekProvider(LLMProvider):
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 model: Optional[str] = None, max_retries: int = 2) -> None:
        import os
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = base_url or os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self._model = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        self.input_cost_per_m = float(os.environ.get("DEEPSEEK_INPUT_COST_PER_M", "0"))
        self.output_cost_per_m = float(os.environ.get("DEEPSEEK_OUTPUT_COST_PER_M", "0"))
        self.max_retries = max_retries
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY not set")

    @property
    def provider_name(self) -> str:
        return "deepseek"

    @property
    def model_name(self) -> str:
        return self._model

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_cost_per_m / 1_000_000
            + output_tokens * self.output_cost_per_m / 1_000_000
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        from openai import OpenAI
        start = time.monotonic()
        last_error: Optional[str] = None
        retry_count = 0
        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.user_prompt})
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        for attempt in range(1, self.max_retries + 2):
            try:
                resp = client.chat.completions.create(
                    model=request.model or self._model,
                    messages=messages,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                choice = resp.choices[0]
                content = choice.message.content or ""
                usage = resp.usage
                llm_resp = LLMResponse(
                    content=content, model=resp.model,
                    input_tokens=usage.prompt_tokens,
                    output_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                    duration_ms=duration_ms, retry_count=retry_count,
                    raw_response={
                        "model": resp.model,
                        "finish_reason": choice.finish_reason,
                        "usage": {"prompt_tokens": usage.prompt_tokens,
                                  "completion_tokens": usage.completion_tokens,
                                  "total_tokens": usage.total_tokens},
                    },
                )
                return llm_resp
            except Exception as e:
                last_error = str(e)
                retry_count += 1
                if attempt <= self.max_retries:
                    time.sleep(2 ** attempt)
        duration_ms = int((time.monotonic() - start) * 1000)
        return LLMResponse(content="", model=self._model, duration_ms=duration_ms,
                           retry_count=retry_count, error=last_error)


class CachedProvider(LLMProvider):
    def __init__(self, inner: LLMProvider, cache: LLMCache) -> None:
        self._inner = inner
        self._cache = cache

    @property
    def provider_name(self) -> str:
        return self._inner.provider_name

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return self._inner.estimate_cost(input_tokens, output_tokens)

    def complete(self, request: LLMRequest) -> LLMResponse:
        cached = self._cache.get(self.provider_name, self.model_name, request)
        if cached:
            return cached
        response = self._inner.complete(request)
        if not response.error:
            self._cache.set(self.provider_name, self.model_name, request, response)
        return response


class CallLogger:
    def __init__(
        self,
        log_dir: str | Path,
        *,
        include_content: bool = False,
        input_cost_per_m: float = 0.0,
        output_cost_per_m: float = 0.0,
    ) -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._log_dir / "llm_calls.jsonl"
        self._records: list[LLMCallRecord] = []
        self._include_content = include_content
        self._input_cost_per_m = input_cost_per_m
        self._output_cost_per_m = output_cost_per_m

    def log(self, request: LLMRequest, response: LLMResponse) -> None:
        prompt_hash = hashlib.sha256(request.user_prompt.encode("utf-8")).hexdigest()[:16]
        input_hash = hashlib.sha256(
            f"{request.system_prompt}{request.user_prompt}".encode("utf-8")
        ).hexdigest()[:16]
        cost = 0.0
        if response.total_tokens > 0:
            cost = (
                response.input_tokens * self._input_cost_per_m / 1_000_000
                + response.output_tokens * self._output_cost_per_m / 1_000_000
            )

        logged_request = request
        logged_response = response
        if not self._include_content:
            logged_request = request.model_copy(
                update={
                    "system_prompt": (
                        f"[REDACTED sha256:{hashlib.sha256(request.system_prompt.encode('utf-8')).hexdigest()}]"
                        if request.system_prompt
                        else ""
                    ),
                    "user_prompt": f"[REDACTED sha256:{hashlib.sha256(request.user_prompt.encode('utf-8')).hexdigest()}]",
                }
            )
            logged_response = response.model_copy(
                update={
                    "content": f"[REDACTED sha256:{hashlib.sha256(response.content.encode('utf-8')).hexdigest()}]",
                    "raw_response": None,
                }
            )
        record = LLMCallRecord(
            request=logged_request,
            response=logged_response,
            prompt_hash=prompt_hash, input_hash=input_hash,
            estimated_cost_usd=round(cost, 6),
        )
        self._records.append(record)
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json(exclude_none=True) + "\n")

    def summary(self) -> dict[str, Any]:
        if not self._records:
            return {"calls": 0, "total_tokens": 0, "total_cost": 0.0}
        return {
            "calls": len(self._records),
            "total_input_tokens": sum(r.response.input_tokens for r in self._records),
            "total_output_tokens": sum(r.response.output_tokens for r in self._records),
            "total_tokens": sum(r.response.total_tokens for r in self._records),
            "total_cost_usd": round(sum(r.estimated_cost_usd for r in self._records), 6),
            "cached_calls": sum(1 for r in self._records if r.response.cached),
            "errors": sum(1 for r in self._records if r.response.error),
        }
