"""Agent-loop features: the tool-call channel, the decision-layer
hygiene judgment, and the stuck exit's rollback offer."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from smbr.agent import RecordingUser, SmbrAgent
from smbr.config import Settings
from smbr.decisions.provider import Decision, DecisionRouter
from smbr.kernel.state import Exit
from smbr.tools.registry import registry_from_settings
from tests_shared import BUGGY, MULTIPLY, TEST_FILE, ScriptedClient

ECHO_CALL = {"tool": "echo", "arguments": {"text": "hi"}}


class FixedBooleanProvider:
    """A decision provider with one answer, for the hygiene judgment."""

    name = "fixed"

    def __init__(self, value: bool, confidence: float) -> None:
        self._value = value
        self._confidence = confidence
        self.questions: list[str] = []

    def choice(self, question: str, options: tuple[str, ...]) -> Decision:
        return Decision(options[0] if options else "", 0.0, self.name)

    def score(self, subject: str, question: str) -> Decision:
        return Decision(0.0, 0.0, self.name)

    def boolean(self, question: str) -> Decision:
        self.questions.append(question)
        return Decision(self._value, self._confidence, self.name)


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


def _mcp_project(project, fake_server) -> Settings:
    """A project with one enabled MCP server offering the echo tool."""
    mcp_dir = project / ".smbr"
    mcp_dir.mkdir()
    (mcp_dir / "mcp.json").write_text(
        json.dumps(
            {"mcpServers": {"fake": {"command": sys.executable, "args": [str(fake_server)]}}}
        ),
        encoding="utf-8",
    )
    return _settings(project)


# -- the tool-call channel --------------------------------------------------


def test_exposed_tool_call_runs_and_is_recorded(project) -> None:
    calls = [{"tool": "file_read", "arguments": {"path": "calc.py"}}]
    user = RecordingUser()
    agent = SmbrAgent(
        settings=_settings(project),
        client=ScriptedClient(tool_calls=calls, claims={"claims": []}),
        user=user,
    )
    result = agent.run("fix the add function in calc.py")
    assert result.exit is Exit.DONE
    assert any("file_read ->" in m for m in user.messages)
    assert any(
        key.startswith("tool-") and "file_read" in key for key in agent.kernel.session.tool_results
    )


def test_undeclared_capability_blocks_the_call(project) -> None:
    calls = [{"tool": "symbol_lookup", "arguments": {"path": "calc.py", "name": "add"}}]
    requires = [
        {"capability": "file_read", "why": "read calc.py"},
        {"capability": "patch_apply", "why": "apply the fix"},
        {"capability": "test_runner", "why": "verify"},
        {"capability": "linter", "why": "lint"},
    ]
    user = RecordingUser()
    agent = SmbrAgent(
        settings=_settings(project),
        client=ScriptedClient(tool_calls=calls, requires=requires),
        user=user,
    )
    agent.run("fix the add function in calc.py")
    assert any("was not declared" in m for m in user.messages)
    assert not any("symbol_lookup ->" in m for m in user.messages)


def test_tool_outside_the_step_is_blocked(project) -> None:
    calls = [{"tool": "test_runner", "arguments": {}}]
    user = RecordingUser()
    agent = SmbrAgent(
        settings=_settings(project),
        client=ScriptedClient(tool_calls=calls),
        user=user,
    )
    agent.run("fix the add function in calc.py")
    assert any("not exposed at this step" in m for m in user.messages)


def test_mcp_tool_calls_ride_the_same_channel(project, fake_server) -> None:
    settings = _mcp_project(project, fake_server)
    user = RecordingUser()
    agent = SmbrAgent(
        settings=settings,
        client=ScriptedClient(tool_calls=[ECHO_CALL], mcp=True, claims={"claims": []}),
        user=user,
        registry=registry_from_settings(settings),
    )
    result = agent.run("fix the add function in calc.py")
    assert result.exit is Exit.DONE
    assert any("echo -> echo: hi" in m for m in user.messages)


def test_mcp_tool_without_declaring_mcp_is_blocked(project, fake_server) -> None:
    settings = _mcp_project(project, fake_server)
    user = RecordingUser()
    agent = SmbrAgent(
        settings=settings,
        client=ScriptedClient(tool_calls=[ECHO_CALL], mcp=False, claims={"claims": []}),
        user=user,
        registry=registry_from_settings(settings),
    )
    agent.run("fix the add function in calc.py")
    assert any("was not declared" in m for m in user.messages)
    assert not any("echo -> echo: hi" in m for m in user.messages)


# -- the stuck exit ---------------------------------------------------------


def test_stuck_run_reports_what_it_tried(project) -> None:
    user = RecordingUser(answers=["skip this edit"] * 10)
    agent = SmbrAgent(
        settings=_settings(project), client=ScriptedClient(symbols=("ghost",)), user=user
    )
    result = agent.run("fix the add function in calc.py")
    assert result.exit is Exit.STUCK
    stuck = [m for m in user.messages if m.startswith("stuck after")]
    assert stuck
    assert "tried:" in stuck[0]
    assert "test_runner" in stuck[0]


def test_stuck_run_rolls_back_when_the_user_says_so(project) -> None:
    user = RecordingUser(answers=["roll back"])
    agent = SmbrAgent(
        settings=_settings(project), client=ScriptedClient(target=MULTIPLY), user=user
    )
    result = agent.run("fix the add function in calc.py")
    assert result.exit is Exit.STUCK
    assert (project / "calc.py").read_text(encoding="utf-8") == BUGGY
    assert any("rolled back 1 file" in m for m in user.messages)


def test_stuck_run_keeps_changes_when_the_user_says_so(project) -> None:
    user = RecordingUser(answers=["keep the changes"])
    agent = SmbrAgent(
        settings=_settings(project), client=ScriptedClient(target=MULTIPLY), user=user
    )
    result = agent.run("fix the add function in calc.py")
    assert result.exit is Exit.STUCK
    assert (project / "calc.py").read_text(encoding="utf-8") == MULTIPLY


# -- comment hygiene, judged by the decision layer ---------------------------


def test_decision_layer_overrules_the_restating_heuristic(project) -> None:
    provider = FixedBooleanProvider(False, 0.9)
    agent = SmbrAgent(
        settings=_settings(project),
        client=ScriptedClient(with_comment=True),
        user=RecordingUser(),
        router=DecisionRouter(provider),
    )
    result = agent.run("fix the add function in calc.py")
    assert result.exit is Exit.DONE
    content = (project / "calc.py").read_text(encoding="utf-8")
    assert "# return a plus b" in content
    assert not any("comment hygiene rejected" in m for m in agent.user.messages)
    assert provider.questions  # the judgment really went through the layer


def test_low_confidence_keeps_the_heuristic(project) -> None:
    provider = FixedBooleanProvider(False, 0.1)
    agent = SmbrAgent(
        settings=_settings(project),
        client=ScriptedClient(with_comment=True),
        user=RecordingUser(),
        router=DecisionRouter(provider),
    )
    result = agent.run("fix the add function in calc.py")
    assert result.exit is Exit.DONE
    content = (project / "calc.py").read_text(encoding="utf-8")
    assert "# return a plus b" not in content
    assert any("comment hygiene rejected" in m for m in agent.user.messages)


def test_no_router_keeps_the_heuristic(project) -> None:
    agent = SmbrAgent(
        settings=_settings(project),
        client=ScriptedClient(with_comment=True),
        user=RecordingUser(),
    )
    result = agent.run("fix the add function in calc.py")
    assert result.exit is Exit.DONE
    content = (project / "calc.py").read_text(encoding="utf-8")
    assert "# return a plus b" not in content
