"""Import discovery: foreign configs become SMBR servers.

Each fixture below is the shape that agent's docs describe, so a
regression in a wrapper key or entry mapping fails here rather than on
a user's machine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smbr.imports.discovery import (
    discover_mcp,
    discover_skills,
    parse_json_tolerant,
    parse_server,
    server_map,
    skill_description,
    strip_jsonc,
)

OPENCODE_JSONC = """\
// OpenCode accepts JSONC
{
  "mcp": {
    "replay": {
      "type": "local",
      "command": ["npx", "-y", "@modelcontextprotocol/server-everything"],
      "enabled": true,
    },
    "off": {"type": "local", "command": ["echo", "hi"], "enabled": false},
    "context7": {
      "type": "remote",
      "url": "https://mcp.context7.com/mcp",
      "enabled": true,
    },
    "slow": {"type": "local", "command": ["./slow"], "timeout": 600000},
  },
}
"""

CLAUDE_MCP = {
    "mcpServers": {
        "airtable": {
            "command": "npx",
            "args": ["-y", "airtable-mcp-server"],
            "env": {"AIRTABLE_API_KEY": "${AIRTABLE_API_KEY}"},
        },
        "notion": {"type": "http", "url": "https://mcp.notion.com/mcp"},
        "broken": {"command": ""},
    }
}

CLAUDE_USER = {
    "projects": {
        "/work/proj": {"mcpServers": {"stripe": {"type": "http", "url": "https://mcp.stripe.com"}}}
    }
}

VSCODE_MCP = {
    "servers": {"memory": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"]}}
}

WINDSURF_MCP = {
    "mcpServers": {"w": {"command": "windsurf-mcp", "args": ["--port", "1"], "timeout": 45}}
}


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_jsonc_is_parsed(tmp_path) -> None:
    doc = parse_json_tolerant(OPENCODE_JSONC)
    assert doc is not None
    assert "replay" in doc["mcp"]


def test_jsonc_strings_with_comment_text_survive() -> None:
    text = '{"a": "http://x // not a comment", "b": "/* also not */"}'
    doc = parse_json_tolerant(text)
    assert doc == {"a": "http://x // not a comment", "b": "/* also not */"}


def test_jsonc_strip_keeps_escaped_quotes() -> None:
    assert json.loads(strip_jsonc('{"a": "he said \\"hi\\"" /* c */}')) == {"a": 'he said "hi"'}


def test_opencode_local_servers_import(tmp_path) -> None:
    config = tmp_path / "opencode.json"
    config.write_text(OPENCODE_JSONC, encoding="utf-8")
    (result,) = discover_mcp([config])
    names = [s.name for s in result.servers]
    assert names == ["replay", "slow"]
    replay = result.servers[0]
    assert replay.command == "npx"
    assert replay.args == ("-y", "@modelcontextprotocol/server-everything")
    # 600000 is milliseconds, matching Claude's and OpenCode's convention
    assert result.servers[1].timeout == 600.0
    reasons = {s.name: s.reason for s in result.skipped}
    assert "remote transport" in reasons["context7"]
    assert "disabled" in reasons["off"]


def test_claude_project_config_imports(tmp_path) -> None:
    config = write_json(tmp_path / ".mcp.json", CLAUDE_MCP)
    (result,) = discover_mcp([config])
    assert [s.name for s in result.servers] == ["airtable"]
    airtable = result.servers[0]
    assert airtable.command == "npx"
    assert airtable.args == ("-y", "airtable-mcp-server")
    # credentials stay as references; the client expands them at spawn time
    assert airtable.env == {"AIRTABLE_API_KEY": "${AIRTABLE_API_KEY}"}
    assert {s.name for s in result.skipped} == {"notion", "broken"}


def test_claude_user_scope_reads_the_project_entry(tmp_path) -> None:
    config = write_json(tmp_path / "claude.json", CLAUDE_USER)
    (result,) = discover_mcp([config], project_root=Path("/work/proj"))
    # the only entry is remote, so it is reported, not silently dropped
    assert result.servers == []
    assert [s.name for s in result.skipped] == ["stripe"]


def test_vscode_servers_key_imports(tmp_path) -> None:
    config = write_json(tmp_path / "mcp.json", VSCODE_MCP)
    (result,) = discover_mcp([config])
    assert [s.name for s in result.servers] == ["memory"]
    assert result.servers[0].args == ("-y", "@modelcontextprotocol/server-memory")


def test_portable_timeout_under_a_thousand_is_seconds(tmp_path) -> None:
    config = write_json(tmp_path / "windsurf.json", WINDSURF_MCP)
    (result,) = discover_mcp([config])
    assert result.servers[0].timeout == 45.0


def test_missing_file_is_skipped_quietly(tmp_path) -> None:
    assert discover_mcp([tmp_path / "nope.json"]) == []


def test_unreadable_file_is_reported_not_fatal(tmp_path) -> None:
    bad = tmp_path / "mcp.json"
    bad.write_text("{ not json", encoding="utf-8")
    (result,) = discover_mcp([bad])
    assert result.error


def test_file_without_a_known_wrapper_is_reported(tmp_path) -> None:
    config = write_json(tmp_path / "mcp.json", {"unrelated": {"a": 1}})
    (result,) = discover_mcp([config])
    assert result.error
    assert "server map" in result.error


@pytest.mark.parametrize(
    ("name", "spec", "expected_reason"),
    [
        ("a", "not a dict", "not an object"),
        ("a", {}, "no 'command'"),
        ("a", {"command": "  "}, "blank command"),
        ("a", {"command": ["only"]}, None),
        ("a", {"command": ["ok"], "env": "nope"}, "'env' is not an object"),
        ("a", {"command": "ok", "args": "nope"}, "'args' is not a list"),
        ("a", {"command": "ok", "type": "SSE"}, "remote transport"),
        ("a", {"command": "ok", "url": "https://x"}, "remote transport"),
        ("a", {"command": "ok", "enabled": False}, "disabled"),
    ],
)
def test_entry_rejections_carry_reasons(name, spec, expected_reason) -> None:
    server, skipped = parse_server(name, spec, "origin")
    if expected_reason is None:
        assert server is not None and skipped is None
        assert server.command == "only"
    else:
        assert server is None
        assert skipped is not None and expected_reason in skipped.reason


def test_wrapper_detection_prefers_the_first_known_key() -> None:
    doc = {"servers": {"a": {"command": "x"}}, "mcpServers": {"b": {"command": "y"}}}
    servers, key = server_map(doc)
    assert key == "mcpServers"
    assert "b" in servers  # the portable wrapper wins over the VS Code one


SKILL_MD = """---
name: demo
description: A demo skill for tests.
---

# Demo

Does demo things.
"""


def _skill(root: Path, name: str, body: str = SKILL_MD) -> Path:
    path = root / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(body, encoding="utf-8")
    return path


def test_discover_skills_finds_folders_with_skill_md(tmp_path) -> None:
    _skill(tmp_path, "demo")
    _skill(tmp_path, "other")
    (tmp_path / "not-a-skill").mkdir()
    found = discover_skills([tmp_path])
    assert [s.name for s in found] == ["demo", "other"]
    assert found[0].path == tmp_path / "demo"


def test_discover_skills_ignores_missing_roots(tmp_path) -> None:
    assert discover_skills([tmp_path / "nope"]) == []


def test_skill_description_reads_frontmatter(tmp_path) -> None:
    path = _skill(tmp_path, "demo")
    assert skill_description(path) == "A demo skill for tests."


def test_skill_description_missing_is_empty(tmp_path) -> None:
    path = _skill(tmp_path, "demo", body="# no frontmatter\n")
    assert skill_description(path) == ""


def test_skill_description_reads_folded_block_scalars(tmp_path) -> None:
    path = _skill(
        tmp_path,
        "folded",
        body="---\nname: folded\ndescription: >\n  First line\n  second line\n---\n\n# Body\n",
    )
    assert skill_description(path) == "First line second line"


def test_skill_description_strips_quotes(tmp_path) -> None:
    path = _skill(tmp_path, "quoted", body='---\ndescription: "A quoted one"\n---\n')
    assert skill_description(path) == "A quoted one"


def test_skill_description_ignores_later_keys(tmp_path) -> None:
    path = _skill(
        tmp_path,
        "multi",
        body="---\nname: multi\ndescription: The real one\nversion: 2\n---\n",
    )
    assert skill_description(path) == "The real one"
