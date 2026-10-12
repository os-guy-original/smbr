"""The git tool: history, diffs, and the rollback path."""

from __future__ import annotations

import subprocess

import pytest

from smbr.tools.git import GitTool


@pytest.fixture
def repo(tmp_path):
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    for flag, value in (("user.name", "T"), ("user.email", "t@t")):
        subprocess.run(("git", "config", flag, value), cwd=tmp_path, check=True)
    return tmp_path


def _commit(repo, name: str, content: str, message: str = "initial") -> None:
    (repo / name).write_text(content, encoding="utf-8")
    subprocess.run(("git", "add", name), cwd=repo, check=True)
    subprocess.run(("git", "commit", "-q", "-m", message), cwd=repo, check=True)


def test_health_reports_git_on_path() -> None:
    health = GitTool().health()
    assert health.installed is True
    assert health.available is True


def test_status_log_and_diff(repo) -> None:
    _commit(repo, "a.py", "one\n")
    tool = GitTool(cwd=str(repo))
    assert tool.status() == ""
    assert "initial" in tool.log()
    assert tool.diff() == ""
    (repo / "a.py").write_text("two\n", encoding="utf-8")
    assert "a.py" in tool.status()
    assert "+two" in tool.diff()


def test_rollback_restores_the_committed_content(repo) -> None:
    _commit(repo, "a.py", "original\n")
    (repo / "a.py").write_text("edited\n", encoding="utf-8")
    restored = GitTool(cwd=str(repo)).rollback(["a.py"])
    assert restored == ["a.py"]
    assert (repo / "a.py").read_text(encoding="utf-8") == "original\n"


def test_rollback_outside_a_repo_restores_nothing(tmp_path) -> None:
    assert GitTool(cwd=str(tmp_path)).rollback(["a.py"]) == []
