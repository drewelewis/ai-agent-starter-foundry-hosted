"""Offline tests for model configuration, agent construction, and real tool invocation."""

import asyncio
import json
from unittest.mock import MagicMock

import httpx
import pytest
from agent_framework.openai import OpenAIChatClient
from openai import AsyncOpenAI

from agents import tutor_agent
from tools.catalog import MATH_TOOLS


@pytest.fixture(autouse=True)
def isolate_model_configuration(monkeypatch):
    for name in tutor_agent.MODEL_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_factory_registers_all_tools(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("MODEL_DEPLOYMENT_NAME", "test-deployment")
    client_factory = MagicMock()
    agent_factory = MagicMock()
    monkeypatch.setattr(tutor_agent, "OpenAIChatClient", client_factory)
    monkeypatch.setattr(tutor_agent, "DefaultAzureCredential", MagicMock())
    monkeypatch.setattr(tutor_agent, "Agent", agent_factory)
    asyncio.run(tutor_agent.create_tutor_agent())
    registered = agent_factory.call_args.kwargs["tools"]
    assert {tool.name for tool in registered} == {tool.__name__ for tool in MATH_TOOLS}
    assert client_factory.call_args.kwargs["model"] == "test-deployment"
    assert agent_factory.call_args.kwargs["default_options"] == {"store": False}


def test_real_agent_construction_without_network(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("MODEL_DEPLOYMENT_NAME", "test-deployment")
    agent = asyncio.run(tutor_agent.create_tutor_agent())
    assert agent.name == "MathTutorAgent"


def test_partial_configuration_rejected(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_ENDPOINT", "https://example.openai.azure.com/")
    with pytest.raises(ValueError, match="MODEL_DEPLOYMENT_NAME"):
        asyncio.run(tutor_agent.create_tutor_agent())


def test_canonical_model_configuration(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "canonical-deployment")
    client_factory = MagicMock()
    monkeypatch.setattr(tutor_agent, "OpenAIChatClient", client_factory)
    monkeypatch.setattr(tutor_agent, "DefaultAzureCredential", MagicMock())
    monkeypatch.setattr(tutor_agent, "Agent", MagicMock())
    asyncio.run(tutor_agent.create_tutor_agent())
    assert client_factory.call_args.kwargs["azure_endpoint"] == "https://example.openai.azure.com/"
    assert client_factory.call_args.kwargs["model"] == "canonical-deployment"


def test_canonical_settings_take_precedence(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://canonical.openai.azure.com/")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "canonical-deployment")
    monkeypatch.setenv("AZURE_OPENAI_API_ENDPOINT", "https://legacy.openai.azure.com/")
    monkeypatch.setenv("MODEL_DEPLOYMENT_NAME", "legacy-deployment")
    client_factory = MagicMock()
    monkeypatch.setattr(tutor_agent, "OpenAIChatClient", client_factory)
    monkeypatch.setattr(tutor_agent, "DefaultAzureCredential", MagicMock())
    monkeypatch.setattr(tutor_agent, "Agent", MagicMock())
    asyncio.run(tutor_agent.create_tutor_agent())
    assert client_factory.call_args.kwargs["azure_endpoint"] == "https://canonical.openai.azure.com/"
    assert client_factory.call_args.kwargs["model"] == "canonical-deployment"


def test_real_agent_invokes_geometry_tool_offline(monkeypatch):
    requests = []

    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            output = [{
                "type": "function_call",
                "id": "fc_offline",
                "call_id": "call_offline",
                "name": "rectangle_area",
                "arguments": '{"length": 3, "width": 4}',
                "status": "completed",
            }]
        else:
            output = [{
                "type": "message",
                "id": "msg_offline",
                "status": "completed",
                "role": "assistant",
                "content": [{
                    "type": "output_text", "text": "The area is 12 square units.",
                    "annotations": [],
                }],
            }]
        return httpx.Response(200, json={
            "id": f"resp_offline_{len(requests)}", "object": "response",
            "created_at": 1, "status": "completed", "model": "offline-test",
            "output": output, "parallel_tool_calls": False,
            "tool_choice": "auto", "tools": [],
        })

    async def run():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        openai_client = AsyncOpenAI(api_key="offline", http_client=http_client)
        client = OpenAIChatClient(model="offline-test", async_client=openai_client)
        monkeypatch.setattr(tutor_agent, "OpenAIChatClient", lambda **kwargs: client)
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
        monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "offline-test")
        async with openai_client:
            async with await tutor_agent.create_tutor_agent() as agent:
                return await agent.run("Find rectangle area for length 3 and width 4.")

    result = asyncio.run(run())
    assert result.text == "The area is 12 square units."
    assert len(requests) == 2
    assert requests[0]["store"] is False
    outputs = [item for item in requests[1]["input"] if item.get("type") == "function_call_output"]
    assert len(outputs) == 1
    assert "12" in outputs[0]["output"]
