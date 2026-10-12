"""Agent-loop integration: the kernel driven by a scripted local model.

The scripted client answers by schema shape, so one class covers the happy
path, the hygiene-revision path and the symbol-refusal path. No network, no
real model — every model answer is a fixed dict.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from smbr.agent import (
    CliUser,
    RecordingUser,
    SmbrAgent,
    build_decision_router,
)
from smbr.config import Settings
from smbr.decisions.provider import DisabledDecisionProvider
from smbr.kernel.state import Exit
from tests_shared import BUGGY, TEST_FILE, ScriptedClient


@pytest.fixture
def project(tmp_path):
    (tmp_path / "calc.py").write_text(BUGGY, encoding="utf-8")
    (tmp_path / "test_calc.py").write_text(TEST_FILE, encoding="utf-8")
    return tmp_path


def _settings(root: Path) -> Settings:
    return Settings(
        project_root=root,
        test_command=f"{sys.executable} -m pytest -q",
        lint_command=f"{sys.executable} -c pass",
        typecheck_command="",
    )


def _agent(settings: Settings, client, user) -> SmbrAgent:
    router = build_decision_router(settings, client)
    return SmbrAgent(settings=settings, client=client, user=user, router=router)


def test_happy_path_fixes_the_bug_and_verifies(project) -> None:
    user = RecordingUser()
    agent = _agent(_settings(project), ScriptedClient(), user)
    result = agent.run("fix the add function in calc.py")
    assert result.exit is Exit.DONE
    assert "return a + b" in (project / "calc.py").read_text(encoding="utf-8")
    assert any("done:" in m for m in user.messages)


def test_hygiene_revision_strips_the_restating_comment(project) -> None:
    user = RecordingUser()
    agent = _agent(_settings(project), ScriptedClient(with_comment=True), user)
    result = agent.run("fix the add function in calc.py")
    assert result.exit is Exit.DONE
    content = (project / "calc.py").read_text(encoding="utf-8")
    assert "return a + b" in content
    assert "# return a plus b" not in content
    assert any("comment hygiene rejected" in m for m in user.messages)


def test_unconfirmed_symbol_refuses_the_edit(project) -> None:
    user = RecordingUser(answers=["skip this edit"] * 10)
    agent = _agent(_settings(project), ScriptedClient(symbols=("ghost",)), user)
    result = agent.run("fix the add function in calc.py")
    # edit skipped, the bug stays, verify fails, repair loop burns the budget
    assert result.exit is Exit.STUCK
    assert "a - b" in (project / "calc.py").read_text(encoding="utf-8")
    assert any("were not confirmed by symbol lookup" in m for m in user.messages)


def test_model_failure_halts_instead_of_guessing(project) -> None:
    user = RecordingUser()
    agent = _agent(_settings(project), ScriptedClient(boom=True), user)
    result = agent.run("fix the add function in calc.py")
    assert result.exit is Exit.HALTED
    assert any("model unavailable" in m for m in user.messages)


def test_disabled_layer_delegates_to_the_user(project) -> None:
    settings = _settings(project)
    settings.decision_layer_enabled = False
    router = build_decision_router(settings, ScriptedClient())
    assert isinstance(router.provider, DisabledDecisionProvider)


def test_user_rejection_skips_the_patch(project) -> None:
    user = RecordingUser(approve=False)
    agent = _agent(_settings(project), ScriptedClient(), user)
    agent.run("fix the add function in calc.py")
    assert "a - b" in (project / "calc.py").read_text(encoding="utf-8")
    assert any("user rejected" in m for m in user.messages)


def test_no_checks_configured_halts_in_preflight(project) -> None:
    settings = _settings(project)
    settings.test_command = ""
    settings.lint_command = ""
    agent = _agent(settings, ScriptedClient(), RecordingUser())
    result = agent.run("fix the add function in calc.py")
    # the manifest declares test_runner and linter; with no command configured
    # both are unhealthy tools, so preflight halts with the harness warning
    assert result.exit is Exit.HALTED
    assert "preflight found missing capabilities" in result.reason


def test_cli_user_prompts_and_approves(project) -> None:
    user = CliUser()
    assert callable(user.ask) and callable(user.approve_patch)
