"""Opt-in exception metadata written to stderr without telemetry export."""

import json
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from pathlib import Path

from agent_framework import AgentContext, AgentMiddleware, AgentResponse, AgentResponseUpdate, ResponseStream
from opentelemetry.trace import get_current_span


_PROVIDER_CODES = frozenset({
    "content_filter", "context_length_exceeded", "invalid_request_error",
    "invalid_value", "invalid_api_key", "insufficient_quota", "model_not_found",
    "rate_limit_exceeded", "server_error", "permission_denied",
    "authentication_error", "unsupported_parameter", "unsupported_value",
})


def local_diagnostics_enabled() -> bool:
    value = os.getenv("ENABLE_LOCAL_DIAGNOSTICS", "false").strip().lower()
    if value not in ("true", "false"):
        raise ValueError("ENABLE_LOCAL_DIAGNOSTICS must be true or false.")
    return value == "true"


def _write_failure(error: Exception) -> None:
    chain: list[dict[str, object]] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        frames: list[dict[str, object]] = []
        traceback = current.__traceback__
        while traceback is not None:
            code = traceback.tb_frame.f_code
            frames.append({
                "file": Path(code.co_filename).name,
                "function": code.co_name,
                "line": traceback.tb_lineno,
            })
            traceback = traceback.tb_next
        entry: dict[str, object] = {
            "type": type(current).__name__,
            "module": type(current).__module__,
            "frames": frames[-12:],
        }
        status = getattr(current, "status_code", None)
        if type(status) is int and 100 <= status <= 599:
            entry["status_code"] = status
        provider_code = getattr(current, "code", None)
        if isinstance(provider_code, str) and provider_code in _PROVIDER_CODES:
            entry["provider_code"] = provider_code
        chain.append(entry)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    span = get_current_span().get_span_context()
    record = {
        "event": "local_agent_failure",
        "trace_id": f"{span.trace_id:032x}" if span.is_valid else None,
        "exceptions": chain,
    }
    # Bypass logging handlers so this diagnostic is not exported by telemetry.
    sys.stderr.write(json.dumps(record) + "\n")
    sys.stderr.flush()


class LocalDiagnosticsMiddleware(AgentMiddleware):
    """Observe failures while preserving results, streaming, and raised exceptions."""

    async def process(
        self, context: AgentContext, call_next: Callable[[], Awaitable[None]],
    ) -> None:
        try:
            await call_next()
        except Exception as error:
            _write_failure(error)
            raise

        if isinstance(context.result, ResponseStream):
            source = context.result

            async def updates() -> AsyncIterator[AgentResponseUpdate]:
                try:
                    async with source:
                        async for update in source:
                            yield update
                except Exception as error:
                    _write_failure(error)
                    raise

            async def final_response(
                _: Sequence[AgentResponseUpdate],
            ) -> AgentResponse:
                try:
                    return await source.get_final_response()
                except Exception as error:
                    _write_failure(error)
                    raise

            context.result = ResponseStream(updates(), finalizer=final_response)
