"""The OpenAI-compatible API backend: wire format, fallback, loud failures."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest
from pydantic import ValidationError

from smbr.agent import build_completion_client
from smbr.config import Settings
from smbr.model.openai_client import DEFAULT_BASE_URL, OpenAICompletionClient

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "boolean"}, "confidence": {"type": "number"}},
    "required": ["answer", "confidence"],
}

ANSWER = {"answer": True, "confidence": 0.9}


class _FakeResponse:
    """Minimal context-manager stand-in for the urlopen result."""

    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _chat_body(content: str) -> str:
    return json.dumps({"choices": [{"message": {"content": content}}]})


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.example.com/v1/chat/completions", code, "error", {}, None
    )


def _patch_urlopen(monkeypatch, outcomes: list) -> list[urllib.request.Request]:
    """Serve scripted outcomes (body strings or exceptions) and record requests."""
    recorded: list[urllib.request.Request] = []

    def urlopen(request, timeout=None):
        recorded.append(request)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResponse(outcome)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return recorded


def _payload_of(request: urllib.request.Request) -> dict:
    return json.loads(request.data.decode("utf-8"))


def test_backend_selected_from_settings(tmp_path) -> None:
    settings = Settings(
        project_root=tmp_path,
        model_backend="openai",
        model="qwen/qwen3-coder",
        api_key="test-key",
    )
    client = build_completion_client(settings)
    assert isinstance(client, OpenAICompletionClient)
    assert client.model == "qwen/qwen3-coder"
    assert client.api_key == "test-key"
    assert client.base_url == DEFAULT_BASE_URL


def test_request_shape(monkeypatch) -> None:
    recorded = _patch_urlopen(monkeypatch, [_chat_body(json.dumps(ANSWER))])
    client = OpenAICompletionClient(model="m", api_key="k", base_url="https://api.x.com/v1")

    data = client.complete_json("is this ok?", SCHEMA)

    assert data == ANSWER
    request = recorded[0]
    assert request.full_url == "https://api.x.com/v1/chat/completions"
    assert request.get_method() == "POST"
    assert request.headers["Authorization"] == "Bearer k"
    payload = _payload_of(request)
    assert payload["model"] == "m"
    assert payload["temperature"] == 0
    assert payload["messages"] == [{"role": "user", "content": "is this ok?"}]
    assert payload["response_format"]["json_schema"]["schema"] == SCHEMA
    # strict is what makes providers with a native strict mode enforce the
    # schema exactly, per OpenRouter's structured-outputs best practice
    assert payload["response_format"]["json_schema"]["strict"] is True


def test_non_object_answer_raises(monkeypatch) -> None:
    _patch_urlopen(monkeypatch, [_chat_body("[1, 2]")])
    client = OpenAICompletionClient(model="m", api_key="k")
    with pytest.raises(TypeError):
        client.complete_json("q", SCHEMA)


def test_empty_answer_raises_a_readable_error(monkeypatch) -> None:
    # documented provider failure: reasoning burns the token budget,
    # the response is a 200 with an empty message content
    _patch_urlopen(monkeypatch, [_chat_body(None)])
    client = OpenAICompletionClient(model="m", api_key="k")
    with pytest.raises(RuntimeError, match="empty answer"):
        client.complete_json("q", SCHEMA)


def test_response_without_choices_raises_a_readable_error(monkeypatch) -> None:
    _patch_urlopen(monkeypatch, [json.dumps({"error": {"message": "warming up"}})])
    client = OpenAICompletionClient(model="m", api_key="k")
    with pytest.raises(RuntimeError, match="warming up"):
        client.complete_json("q", SCHEMA)


def test_falls_back_to_json_object_when_schema_rejected(monkeypatch) -> None:
    recorded = _patch_urlopen(monkeypatch, [_http_error(400), _chat_body(json.dumps(ANSWER))])
    client = OpenAICompletionClient(model="m", api_key="k")

    data = client.complete_json("q", SCHEMA)

    assert data == ANSWER
    retry = _payload_of(recorded[1])
    assert retry["response_format"] == {"type": "json_object"}
    assert json.dumps(SCHEMA) in retry["messages"][0]["content"]


def test_auth_failure_raises_without_retry(monkeypatch) -> None:
    recorded = _patch_urlopen(monkeypatch, [_http_error(401)])
    client = OpenAICompletionClient(model="m", api_key="bad")

    with pytest.raises(urllib.error.HTTPError):
        client.complete_json("q", SCHEMA)
    assert len(recorded) == 1


def test_missing_api_key_fails_loudly(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SMBR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = Settings(project_root=tmp_path, model_backend="openai")
    with pytest.raises(ValueError, match="SMBR_API_KEY"):
        build_completion_client(settings)


def test_env_configures_the_api_backend(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SMBR_MODEL_BACKEND", "openai")
    monkeypatch.setenv("SMBR_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setenv("SMBR_API_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("SMBR_API_KEY", "groq-key")

    client = build_completion_client(Settings(project_root=tmp_path))

    assert isinstance(client, OpenAICompletionClient)
    assert client.model == "llama-3.3-70b-versatile"
    assert client.base_url == "https://api.groq.com/openai/v1"
    assert client.api_key == "groq-key"


def test_openai_api_key_env_is_a_fallback(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SMBR_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fallback")
    assert Settings(project_root=tmp_path).api_key == "sk-fallback"


def test_unknown_backend_rejected(tmp_path) -> None:
    with pytest.raises(ValidationError, match="unknown model_backend"):
        Settings(project_root=tmp_path, model_backend="gpt-4o-mini")
