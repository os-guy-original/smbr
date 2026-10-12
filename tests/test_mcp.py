"""MCP: the stdio client, the config, and the registry integration.

The tests drive a real subprocess: a fake MCP server (the
``fake_server`` fixture in conftest) that speaks newline-delimited
JSON-RPC 2.0, so the handshake, tool listing, and tool calls run
the actual wire code.
"""

from __future__ import annotations

import json
import sys

import pytest

from smbr.config import Settings
from smbr.kernel.state import Step
from smbr.mcp import McpConfigError, McpServerTool, load_mcp_config
from smbr.preflight.capabilities import Capability
from smbr.tools.registry import ToolRegistry


def test_client_handshake_list_and_call(fake_server) -> None:
    from smbr.mcp import McpStdioClient

    client = McpStdioClient(sys.executable, [str(fake_server)], timeout=10)
    try:
        client.open()
        info = client.initialize()
        assert info["serverInfo"]["name"] == "fake"
        tools = client.list_tools()
        assert [t["name"] for t in tools] == ["echo"]
        output = client.call_tool("echo", {"text": "hi"})
        assert output == "echo: hi"
    finally:
        client.close()


def test_client_health_reports_the_server(fake_server) -> None:
    from smbr.mcp import McpStdioClient

    client = McpStdioClient(sys.executable, [str(fake_server)], timeout=10)
    available, detail = client.health()
    assert available is True
    assert "fake" in detail


def test_client_health_reports_a_dead_server() -> None:
    from smbr.mcp import McpStdioClient

    client = McpStdioClient("definitely-not-a-command-xyz", timeout=5)
    available, detail = client.health()
    assert available is False
    assert detail


def test_config_loads_enabled_servers_only(tmp_path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "kept": {"command": "echo", "enabled": True},
                    "dropped": {"command": "echo", "enabled": False},
                }
            }
        ),
        encoding="utf-8",
    )
    servers = load_mcp_config(config)
    assert [s.name for s in servers] == ["kept"]
    assert servers[0].command == "echo"


def test_config_missing_file_is_no_servers(tmp_path) -> None:
    assert load_mcp_config(tmp_path / "nope.json") == []


def test_config_malformed_file_raises(tmp_path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text("{not json", encoding="utf-8")
    with pytest.raises(McpConfigError):
        load_mcp_config(config)


def test_config_missing_command_raises(tmp_path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"mcpServers": {"bad": {}}}), encoding="utf-8")
    with pytest.raises(McpConfigError):
        load_mcp_config(config)


def test_server_tool_exposes_and_calls_remote_tools(fake_server) -> None:
    from smbr.mcp.config import McpServerConfig

    server = McpServerTool(
        McpServerConfig(name="fake", command=sys.executable, args=[str(fake_server)]),
        timeout=10,
    )
    assert server.health().available is True
    assert [t["name"] for t in server.remote_tools()] == ["echo"]
    assert server.call("echo", {"text": "yo"}) == "echo: yo"


def test_registry_registers_remote_tool_names(fake_server) -> None:
    from smbr.mcp.config import McpServerConfig

    registry = ToolRegistry()
    registry.register_mcp(
        McpServerTool(
            McpServerConfig(name="fake", command=sys.executable, args=[str(fake_server)]),
            timeout=10,
        )
    )
    exposed = registry.expose(Step.EDIT)
    assert "echo" in exposed
    # a step that does not see the mcp capability never sees the remote tool
    assert "echo" not in registry.expose(Step.INTAKE)
    assert registry.mcp_tool_for("echo") is not None
    assert registry.mcp_tool_for("nope") is None


def test_registry_check_covers_the_mcp_capability(fake_server) -> None:
    from smbr.mcp.config import McpServerConfig

    registry = ToolRegistry()
    registry.register_mcp(
        McpServerTool(
            McpServerConfig(name="fake", command=sys.executable, args=[str(fake_server)]),
            timeout=10,
        )
    )
    mcp = registry.check(Capability.MCP)
    assert mcp.available is True
    # the generic tool name is not a callable; remote names are
    assert "mcp" not in registry.expose(Step.EDIT)
    assert "echo" in registry.expose(Step.EDIT)


def test_registry_check_without_servers_reports_absent() -> None:
    registry = ToolRegistry()
    health = registry.check(Capability.MCP)
    assert health.installed is False
    assert health.available is False


def test_settings_default_mcp_path() -> None:
    settings = Settings()
    assert settings.mcp_config == ".smbr/mcp.json"
    assert settings.mcp_timeout > 0
