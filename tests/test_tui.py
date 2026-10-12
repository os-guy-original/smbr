"""The TUI end to end: a demo run through the real modal screens.

Textual's Pilot drives the app without a terminal, so the flow a user
clicks through by hand — clarification question, patch approval,
verification, grounded report — runs here in CI.
"""

from __future__ import annotations

import asyncio
import sys

import pytest
from textual.widgets import Button, Input, Log, Static

from smbr.agent.demo import DEMO_FILE
from smbr.tui import ApprovalScreen, QuestionScreen, SmbrApp


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # the demo run verifies with the configured checks; keep them trivial and
    # fast (env vars, because pydantic holds defaults in model_fields)
    monkeypatch.setenv("SMBR_TEST_COMMAND", f"{sys.executable} -c pass")
    monkeypatch.setenv("SMBR_LINT_COMMAND", f"{sys.executable} -c pass")
    monkeypatch.setenv("SMBR_TYPECHECK_COMMAND", "")
    return tmp_path


def _log_lines(app: SmbrApp) -> list[str]:
    return [str(line) for line in app.query_one("#events", Log).lines]


async def _drive(app: SmbrApp, pilot) -> None:
    """Answer every modal the run raises, in order."""
    for _ in range(20):  # bounded: clarification, then approval
        await pilot.pause()
        if isinstance(app.screen, QuestionScreen):
            # the clarification question: pick the first option
            app.screen.query_one("#opt-0", Button).press()
            await pilot.pause()
        elif isinstance(app.screen, ApprovalScreen):
            app.screen.query_one("#approve", Button).press()
            await pilot.pause()
    await pilot.pause()


def test_demo_run_flows_through_every_screen(project) -> None:
    async def main(app: SmbrApp) -> tuple[str, list[str]]:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.query_one("#request", Input), Input)
            await _drive(app, pilot)
            return str(app.query_one("#step", Static).content), _log_lines(app)

    app = SmbrApp(request="leave a demo note", demo=True)
    step, lines = asyncio.run(main(app))

    # the clarification question was asked, answered, and the patch approved
    assert any("[ask]" in line and "scope" in line for line in lines)
    assert any("[answer]" in line for line in lines)
    assert any("[answer] approved: smbr-demo-note.txt" in line for line in lines)
    assert any("run started" in line for line in lines)
    assert any("patch_apply smbr-demo-note.txt -> diff applied" in line for line in lines)
    assert step == "Step: done"
    # the approved patch really landed in the project
    assert (project / DEMO_FILE).exists()


def test_the_question_screen_dismisses_with_the_chosen_option(project) -> None:
    async def main(app: SmbrApp) -> str:
        from concurrent.futures import Future

        async with app.run_test() as pilot:
            outcome: Future[str] = Future()
            app.push_screen(QuestionScreen("pick one", ["a", "b"]), outcome.set_result)
            await pilot.pause()
            app.screen.query_one("#opt-1", Button).press()
            await pilot.pause()
            return outcome.result()

    app = SmbrApp()
    assert asyncio.run(main(app)) == "b"


def test_the_approval_screen_can_reject(project) -> None:
    async def main(app: SmbrApp) -> bool:
        from concurrent.futures import Future

        async with app.run_test() as pilot:
            outcome: Future[bool] = Future()
            app.push_screen(ApprovalScreen("x.py", "--- a/x.py", []), outcome.set_result)
            await pilot.pause()
            app.screen.query_one("#reject", Button).press()
            await pilot.pause()
            return outcome.result()

    app = SmbrApp()
    assert asyncio.run(main(app)) is False


def test_typing_a_request_starts_a_run(project) -> None:
    async def main(app: SmbrApp) -> list[str]:
        async with app.run_test() as pilot:
            app.query_one("#request", Input).value = "leave a demo note"
            await pilot.pause()
            await pilot.press("enter")
            await _drive(app, pilot)
            return _log_lines(app)

    app = SmbrApp(demo=True)
    lines = asyncio.run(main(app))
    assert any("run started: leave a demo note" in line for line in lines)
    assert (project / DEMO_FILE).exists()


def test_a_second_run_while_one_is_going_is_refused(project) -> None:
    async def main(app: SmbrApp) -> list[str]:
        async with app.run_test() as pilot:
            app._busy = True  # simulate a run in flight
            app._start_run("another one")
            await pilot.pause()
            return _log_lines(app)

    app = SmbrApp(demo=True)
    lines = asyncio.run(main(app))
    assert any("already in progress" in line for line in lines)
