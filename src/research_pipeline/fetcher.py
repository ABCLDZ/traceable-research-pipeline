"""HTTP 抓取模块。

支持普通 HTTP 请求和失败重试，动态页面作为后备方案。"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from research_pipeline.models import FetchRecord, FetchStatus
from research_pipeline.url_policy import validate_public_url


DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_MAX_RESPONSE_BYTES = 50 * 1024 * 1024
DEFAULT_USER_AGENT = (
    "TraceableResearchPipeline/0.1 "
    "(+https://github.com/ABCLDZ/traceable-research-pipeline)"
)


def fetch_url(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    user_agent: str = DEFAULT_USER_AGENT,
    follow_redirects: bool = True,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
) -> tuple[Optional[bytes], Optional[str], FetchRecord]:
    """抓取单个 URL，返回 (content_bytes, content_type, fetch_record)。

    自动重试失败的请求（不包括 4xx 客户端错误）。
    """
    start = time.monotonic()
    last_error: Optional[str] = None

    headers = {"User-Agent": user_agent}
    allowed, reason = validate_public_url(
        url,
        allowed_domains=allowed_domains,
        blocked_domains=blocked_domains,
    )
    if not allowed:
        return None, None, FetchRecord(
            error_message=f"url_policy: {reason}",
            user_agent=user_agent,
        )

    def guard_request(request: httpx.Request) -> None:
        request_allowed, request_reason = validate_public_url(
            str(request.url),
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
        )
        if not request_allowed:
            raise httpx.RequestError(
                f"redirect blocked by URL policy: {request_reason}",
                request=request,
            )

    for attempt in range(1, max_retries + 1):
        try:
            with httpx.Client(
                timeout=httpx.Timeout(timeout),
                follow_redirects=follow_redirects,
                event_hooks={"request": [guard_request]},
            ) as client:
                with client.stream("GET", url, headers=headers) as response:
                    duration_ms = int((time.monotonic() - start) * 1000)

                    if response.status_code == 200:
                        declared_size = response.headers.get("content-length")
                        try:
                            declared_bytes = int(declared_size) if declared_size else None
                        except ValueError:
                            declared_bytes = None
                        if (
                            declared_bytes is not None
                            and declared_bytes > max_response_bytes
                        ):
                            return None, None, FetchRecord(
                                http_status=200,
                                final_url=str(response.url),
                                fetched_at=datetime.now(timezone.utc),
                                fetch_duration_ms=duration_ms,
                                error_message="response exceeds configured byte limit",
                                user_agent=user_agent,
                            )

                        chunks: list[bytes] = []
                        received = 0
                        for chunk in response.iter_bytes():
                            received += len(chunk)
                            if received > max_response_bytes:
                                return None, None, FetchRecord(
                                    http_status=200,
                                    final_url=str(response.url),
                                    fetched_at=datetime.now(timezone.utc),
                                    fetch_duration_ms=duration_ms,
                                    error_message="response exceeds configured byte limit",
                                    user_agent=user_agent,
                                )
                            chunks.append(chunk)
                        content_type = response.headers.get("content-type")
                        record = FetchRecord(
                            http_status=200,
                            final_url=str(response.url),
                            fetched_at=datetime.now(timezone.utc),
                            fetch_duration_ms=duration_ms,
                            user_agent=user_agent,
                        )
                        return b"".join(chunks), content_type, record

                    # 4xx 不重试（客户端错误）
                    if 400 <= response.status_code < 500:
                        record = FetchRecord(
                            http_status=response.status_code,
                            final_url=str(response.url),
                            fetched_at=datetime.now(timezone.utc),
                            fetch_duration_ms=duration_ms,
                            error_message=f"HTTP {response.status_code}",
                            user_agent=user_agent,
                        )
                        return None, None, record

                    last_error = f"HTTP {response.status_code}"

        except httpx.TimeoutException as e:
            last_error = f"timeout: {e}"
        except httpx.RequestError as e:
            last_error = str(e)

        if attempt < max_retries:
            time.sleep(2 ** attempt)  # exponential backoff

    duration_ms = int((time.monotonic() - start) * 1000)
    record = FetchRecord(
        http_status=None,
        final_url=None,
        fetched_at=datetime.now(timezone.utc),
        fetch_duration_ms=duration_ms,
        error_message=last_error,
        user_agent=user_agent,
        used_browser=False,
    )
    return None, None, record
