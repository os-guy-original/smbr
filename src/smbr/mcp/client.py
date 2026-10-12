"""MCP client over the stdio transport.

Speaks JSON-RPC 2.0, newline-delimited, to a subprocess — the wire
format the Model Context Protocol defines for stdio servers
(initialize, then tools/list and tools/call). No MCP SDK: the
protocol is small and a subprocess plus two pipes is all it needs,
which keeps the dependency surface at zero.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping

PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    """The server misbehaved. The message is safe to show the user."""


class McpStdioClient:
    """One MCP server, spawned per use so no process outlives a call."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self.timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._request_id = 0

    def initialize(self) -> dict:
        """Handshake: initialize request, then the initialized notification."""
        result = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "smbr", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized")
        return result

    def list_tools(self) -> list[dict]:
        """The server's tool definitions (name, description, inputSchema)."""
        result = self._request("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            msg = "tools/list returned no tools array"
            raise McpError(msg)
        return [t for t in tools if isinstance(t, dict) and "name" in t]

    def call_tool(self, name: str, arguments: dict) -> str:
        """Call one remote tool; returns its text content."""
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            msg = f"mcp tool {name} returned an error"
            raise McpError(msg)
        content = result.get("content")
        if not isinstance(content, list):
            msg = f"mcp tool {name} returned no content"
            raise McpError(msg)
        texts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(texts)

    def health(self) -> tuple[bool, str]:
        """Spawn, handshake, list tools, and shut down. Never raises."""
        try:
            self.open()
            info = self.initialize()
            tools = self.list_tools()
            server = info.get("serverInfo", {})
            name = server.get("name", self.command)
            return True, f"{name}: {len(tools)} tool(s)"
        except (OSError, McpError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            return False, f"{self.command}: {exc}"
        finally:
            self.close()

    def open(self) -> None:
        """Start the server subprocess."""
        self._start()

    def close(self) -> None:
        """Stop the server subprocess."""
        self._stop()

    # -- transport ------------------------------------------------------

    def _start(self) -> None:
        merged = {**os.environ, **self.env}
        self._proc = subprocess.Popen(  # the user configures the server command
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=merged,
            text=True,
        )

    def _send(self, message: dict) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(message) + "\n")
        self._proc.stdin.flush()

    def _recv(self) -> dict:
        assert self._proc is not None and self._proc.stdout is not None
        line = self._proc.stdout.readline()
        if not line:
            msg = "server closed the connection"
            raise McpError(msg)
        return json.loads(line)

    def _request(self, method: str, params: dict) -> dict:
        """Send one request and read until its response arrives."""
        self._request_id += 1
        request_id = self._request_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            message = self._recv()
            if message.get("id") == request_id:
                if "error" in message:
                    msg = f"{method} failed: {message['error']}"
                    raise McpError(msg)
                return message.get("result", {})

    def _notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method})

    def _stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
