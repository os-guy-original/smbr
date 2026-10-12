"""``smbr import`` and ``smbr skills`` end to end through the CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smbr.cli import main

OPENCODE_CONFIG = """\
// this is OpenCode's shape
{
  "mcp": {
    "replay": {
      "type": "local",
      "command": ["npx", "-y", "@modelcontextprotocol/server-everything"],
      "enabled": true,
    },
    "context7": {"type": "remote", "url": "https://mcp.context7.com/mcp", "enabled": true},
  },
}
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    # keep the ambient environment out of the settings and out of discovery:
    # a hermetic HOME/XDG_CONFIG_HOME means the test only sees the fixtures
    # it writes itself
    import os

    for key in list(os.environ):
        if key.startswith("SMBR_"):
            monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _config(project: Path) -> Path:
    path = project / ".opencode" / "opencode.json"
    path.parent.mkdir(parents=True)
    path.write_text(OPENCODE_CONFIG, encoding="utf-8")
    return path


def test_import_mcp_writes_disabled_entries(project, capsys) -> None:
    _config(project)
    code = main(["import", "mcp", "--from", "opencode"])
    out = capsys.readouterr().out
    assert code == 0
    assert "added: replay" in out
    target = project / ".smbr" / "mcp.json"
    doc = json.loads(target.read_text(encoding="utf-8"))
    entry = doc["mcpServers"]["replay"]
    assert entry["command"] == "npx"
    assert entry["args"] == ["-y", "@modelcontextprotocol/server-everything"]
    assert entry["enabled"] is False  # review before enabling
    # the remote server is reported, never silently dropped
    assert "skipped: context7" in out
    assert "remote transport" in out


def test_import_mcp_dry_run_writes_nothing(project, capsys) -> None:
    _config(project)
    code = main(["import", "mcp", "--from", "opencode", "--dry-run"])
    assert code == 0
    assert "added: replay" in capsys.readouterr().out
    assert not (project / ".smbr" / "mcp.json").exists()


def test_import_mcp_second_run_unchanged(project, capsys) -> None:
    _config(project)
    main(["import", "mcp", "--from", "opencode"])
    capsys.readouterr()
    code = main(["import", "mcp", "--from", "opencode"])
    assert code == 0
    assert "unchanged: replay" in capsys.readouterr().out


def test_import_mcp_conflict_needs_force(project, capsys) -> None:
    _config(project)
    main(["import", "mcp", "--from", "opencode"])
    target = project / ".smbr" / "mcp.json"
    doc = json.loads(target.read_text(encoding="utf-8"))
    doc["mcpServers"]["replay"]["command"] = "other"
    target.write_text(json.dumps(doc), encoding="utf-8")
    capsys.readouterr()

    code = main(["import", "mcp", "--from", "opcode" if False else "opencode"])
    assert code == 1
    assert "conflict: replay" in capsys.readouterr().out

    code = main(["import", "mcp", "--from", "opencode", "--force"])
    assert code == 0
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert doc["mcpServers"]["replay"]["command"] == "npx"


def test_import_mcp_explicit_path(project, capsys) -> None:
    source = project / "some-agent.json"
    source.write_text(
        json.dumps({"mcpServers": {"x": {"command": "x-mcp", "args": ["-v"]}}}), encoding="utf-8"
    )
    code = main(["import", "mcp", "--path", str(source)])
    assert code == 0
    assert "added: x" in capsys.readouterr().out


def test_unknown_source_is_a_clean_error(project, capsys) -> None:
    code = main(["import", "mcp", "--from", "definitely-not-an-agent"])
    assert code == 2  # usage error, with the known sources named
    err = capsys.readouterr().err
    assert "unknown source" in err


def test_scan_lists_what_the_machine_has(project, capsys) -> None:
    _config(project)
    code = main(["import", "scan"])
    assert code == 0
    out = capsys.readouterr().out
    assert "replay" in out
    assert "skipped" in out  # the remote server is named, not hidden


def _skill(project: Path, name: str = "demo", body: str | None = None) -> Path:
    path = project / ".opencode" / "skills" / name
    path.mkdir(parents=True, exist_ok=True)
    text = body
    if text is None:
        text = f"---\nname: {name}\ndescription: A demo skill.\n---\n\n# Demo\n"
    (path / "SKILL.md").write_text(text, encoding="utf-8")
    return path


def test_import_skills_copies_and_records_provenance(project, capsys) -> None:
    _skill(project)
    code = main(["import", "skills", "--from", "opencode"])
    out = capsys.readouterr().out
    assert code == 0
    assert "imported: demo" in out
    skills_dir = project / ".smbr" / "skills" / "demo"
    assert skills_dir.is_dir()
    manifest = json.loads((project / ".smbr" / "skills.json").read_text(encoding="utf-8"))
    assert manifest["skills"][0]["name"] == "demo"


def test_skills_list_shows_provenance(project, capsys) -> None:
    _skill(project)
    main(["import", "skills", "--from", "opencode"])
    capsys.readouterr()
    code = main(["skills"])
    out = capsys.readouterr().out
    assert code == 0
    assert "demo: A demo skill." in out
    assert "sha256" in out
    assert ".opencode/skills/demo" in out


def test_skills_list_without_imports_is_clear(project, capsys) -> None:
    assert main(["skills"]) == 0
    assert "no imported skills" in capsys.readouterr().out


def test_import_skills_conflict_needs_force(project, capsys) -> None:
    _skill(project)
    main(["import", "skills", "--from", "opencode"])
    capsys.readouterr()
    # change the source, then re-import without force
    _skill(project, "demo", body="---\nname: demo\ndescription: Changed.\n---\n")
    code = main(["import", "skills", "--from", "opencode"])
    assert code == 0
    out = capsys.readouterr().out
    assert "skipped: demo" in out
    # and the imported copy still carries the old text until --force
    assert (
        (project / ".smbr" / "skills" / "demo" / "SKILL.md")
        .read_text(encoding="utf-8")
        .endswith("# Demo\n")
    )
