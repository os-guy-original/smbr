"""Ollama completion client with structured outputs.

Uses Ollama's ``format=<json-schema>`` parameter (grammar-constrained
decoding) so the model can only emit the fields the harness allows.

Requires a running Ollama server; not exercised in CI (tests use a stub
client instead). Install with ``smbr[ollama]`` and pull a model, e.g.
``ollama pull gemma4:e4b``.
"""

from __future__ import annotations

import json


class OllamaCompletionClient:
    """CompletionClient backed by a local Ollama server."""

    def __init__(
        self,
        model: str,
        host: str | None = None,
        timeout: float = 300.0,
    ) -> None:
        import ollama  # imported lazily so the core never depends on it

        self.model = model
        if host:
            self._client = ollama.Client(host, timeout=timeout)
        else:
            self._client = ollama.Client(timeout=timeout)

    def complete_json(self, prompt: str, schema: dict) -> dict:
        response = self._client.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            format=schema,
        )
        content = response.message.content
        data = json.loads(content)
        if not isinstance(data, dict):
            msg = f"model returned {type(data).__name__}, expected object"
            raise TypeError(msg)
        return data
