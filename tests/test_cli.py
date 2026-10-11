"""CLI: version and the genuinely useful preflight check."""

from __future__ import annotations

import json

from smbr.cli import main


def test_version(capsys) -> None:
    assert main(["version"]) == 0
    assert "smbr" in capsys.readouterr().out


def test_preflight_ok(tmp_path, capsys) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {"task": "read the form", "requires": [{"capability": "file_read", "why": "x"}]}
        ),
        encoding="utf-8",
    )
    assert main(["preflight", str(manifest)]) == 0
    assert "preflight ok" in capsys.readouterr().out


def test_preflight_failure_uses_harness_template(tmp_path, capsys) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {"task": "look up docs", "requires": [{"capability": "docs_lookup", "why": "x"}]}
        ),
        encoding="utf-8",
    )
    assert main(["preflight", str(manifest)]) == 1
    out = capsys.readouterr().out
    assert "not installed" in out and "docs_lookup" in out


def test_preflight_bad_json_is_usage_error(tmp_path, capsys) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{not json", encoding="utf-8")
    assert main(["preflight", str(manifest)]) == 2
    assert "cannot read manifest" in capsys.readouterr().err
