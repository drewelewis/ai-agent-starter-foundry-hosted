"""Offline tests for privacy-preserving local failure diagnostics."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from agent_framework import AgentContext, AgentResponse, AgentResponseUpdate, Content, ResponseStream
from agent_framework.exceptions import ChatClientException
from agent_framework.openai import OpenAIChatClient
from openai import AsyncOpenAI

import main as hosted_main
from agents import tutor_agent
from agents.diagnostics import LocalDiagnosticsMiddleware, _write_failure, local_diagnostics_enabled


@pytest.mark.parametrize(("setting", "enabled"), [
    (None, False), ("false", False), ("true", True), (" TRUE ", True),
])
def test_diagnostic_setting(monkeypatch, setting, enabled):
    monkeypatch.delenv("ENABLE_LOCAL_DIAGNOSTICS", raising=False)
    if setting is not None:
        monkeypatch.setenv("ENABLE_LOCAL_DIAGNOSTICS", setting)
    assert local_diagnostics_enabled() is enabled


@pytest.mark.parametrize("setting", ["", "yes", "1", "invalid"])
def test_invalid_diagnostic_setting(monkeypatch, setting):
    monkeypatch.setenv("ENABLE_LOCAL_DIAGNOSTICS", setting)
    with pytest.raises(ValueError, match="ENABLE_LOCAL_DIAGNOSTICS must be true or false"):
        local_diagnostics_enabled()


def test_metadata_excludes_messages_bodies_and_unknown_codes(capsys):
    secret = "secret-message-token-and-prompt"
    inner = ValueError(secret)
    inner.status_code = 400
    inner.code = "invalid_request_error"
    inner.body = {"prompt": secret}
    outer = ChatClientException(secret, log_level=None)
    outer.code = secret
    try:
        try:
            raise inner
        except ValueError as error:
            raise outer from error
    except ChatClientException as error:
        _write_failure(error)
    output = capsys.readouterr().err
    assert secret not in output
    record = json.loads(output)
    assert record["event"] == "local_agent_failure"
    assert [entry["type"] for entry in record["exceptions"]] == [
        "ChatClientException", "ValueError",
    ]
    assert "provider_code" not in record["exceptions"][0]
    assert record["exceptions"][1]["provider_code"] == "invalid_request_error"
    assert record["exceptions"][1]["status_code"] == 400
    for entry in record["exceptions"]:
        assert entry["frames"]
        assert all(frame["file"] == "test_diagnostics.py" for frame in entry["frames"])
        assert all(set(frame) == {"file", "function", "line"} for frame in entry["frames"])


def test_cyclic_exception_chain_is_bounded(capsys):
    error = ValueError("not logged")
    error.__cause__ = error
    _write_failure(error)
    assert len(json.loads(capsys.readouterr().err)["exceptions"]) == 1


def test_invalid_setting_fails_at_startup(monkeypatch):
    monkeypatch.setenv("ENABLE_LOCAL_DIAGNOSTICS", "invalid")
    monkeypatch.setattr(hosted_main, "load_dotenv", lambda **kwargs: None)
    with pytest.raises(ValueError, match="ENABLE_LOCAL_DIAGNOSTICS must be true or false"):
        asyncio.run(hosted_main.main())


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_real_agent_failure_diagnostics_are_opt_in(monkeypatch, capsys, stream, enabled):
    secret = "private-provider-message"

    def handle(request):
        return httpx.Response(400, json={
            "error": {"message": secret, "code": "invalid_request_error",
                      "type": "invalid_request_error"},
        })

    async def run():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        async with AsyncOpenAI(api_key="offline", http_client=http_client, max_retries=0) as api:
            client = OpenAIChatClient(model="offline-test", async_client=api)
            monkeypatch.setattr(tutor_agent, "OpenAIChatClient", lambda **kwargs: client)
            monkeypatch.setenv("ENABLE_LOCAL_DIAGNOSTICS", str(enabled).lower())
            monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
            monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "offline-test")
            async with await tutor_agent.create_tutor_agent() as agent:
                if stream:
                    async for _ in agent.run("private student prompt", stream=True):
                        pass
                else:
                    await agent.run("private student prompt")

    with pytest.raises(ChatClientException):
        asyncio.run(run())
    output = capsys.readouterr().err
    assert secret not in output
    assert "private student prompt" not in output
    if enabled:
        records = [json.loads(line) for line in output.splitlines()]
        assert len(records) == 1
        assert records[0]["exceptions"][-1]["type"] == "BadRequestError"
        assert records[0]["exceptions"][-1]["status_code"] == 400
    else:
        assert "local_agent_failure" not in output


@pytest.mark.parametrize("stream", [False, True])
def test_middleware_preserves_successful_results(capsys, stream):
    expected = AgentResponse.from_updates([
        AgentResponseUpdate(role="assistant", contents=[Content.from_text("2")]),
    ])

    async def run():
        context = AgentContext(agent=SimpleNamespace(), messages=[], stream=stream)

        async def next_handler():
            if stream:
                async def updates():
                    yield AgentResponseUpdate(
                        role="assistant", contents=[Content.from_text("2")],
                    )

                context.result = ResponseStream(updates(), finalizer=lambda _: expected)
            else:
                context.result = expected

        await LocalDiagnosticsMiddleware().process(context, next_handler)
        if stream:
            return await context.result.get_final_response()
        return context.result

    assert asyncio.run(run()) is expected
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("phase", ["invocation", "updates", "finalizer"])
def test_middleware_reraises_the_original_exception(capsys, phase):
    error = ValueError("private message")

    async def run():
        context = AgentContext(agent=SimpleNamespace(), messages=[], stream=True)

        async def next_handler():
            if phase == "invocation":
                raise error

            async def updates():
                yield AgentResponseUpdate(role="assistant", contents=[Content.from_text("2")])
                if phase == "updates":
                    raise error

            def finalize(_):
                raise error

            context.result = ResponseStream(updates(), finalizer=finalize)

        await LocalDiagnosticsMiddleware().process(context, next_handler)
        await context.result.get_final_response()

    with pytest.raises(ValueError) as caught:
        asyncio.run(run())
    assert caught.value is error
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert len(records) == 1
    assert records[0]["exceptions"][0]["type"] == "ValueError"
