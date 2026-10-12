"""MCP server configuration.

The config shape is the common one (command, arguments,
environment), so configs port between MCP hosts. Only servers
explicitly enabled are started — the user reviews what an
import adds before it runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smbr.mcp.client import McpStdioClient


class McpConfigError(ValueError):
    """The config file is malformed. Named so callers can tell it
    from a missing (harmless) file."""


@dataclass(frozen=True)
class McpServerConfig:
    """One opt-in MCP server."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True

    def client(self, timeout: float) -> McpStdioClient:
        from smbr.mcp.client import McpStdioClient

        return McpStdioClient(self.command, self.args, self.env, timeout)


def load_mcp_config(path: str | Path) -> list[McpServerConfig]:
    """Load enabled servers from a ``{"mcpServers": {...}}`` file.

    A missing file means "no MCP servers", which is not an error.
    A malformed file is: silently ignoring a broken config would
    hide servers the user believes are running.
    """
    config_path = Path(path)
    if not config_path.is_file():
        return []
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"{config_path}: unreadable MCP config: {exc}"
        raise McpConfigError(msg) from exc
    servers = raw.get("mcpServers") if isinstance(raw, dict) else None
    if not isinstance(servers, dict):
        msg = f"{config_path}: expected an 'mcpServers' object"
        raise McpConfigError(msg)
    configs: list[McpServerConfig] = []
    for name, spec in servers.items():
        if not isinstance(spec, dict) or not isinstance(spec.get("command"), str):
            msg = f"{config_path}: server '{name}' needs a 'command' string"
            raise McpConfigError(msg)
        if spec.get("enabled", True) is False:
            continue
        configs.append(
            McpServerConfig(
                name=name,
                command=spec["command"],
                args=[str(a) for a in spec.get("args", [])],
                env={str(k): str(v) for k, v in spec.get("env", {}).items()},
            )
        )
    return configs
