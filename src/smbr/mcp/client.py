"""MCP client over the stdio transport.

Speaks JSON-RPC 2.0, newline-delimited, to a subprocess — the wire
format the Model Context Protocol defines for stdio servers
(initialize, then tools/list and tools/call). No MCP SDK: the
protocol is small and a subprocess plus two pipes is all it needs,
which keeps the dependency surface at zero.

Stability rules the transport owes the caller: every read is bounded
by the timeout (a hung server fails, it does not wedge the run), a
message has a size cap, and ``${VAR}`` / ``${VAR:-default}`` are
expanded at spawn time so secrets never touch the config file.
"""

from __future__ import annotations

import json
import os
import re
import select
import subprocess
import time
from collections.abc import Mapping

PROTOCOL_VERSION = "2025-06-18"

# A response larger than this is a broken or hostile server, not a
# legitimate tool result.
MAX_MESSAGE_BYTES = 8 * 1024 * 1024

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class McpError(RuntimeError):
    """The server misbehaved. The message is safe to show the user."""


def expand_env(value: str, environ: Mapping[str, str]) -> str:
    """Expand ``${VAR}`` and ``${VAR:-default}``; unknown vars stay literal."""

    def replace(match: re.Match) -> str:
        name, default = match.group(1), match.group(2)
        if name in environ:
            return environ[name]
        return default if default is not None else match.group(0)

    return _ENV_REF.sub(replace, value)


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
        self._buffer = b""
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
        argv = [expand_env(part, merged) for part in (self.command, *self.args)]
        self._proc = subprocess.Popen(  # the user configures the server command
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={k: expand_env(v, merged) for k, v in merged.items()},
        )
        self._buffer = b""

    def _send(self, message: dict) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        payload = json.dumps(message).encode("utf-8") + b"\n"
        self._proc.stdin.write(payload)
        self._proc.stdin.flush()

    def _recv(self) -> dict:
        line = self._read_line()
        if not line:
            msg = "server closed the connection"
            raise McpError(msg)
        try:
            return json.loads(line.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            msg = f"server sent a malformed message: {exc}"
            raise McpError(msg) from exc

    def _read_line(self) -> bytes:
        """One newline-delimited message, bounded by the timeout.

        Every read waits at most ``self.timeout`` seconds: a server that
        stops answering fails the call instead of wedging the run.
        """
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                line, self._buffer = self._buffer[:newline], self._buffer[newline + 1 :]
                return line
            if len(self._buffer) > MAX_MESSAGE_BYTES:
                msg = f"server sent more than {MAX_MESSAGE_BYTES} bytes without a newline"
                raise McpError(msg)
            self._wait_readable(proc)
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                line, self._buffer = self._buffer, b""
                return line
            self._buffer += chunk

    def _wait_readable(self, proc: subprocess.Popen) -> None:
        """Block until stdout has bytes, or the timeout expires."""
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                msg = f"server did not respond within {self.timeout:.0f}s"
                raise McpError(msg)
            try:
                ready, _, _ = select.select([proc.stdout], [], [], remaining)
            except (OSError, ValueError):
                # select cannot watch this handle (Windows pipes): fall back
                # to a blocking read, correct but unbounded.
                return
            if ready:
                return
            msg = f"server did not respond within {self.timeout:.0f}s"
            raise McpError(msg)

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
