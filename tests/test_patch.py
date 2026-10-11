"""Patch apply: sandboxed preview, real application, path safety."""

from __future__ import annotations

import difflib

import pytest

from smbr.tools.patch import PatchApplyTool, PatchError

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"


def _diff(path: str, before: str, after: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(lines)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "calc.py").write_text(BUGGY, encoding="utf-8")
    return tmp_path


def test_preview_does_not_touch_the_tree(project) -> None:
    tool = PatchApplyTool(cwd=str(project))
    after = tool.preview("calc.py", _diff("calc.py", BUGGY, FIXED))
    assert after == FIXED
    assert (project / "calc.py").read_text(encoding="utf-8") == BUGGY  # untouched


def test_apply_writes_the_working_tree(project) -> None:
    tool = PatchApplyTool(cwd=str(project))
    result = tool.apply("calc.py", _diff("calc.py", BUGGY, FIXED))
    assert result == FIXED
    assert (project / "calc.py").read_text(encoding="utf-8") == FIXED


def test_unapplicable_diff_raises(project) -> None:
    tool = PatchApplyTool(cwd=str(project))
    with pytest.raises(PatchError):
        tool.apply("calc.py", "not a diff at all")
    assert tool.preview("calc.py", "not a diff at all") is None


def test_traversal_paths_are_refused(project) -> None:
    tool = PatchApplyTool(cwd=str(project))
    assert tool.preview("../outside.py", _diff("../outside.py", "x\n", "y\n")) is None
    with pytest.raises(PatchError):
        tool.apply("/etc/passwd", _diff("/etc/passwd", "x\n", "y\n"))


def test_health_needs_git_and_root(tmp_path) -> None:
    assert PatchApplyTool(cwd=str(tmp_path)).health().available
    assert not PatchApplyTool(cwd=str(tmp_path / "missing")).health().available
