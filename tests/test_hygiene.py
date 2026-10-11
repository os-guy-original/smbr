"""Comment hygiene: added comments only; docstrings and reasons survive."""

from __future__ import annotations

from smbr.hygiene import classify, comment_findings


def test_docstrings_are_never_touched() -> None:
    before = 'def double(x):\n    """Docstring."""\n    return x * 2\n'
    after = (
        "def double(x):\n"
        '    """Docstring."""\n'
        "    # WHY: keep the arithmetic explicit for the generated docs\n"
        "    return x * 2\n"
    )
    assert comment_findings(before, after) == []


def test_restating_comment_flagged() -> None:
    before = "def double(x):\n    return x * 2\n"
    after = "def double(x):\n    # return x times two\n    return x * 2\n"
    findings = comment_findings(before, after)
    assert [f.kind for f in findings] == ["restates_code"]


def test_commented_out_code_flagged() -> None:
    before = "def f():\n    return 1\n"
    after = "def f():\n    # x = 2\n    return 1\n"
    findings = comment_findings(before, after)
    assert [f.kind for f in findings] == ["commented_out_code"]


def test_todo_with_reason_is_kept() -> None:
    assert classify("# TODO: retry on flake once the server-side fix ships", "retry()") == "keep"


def test_preexisting_comments_not_flagged() -> None:
    before = "def f():\n    # old comment that stays\n    return 1\n"
    after = before
    assert comment_findings(before, after) == []


def test_findings_report_line_numbers() -> None:
    before = "def f():\n    return 1\n"
    after = "def f():\n\n    # y = 2\n    return 1\n"
    findings = comment_findings(before, after)
    assert findings[0].line == 3
