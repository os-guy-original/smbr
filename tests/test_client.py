"""Model and decision-layer factories driven by Settings."""

from __future__ import annotations

from pathlib import Path

from smbr.agent import build_completion_client, build_decision_router
from smbr.config import Settings
from smbr.decisions.provider import ConstrainedJsonProvider, DisabledDecisionProvider
from smbr.model.llamacpp_client import LlamaCppCompletionClient
from smbr.model.ollama_client import OllamaCompletionClient


def test_default_backend_is_ollama(tmp_path) -> None:
    settings = Settings(project_root=tmp_path)
    client = build_completion_client(settings)
    assert isinstance(client, OllamaCompletionClient)
    assert client.model == "gemma4:e4b"  # real tag, verified in the Ollama library


def test_llamacpp_backend(tmp_path) -> None:
    settings = Settings(project_root=tmp_path, decision_provider="llamacpp")
    client = build_completion_client(settings)
    assert isinstance(client, LlamaCppCompletionClient)


def test_layer_off_means_disabled_provider(tmp_path) -> None:
    settings = Settings(project_root=tmp_path, decision_provider="off")
    router = build_decision_router(settings)
    assert isinstance(router.provider, DisabledDecisionProvider)
    # low confidence always routes to the user
    assert router.needs_user(router.boolean("anything"))


def test_layer_on_builds_constrained_provider(tmp_path) -> None:
    settings = Settings(project_root=tmp_path, model_host="http://localhost:11434")
    router = build_decision_router(settings, client=object())  # type: ignore[arg-type]
    assert isinstance(router.provider, ConstrainedJsonProvider)


def test_settings_env_prefix(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SMBR_MODEL", "qwen2.5-coder:7b")
    monkeypatch.setenv("SMBR_MAX_EDIT_ATTEMPTS", "5")
    settings = Settings(project_root=tmp_path)
    assert settings.model == "qwen2.5-coder:7b"
    assert settings.max_edit_attempts == 5
    assert Path(settings.project_root) == tmp_path
