"""OpenAI-compatible API completion client.

Talks to any endpoint that speaks the OpenAI chat-completions protocol —
OpenRouter, OpenAI, Groq, Together, or a self-hosted vLLM — so a machine
without the RAM for a local model is not locked out. No SDK dependency:
plain urllib, like the llama.cpp client.

The request asks for a JSON-schema response format in strict mode, so
providers with a native strict mode enforce the schema exactly.
Providers that reject it (some routers only speak ``json_object``, and
strict schemas with optional fields are rejected by OpenAI proper)
get a retry with the schema moved into the prompt; anything other
than a request-shape rejection is raised as-is.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class OpenAICompletionClient:
    """CompletionClient backed by an OpenAI-compatible chat API."""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 300.0,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout

    def complete_json(self, prompt: str, schema: dict) -> dict:
        try:
            return self._complete(prompt, schema, response_format="json_schema")
        except urllib.error.HTTPError as exc:
            if exc.code not in (400, 422):
                raise
        return self._complete(prompt, schema, response_format="json_object")

    def _complete(self, prompt: str, schema: dict, *, response_format: str) -> dict:
        content = self._prompt_for(prompt, schema, response_format)
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "response_format": {"type": response_format},
        }
        if response_format == "json_schema":
            # strict is what makes providers with a native strict mode enforce
            # the schema exactly (OpenRouter's documented practice); providers
            # that reject it fall back through complete_json.
            payload["response_format"]["json_schema"] = {
                "name": "smbr_answer",
                "strict": True,
                "schema": schema,
            }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        choices = body.get("choices") if isinstance(body, dict) else None
        if not choices:
            error = body.get("error") if isinstance(body, dict) else None
            msg = f"API returned no choices: {error or body!r}"
            raise RuntimeError(msg)
        content = (choices[0].get("message") or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            # a documented failure mode: a reasoning model spends its whole
            # token budget on reasoning and answers with nothing
            msg = "API returned no content (the model produced an empty answer)"
            raise RuntimeError(msg)
        data = json.loads(content)
        if not isinstance(data, dict):
            msg = f"model returned {type(data).__name__}, expected object"
            raise TypeError(msg)
        return data

    @staticmethod
    def _prompt_for(prompt: str, schema: dict, response_format: str) -> str:
        if response_format == "json_schema":
            return prompt
        return f"{prompt}\n\nRespond with a JSON object matching this schema: {json.dumps(schema)}"
