"""Offline tests for the HTTP-only local Responses client."""

import json
from unittest.mock import MagicMock

import httpx
import pytest

import chat


def completed_response(response_id="response-1", text="The answer is 12."):
    return {
        "id": response_id,
        "status": "completed",
        "output": [{
            "type": "message",
            "content": [{"type": "output_text", "text": text}],
        }],
    }


def test_response_text_ignores_tool_output_and_joins_messages():
    data = completed_response()
    data["output"].insert(0, {"type": "function_call", "name": "multiply"})
    data["output"].append({
        "type": "message",
        "content": [{"type": "output_text", "text": "Try another example."}],
    })
    assert chat.response_message(data) == (
        "response-1", "The answer is 12.\nTry another example.",
    )


@pytest.mark.parametrize("data", [
    [],
    {"status": "failed", "error": {"message": "Model unavailable"}},
    {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
    {"status": "completed", "output": []},
    {"id": "r", "status": "completed", "output": []},
    {"id": "r", "status": "completed", "output": [{"type": "message"}]},
    {"id": "r", "status": "completed", "output": [{
        "type": "message", "content": [None],
    }]},
    {"id": "r", "status": "completed", "output": [{
        "type": "message", "content": [{"type": "output_text", "text": 12}],
    }]},
    completed_response(text=" "),
])
def test_invalid_responses_are_reported(data):
    with pytest.raises(ValueError):
        chat.response_message(data)


def test_refusal_is_explicit():
    data = completed_response()
    data["output"][0]["content"] = [{"type": "refusal", "refusal": "Cannot help."}]
    with pytest.raises(ValueError, match="Tutor refused.*Cannot help"):
        chat.response_message(data)


@pytest.mark.parametrize("failure", ["http", "timeout", "json", "incomplete"])
def test_request_failure_keeps_previous_successful_response(monkeypatch, capsys, failure):
    requests = []
    messages = iter(["First question", "Failed question", "Retry", "quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(messages))

    def handle(request):
        requests.append(json.loads(request.content))
        if len(requests) == 2:
            if failure == "http":
                return httpx.Response(502, json={"error": "Model unavailable"})
            if failure == "timeout":
                raise httpx.ReadTimeout("Server timed out", request=request)
            if failure == "json":
                return httpx.Response(200, text="not JSON")
            return httpx.Response(200, json={"status": "incomplete"})
        return httpx.Response(200, json=completed_response(f"response-{len(requests)}"))

    with httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(handle)) as client:
        chat.run_chat(client)
    assert requests == [
        {"input": "First question", "stream": False, "store": True},
        {"input": "Failed question", "stream": False, "store": True,
         "previous_response_id": "response-1"},
        {"input": "Retry", "stream": False, "store": True,
         "previous_response_id": "response-1"},
    ]
    assert "Tutor request failed:" in capsys.readouterr().out


@pytest.mark.parametrize(("port", "default_port", "arguments", "expected"), [
    (None, None, [], "http://127.0.0.1:8088"),
    (None, "8090", [], "http://127.0.0.1:8090"),
    ("8091", "8090", [], "http://127.0.0.1:8091"),
    ("8091", "8090", ["--url", "http://localhost:9000"], "http://localhost:9000"),
])
def test_client_url_and_readiness(monkeypatch, port, default_port, arguments, expected):
    monkeypatch.setattr(chat, "load_dotenv", lambda **kwargs: None)
    for name, value in (("PORT", port), ("DEFAULT_AD_PORT", default_port)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    monkeypatch.setattr("sys.argv", ["chat.py", *arguments])
    monkeypatch.setattr("builtins.input", lambda _: "quit")
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200)

    client = httpx.Client(base_url=expected, transport=httpx.MockTransport(handle))
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(chat.httpx, "Client", factory)
    assert chat.main() == 0
    factory.assert_called_once_with(base_url=expected, timeout=180)
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/readiness"


def test_server_not_running_returns_actionable_error(monkeypatch, capsys):
    monkeypatch.setattr(chat, "load_dotenv", lambda **kwargs: None)
    monkeypatch.setattr("sys.argv", ["chat.py"])

    def handle(request):
        raise httpx.ConnectError("Connection refused", request=request)

    client = httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(handle))
    monkeypatch.setattr(chat.httpx, "Client", lambda **kwargs: client)
    assert chat.main() == 1
    output = capsys.readouterr().out
    assert "Connection refused" in output
    assert "python main.py" in output


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_input_can_exit_cleanly(monkeypatch, capsys, error):
    def stop(_):
        raise error()

    monkeypatch.setattr("builtins.input", stop)
    with httpx.Client(base_url="http://testserver") as client:
        chat.run_chat(client)
    assert "Goodbye!" in capsys.readouterr().out
