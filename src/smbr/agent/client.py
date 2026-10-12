"""Model and decision-layer factories, driven by Settings.

The kernel never imports a backend. Callers build a CompletionClient here
and hand it to the agent; with the decision layer off, the router is the
disabled provider and SMBR asks the user every time.
"""

from __future__ import annotations

from smbr.config import Settings
from smbr.decisions.provider import (
    CompletionClient,
    ConstrainedJsonProvider,
    DecisionProfile,
    DecisionRouter,
    DisabledDecisionProvider,
)


def build_completion_client(settings: Settings) -> CompletionClient:
    """The model backend: a local server (Ollama, llama.cpp) or an OpenAI-compatible API."""
    backend = settings.model_backend
    if backend == "openai":
        from smbr.model.openai_client import OpenAICompletionClient

        if not settings.api_key:
            msg = (
                "model_backend='openai' needs an API key: set SMBR_API_KEY "
                "(or OPENAI_API_KEY) in the environment"
            )
            raise ValueError(msg)
        return OpenAICompletionClient(
            model=settings.model,
            api_key=settings.api_key,
            base_url=settings.api_base_url,
            timeout=settings.model_timeout,
        )
    # decision_provider='llamacpp' also selects the server (legacy setting)
    if backend == "llamacpp" or settings.decision_provider == "llamacpp":
        from smbr.model.llamacpp_client import LlamaCppCompletionClient

        return LlamaCppCompletionClient(
            base_url=settings.model_host or "http://localhost:8080",
            timeout=settings.model_timeout,
        )
    from smbr.model.ollama_client import OllamaCompletionClient

    return OllamaCompletionClient(
        model=settings.model,
        host=settings.model_host,
        timeout=settings.model_timeout,
    )


def build_decision_router(
    settings: Settings,
    client: CompletionClient | None = None,
) -> DecisionRouter:
    """Router for bounded judgments; low confidence always routes to the user."""
    profile = DecisionProfile(defaults=settings.decision_profile)
    if not settings.decision_layer_enabled or settings.decision_provider == "off":
        return DecisionRouter(DisabledDecisionProvider(), profile)
    if client is None:
        client = build_completion_client(settings)
    return DecisionRouter(ConstrainedJsonProvider(client), profile)
