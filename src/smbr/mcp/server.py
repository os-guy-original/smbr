"""MCP servers as registry tools.

One McpServerTool per enabled server. The remote tools ride the
same registry and the same gates as built-ins: the
declared-capabilities gate covers them through the mcp capability,
and per-step exposure decides which of them the model may call.
"""

from __future__ import annotations

from smbr.preflight.capabilities import Capability
from smbr.tools.registry import ToolHealth


class McpServerTool:
    """An MCP server: a bundle of remote tools behind one process."""

    name = "mcp"
    capability = Capability.MCP

    def __init__(self, config, timeout: float | None = None) -> None:
        self.config = config
        self.timeout = config.timeout if timeout is None else timeout

    @property
    def server_name(self) -> str:
        return self.config.name

    def health(self) -> ToolHealth:
        client = self.config.client(self.timeout)
        available, detail = client.health()
        if available:
            return ToolHealth.ok(self.capability, detail)
        return ToolHealth.broken(self.capability, detail)

    def remote_tools(self) -> list[dict]:
        """The server's tool definitions, or [] when it is down."""
        client = self.config.client(self.timeout)
        try:
            client.open()
            client.initialize()
            return client.list_tools()
        except Exception:  # a down server lists nothing
            return []
        finally:
            client.close()

    def call(self, tool_name: str, arguments: dict) -> str:
        """Call one remote tool by its name."""
        client = self.config.client(self.timeout)
        try:
            client.open()
            client.initialize()
            return client.call_tool(tool_name, arguments)
        finally:
            client.close()
