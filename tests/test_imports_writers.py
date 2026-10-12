"""The import writers: disabled-first, atomic, review-then-enable."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from smbr.imports.discovery import DiscoveredServer, SkillFound
from smbr.imports.mcp_config import load_smbr_mcp, merge_servers, write_json_atomic
from smbr.imports.skills import import_skills, load_manifest, sha256_of

ECHO = DiscoveredServer(
    name="echo", command="npx", args=("-y", "echo-mcp"), origin="test", timeout=45.0
)


def test_first_import_writes_disabled_entries(tmp_path) -> None:
    target = tmp_path / ".smbr" / "mcp.json"
    report = merge_servers([ECHO], target)
    assert report.added == ["echo"]
    assert report.wrote is True
    doc = json.loads(target.read_text(encoding="utf-8"))
    entry = doc["mcpServers"]["echo"]
    assert entry == {
        "command": "npx",
        "args": ["-y", "echo-mcp"],
        "env": {},
        "timeout": 45,
        "enabled": False,
    }


def test_second_import_of_the_same_server_is_unchanged(tmp_path) -> None:
    target = tmp_path / "mcp.json"
    merge_servers([ECHO], target)
    report = merge_servers([ECHO], target)
    assert report.added == []
    assert report.unchanged == ["echo"]
    assert report.wrote is False


def test_conflicting_shape_needs_force(tmp_path) -> None:
    target = tmp_path / "mcp.json"
    merge_servers([ECHO], target)
    changed = DiscoveredServer(name="echo", command="other", args=(), origin="test")
    report = merge_servers([changed], target)
    assert report.conflicts == ["echo"]
    assert report.wrote is False
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert doc["mcpServers"]["echo"]["command"] == "npx"

    forced = merge_servers([changed], target, force=True)
    assert forced.updated == ["echo"]
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert doc["mcpServers"]["echo"]["command"] == "other"


def test_import_merges_without_dropping_existing_servers(tmp_path) -> None:
    target = tmp_path / "mcp.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"mcpServers": {"mine": {"command": "x", "enabled": True}}}), encoding="utf-8"
    )
    report = merge_servers([ECHO], target)
    assert sorted(report.added) == ["echo"]
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert doc["mcpServers"]["mine"] == {"command": "x", "enabled": True}
    assert doc["mcpServers"]["echo"]["enabled"] is False


def test_dry_run_leaves_no_file(tmp_path) -> None:
    target = tmp_path / "mcp.json"
    # merge_servers only writes when something changed; a caller wanting a
    # dry run must not call it with a real target. The CLI never does.
    report = merge_servers([], target)
    assert report.wrote is False
    assert not target.exists()


def test_write_is_atomic_on_failure(tmp_path, monkeypatch) -> None:
    target = tmp_path / "mcp.json"

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", boom)
    with contextlib.suppress(OSError):
        write_json_atomic(target, {"a": 1})
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []  # no temp file left behind


def test_load_handles_a_corrupt_config(tmp_path) -> None:
    target = tmp_path / "mcp.json"
    target.write_text("{ broken", encoding="utf-8")
    assert load_smbr_mcp(target) == {}
    assert load_smbr_mcp(tmp_path / "nope.json") == {}


# -- skills ----------------------------------------------------------------


def _skill(root: Path, name: str = "demo") -> SkillFound:
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: skill {name}\n---\n\n# {name}\n", encoding="utf-8"
    )
    (path / "helper.py").write_text("x = 1\n", encoding="utf-8")
    return SkillFound(name=name, path=path, origin=str(root))


def test_import_copies_the_skill_and_records_provenance(tmp_path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    skill = _skill(source_root)
    skills_dir = tmp_path / ".smbr" / "skills"
    manifest = tmp_path / ".smbr" / "skills.json"

    report = import_skills([skill], skills_dir, manifest)

    assert report.imported == ["demo"]
    assert (skills_dir / "demo" / "SKILL.md").is_file()
    assert (skills_dir / "demo" / "helper.py").read_text(encoding="utf-8") == "x = 1\n"
    entries = load_manifest(manifest)
    assert entries[0]["name"] == "demo"
    assert entries[0]["source"] == str(skill.path)
    assert entries[0]["sha256"] == sha256_of(skill.path / "SKILL.md")
    assert entries[0]["description"] == "skill demo"


def test_reimport_of_an_unchanged_skill_is_a_noop(tmp_path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    skill = _skill(source_root)
    skills_dir = tmp_path / ".smbr" / "skills"
    manifest = tmp_path / ".smbr" / "skills.json"

    assert import_skills([skill], skills_dir, manifest).imported == ["demo"]
    (skills_dir / "demo" / "SKILL.md").write_text("tampered\n", encoding="utf-8")
    report = import_skills([skill], skills_dir, manifest)
    assert report.imported == []  # unchanged content, not re-copied
    assert "unchanged" in report.skipped[0][1]
    assert (skills_dir / "demo" / "SKILL.md").read_text(encoding="utf-8") == "tampered\n"


def test_existing_different_skill_needs_force(tmp_path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    skill = _skill(source_root)
    skills_dir = tmp_path / ".smbr" / "skills"
    manifest = tmp_path / ".smbr" / "skills.json"
    import_skills([skill], skills_dir, manifest)

    (skill.path / "SKILL.md").write_text(
        "---\nname: demo\ndescription: changed\n---\n", encoding="utf-8"
    )
    report = import_skills([skill], skills_dir, manifest)
    assert report.imported == []
    assert report.skipped[0][0] == "demo"

    forced = import_skills([skill], skills_dir, manifest, force=True)
    assert forced.imported == ["demo"]
    assert "changed" in (skills_dir / "demo" / "SKILL.md").read_text(encoding="utf-8")


def test_symlink_escape_is_refused(tmp_path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    skill = _skill(source_root)
    outside = tmp_path / "secret.txt"
    outside.write_text("do not copy\n", encoding="utf-8")
    (skill.path / "escape").symlink_to(outside)

    report = import_skills([skill], tmp_path / ".smbr" / "skills", tmp_path / "skills.json")

    assert report.imported == []
    assert "escapes" in report.skipped[0][1]


def test_oversize_skill_is_refused(tmp_path, monkeypatch) -> None:
    from smbr.imports import skills as skills_module

    monkeypatch.setattr(skills_module, "MAX_SKILL_BYTES", 16)
    source_root = tmp_path / "src"
    source_root.mkdir()
    skill = _skill(source_root)

    report = import_skills([skill], tmp_path / ".smbr" / "skills", tmp_path / "skills.json")

    assert report.imported == []
    assert "cap" in report.skipped[0][1]


def test_dry_run_writes_nothing(tmp_path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    skill = _skill(source_root)
    skills_dir = tmp_path / ".smbr" / "skills"
    manifest = tmp_path / "skills.json"

    report = import_skills([skill], skills_dir, manifest, dry_run=True)

    assert report.imported == ["demo"]
    assert not skills_dir.exists()
    assert not manifest.exists()
