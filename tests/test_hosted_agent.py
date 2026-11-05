"""Exercise the actual Foundry Responses 2.0 host without model calls."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from agent_framework import Agent, AgentResponse, AgentResponseUpdate, Content, ResponseStream
from agent_framework_foundry_hosting import ResponsesHostServer
from starlette.testclient import TestClient

import main as hosted_main
import chat
from agents.tutor_agent import MODEL_ENVIRONMENT_VARIABLES


@pytest.fixture(autouse=True)
def isolate_swagger_setting(monkeypatch):
    monkeypatch.delenv("ENABLE_SWAGGER", raising=False)
    monkeypatch.delenv("ENABLE_LOCAL_DIAGNOSTICS", raising=False)


@pytest.fixture
def hosted_client(monkeypatch, tmp_path):
    for name in MODEL_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "offline-test")
    monkeypatch.setenv("AGENTSERVER_STATE_ROOT", str(tmp_path))
    server = ResponsesHostServer(
        agent=hosted_main.create_tutor_agent,
        configure_observability=None,
    )
    with TestClient(server) as client:
        yield client


@pytest.fixture
def swagger_client(hosted_client):
    hosted_main.add_swagger_routes(hosted_client.app)
    return hosted_client


@pytest.fixture
def offline_agent(monkeypatch):
    state = SimpleNamespace(calls=[], text="The area is 12 square units.")

    def run(self, messages=None, *, stream=False, **kwargs):
        state.calls.append((messages, kwargs))

        async def updates():
            yield AgentResponseUpdate(
                role="assistant", contents=[Content.from_text(state.text)],
                message_id="offline-message",
            )

        if stream:
            return ResponseStream(updates(), finalizer=AgentResponse.from_updates)

        async def response():
            return AgentResponse.from_updates([update async for update in updates()])

        return response()

    monkeypatch.setattr(Agent, "run", run)
    return state


def test_hosted_readiness(hosted_client):
    assert hosted_client.get("/readiness").status_code == 200


@pytest.mark.parametrize("path", ["/chat", "/calculate", "/clear_session"])
def test_no_custom_rest_actions(hosted_client, path):
    assert hosted_client.post(path, json={}).status_code == 404


@pytest.mark.parametrize("path", ["/docs", "/openapi.json", "/health", "/agent/status"])
def test_no_custom_rest_discovery(hosted_client, path):
    assert hosted_client.get(path).status_code == 404


def test_swagger_documents_only_existing_hosted_routes(swagger_client, offline_agent):
    docs = swagger_client.get("/docs")
    assert docs.status_code == 200
    assert docs.headers["content-type"].startswith("text/html")
    assert 'url: "/openapi.json"' in docs.text
    assert "swagger-ui-dist@5.34.1" in docs.text
    assert "validatorUrl: null" in docs.text
    schema = swagger_client.get("/openapi.json").json()
    assert schema["openapi"] == "3.0.3"
    assert schema["servers"] == [{"url": "/"}]
    assert set(schema["paths"]) == {
        "/readiness", "/responses", "/responses/{response_id}",
        "/responses/{response_id}/cancel", "/responses/{response_id}/input_items",
    }
    for path, operations in schema["paths"].items():
        actual_methods = {
            method.lower()
            for route in swagger_client.app.routes
            if route.path == path
            for method in route.methods
        }
        assert set(operations) <= actual_methods
    assert not offline_agent.calls
    assert swagger_client.get("/readiness").status_code == 200
    assert swagger_client.post("/chat", json={}).status_code == 404


def test_swagger_example_invokes_the_existing_hosted_agent(swagger_client, offline_agent):
    schema = swagger_client.get("/openapi.json").json()
    operation = schema["paths"]["/responses"]["post"]
    example = operation["requestBody"]["content"]["application/json"]["example"]
    response = swagger_client.post("/responses", json=example)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["output"][0]["content"][0]["text"] == offline_agent.text
    assert len(offline_agent.calls) == 1
    stored = swagger_client.get(f"/responses/{data['id']}")
    assert stored.status_code == 200
    assert stored.json()["id"] == data["id"]


def test_non_streaming_responses(hosted_client, offline_agent):
    response = hosted_client.post(
        "/responses",
        json={"input": "Find the area of a 3 by 4 rectangle.", "stream": False},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "response"
    assert data["id"]
    assert data["status"] == "completed"
    message = data["output"][0]
    assert message["type"] == "message"
    assert message["role"] == "assistant"
    assert message["content"][0]["type"] == "output_text"
    assert message["content"][0]["text"] == offline_agent.text
    assert len(offline_agent.calls) == 1


def test_streaming_responses(hosted_client, offline_agent):
    response = hosted_client.post(
        "/responses", json={"input": "Find rectangle area.", "stream": True},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [
        json.loads(line.removeprefix("data:").strip())
        for line in response.text.splitlines()
        if line.startswith("data:") and line.removeprefix("data:").strip() != "[DONE]"
    ]
    types = [event["type"] for event in events]
    assert "response.created" in types
    assert "response.output_text.delta" in types
    assert types[-1] == "response.completed"
    text = "".join(
        event["delta"] for event in events if event["type"] == "response.output_text.delta"
    )
    assert text == offline_agent.text


def test_platform_supplied_history(hosted_client, offline_agent):
    response = hosted_client.post("/responses", json={
        "input": [
            {"type": "message", "role": "user", "content": "My radius is 5."},
            {"type": "message", "role": "assistant", "content": "I will use radius 5."},
            {"type": "message", "role": "user", "content": "What radius did I give?"},
        ],
        "stream": False,
    })
    assert response.json()["status"] == "completed"
    messages = offline_agent.calls[0][0]
    assert len(messages) == 3
    assert messages[0].text == "My radius is 5."
    assert messages[2].text == "What radius did I give?"
    assert offline_agent.calls[0][1]["session"] is not None


def test_response_retrieval_and_continuation(hosted_client, offline_agent):
    first = hosted_client.post(
        "/responses", json={"input": "My radius is 5.", "store": True},
    ).json()
    assert first["status"] == "completed"
    stored = hosted_client.get(f"/responses/{first['id']}")
    assert stored.status_code == 200
    assert stored.json()["id"] == first["id"]
    second = hosted_client.post("/responses", json={
        "input": "What radius did I give?",
        "previous_response_id": first["id"],
        "store": True,
    })
    assert second.json()["status"] == "completed"
    messages = offline_agent.calls[-1][0]
    assert any("My radius is 5." in message.text for message in messages)
    assert any("What radius did I give?" in message.text for message in messages)


def test_chat_client_uses_hosted_server_history_and_clear(
    hosted_client, offline_agent, monkeypatch, capsys,
):
    messages = iter([
        "My radius is 5.", "What radius did I give?", "clear",
        "Find rectangle area.", "status", "help", "quit",
    ])
    monkeypatch.setattr("builtins.input", lambda _: next(messages))
    chat.run_chat(hosted_client)
    assert len(offline_agent.calls) == 3
    continued_messages = offline_agent.calls[1][0]
    assert any("My radius is 5." in message.text for message in continued_messages)
    new_messages = offline_agent.calls[2][0]
    assert not any("My radius is 5." in message.text for message in new_messages)
    output = capsys.readouterr().out
    assert output.count(f"Tutor: {offline_agent.text}") == 3
    assert "Started a new conversation" in output
    assert "server is ready" in output


def test_invalid_json(hosted_client):
    response = hosted_client.post(
        "/responses", content="{", headers={"Content-Type": "application/json"},
    )
    assert response.status_code in (400, 422)


def test_hosted_startup_requires_model_settings(monkeypatch):
    for name in MODEL_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(hosted_main, "load_dotenv", lambda **kwargs: None)
    with pytest.raises(ValueError, match="Missing required environment variables"):
        asyncio.run(hosted_main.main())


def test_hosted_entrypoint_uses_configured_port(monkeypatch):
    server = SimpleNamespace(run_async=AsyncMock())
    factory = MagicMock(return_value=server)
    monkeypatch.setattr(hosted_main, "ResponsesHostServer", factory)
    monkeypatch.setattr(hosted_main, "load_dotenv", lambda **kwargs: None)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "offline-test")
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setenv("DEFAULT_AD_PORT", "8090")
    asyncio.run(hosted_main.main())
    factory.assert_called_once_with(agent=hosted_main.create_tutor_agent)
    server.run_async.assert_awaited_once_with(port=8090)


def test_platform_port_takes_precedence(monkeypatch):
    server = SimpleNamespace(run_async=AsyncMock())
    monkeypatch.setattr(hosted_main, "ResponsesHostServer", lambda **kwargs: server)
    monkeypatch.setattr(hosted_main, "load_dotenv", lambda **kwargs: None)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "offline-test")
    monkeypatch.setenv("PORT", "8088")
    monkeypatch.setenv("DEFAULT_AD_PORT", "8090")
    asyncio.run(hosted_main.main())
    server.run_async.assert_awaited_once_with(port=8088)


@pytest.mark.parametrize(("setting", "enabled"), [
    (None, False), ("false", False), ("true", True), (" TRUE ", True),
])
def test_swagger_startup_setting(monkeypatch, setting, enabled):
    if setting is not None:
        monkeypatch.setenv("ENABLE_SWAGGER", setting)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "offline-test")
    monkeypatch.setattr(hosted_main, "load_dotenv", lambda **kwargs: None)
    server = SimpleNamespace(run_async=AsyncMock())
    monkeypatch.setattr(hosted_main, "ResponsesHostServer", lambda **kwargs: server)
    add_docs = MagicMock()
    monkeypatch.setattr(hosted_main, "add_swagger_routes", add_docs)
    asyncio.run(hosted_main.main())
    if enabled:
        add_docs.assert_called_once_with(server)
    else:
        add_docs.assert_not_called()
    server.run_async.assert_awaited_once()


@pytest.mark.parametrize("setting", ["", "yes", "1", "invalid"])
def test_invalid_swagger_setting_is_a_startup_error(monkeypatch, setting):
    monkeypatch.setenv("ENABLE_SWAGGER", setting)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "offline-test")
    monkeypatch.setattr(hosted_main, "load_dotenv", lambda **kwargs: None)
    with pytest.raises(ValueError, match="ENABLE_SWAGGER must be true or false"):
        asyncio.run(hosted_main.main())
