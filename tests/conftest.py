"""Shared fixtures."""

from __future__ import annotations

import textwrap

import pytest

SAMPLE_APP = '''\
import os
from typing import Optional

DEFAULT_TIMEOUT = 30


class Client:
    """A client."""

    def __init__(self, host: str) -> None:
        self.host = host

    def fetch(self, path: str) -> str:
        return os.path.join(self.host, path)


def helper(x: int) -> Optional[int]:
    # this helper returns the doubled input value
    return x * 2
'''

CLEAN_CODE = '''\
def double(x):
    """Return x doubled."""
    return x * 2
'''

MESSY_CODE = '''\
def double(x):
    # return x times two
    # y = 2
    """Not a docstring position."""
    return x * 2
'''


class StubClient:
    """A CompletionClient that answers from a scripted queue."""

    def __init__(self, answers: list[dict] | None = None, boom: bool = False) -> None:
        self.answers = list(answers or [])
        self.boom = boom
        self.calls: list[tuple[str, dict]] = []

    def complete_json(self, prompt: str, schema: dict) -> dict:
        self.calls.append((prompt, schema))
        if self.boom:
            raise RuntimeError("stub failure")
        if not self.answers:
            msg = "stub client ran out of answers"
            raise IndexError(msg)
        return self.answers.pop(0)


@pytest.fixture
def sample_source() -> str:
    return SAMPLE_APP


@pytest.fixture
def stub_client_factory():
    """Build scripted CompletionClient stubs: make(answers=[...], boom=True)."""

    def make(answers: list[dict] | None = None, boom: bool = False) -> StubClient:
        return StubClient(answers, boom)

    return make


# A stand-in MCP server: reads one JSON-RPC message per line and
# answers initialize, tools/list and tools/call. Real subprocess, real
# wire code, no MCP SDK.
FAKE_SERVER = textwrap.dedent(
    """
    import json
    import sys

    for line in sys.stdin:
        message = json.loads(line)
        method = message.get("method")
        if method == "initialize":
            result = {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "fake", "version": "0"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo the text back",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    }
                ]
            }
        elif method == "tools/call":
            text = message["params"]["arguments"].get("text", "")
            result = {
                "content": [{"type": "text", "text": f"echo: {text}"}],
                "isError": False,
            }
        else:
            result = {}
        response = {"jsonrpc": "2.0", "id": message.get("id"), "result": result}
        print(json.dumps(response), flush=True)
    """
)


@pytest.fixture
def fake_server(tmp_path):
    script = tmp_path / "fake_mcp_server.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    return script
