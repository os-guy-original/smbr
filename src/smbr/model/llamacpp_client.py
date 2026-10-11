"""llama.cpp server completion client.

Talks to llama.cpp's OpenAI-compatible endpoint with a JSON-schema response
format. The server must be started with ``--jinja`` for chat formatting.

UNVERIFIED against a running server (none available in CI) — the request
shape follows llama.cpp's documented structured-output support; treat the
first real run as the verification step.
"""

from __future__ import annotations

import json
import urllib.request


class LlamaCppCompletionClient:
    """CompletionClient backed by a local llama.cpp server."""

    def __init__(self, base_url: str = "http://localhost:8080", timeout: float = 300.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def complete_json(self, prompt: str, schema: dict) -> dict:
        payload = {
            "model": "local",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "smbr_answer", "schema": schema},
            },
        }
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        data = json.loads(content)
        if not isinstance(data, dict):
            msg = f"server returned {type(data).__name__}, expected object"
            raise TypeError(msg)
        return data
