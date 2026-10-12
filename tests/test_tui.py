"""The TUI end to end: a demo run through the real modal screens.

Textual's Pilot drives the app without a terminal, so the flow a user
clicks through by hand — clarification question, patch approval,
verification, grounded report — runs here in CI.
"""

from __future__ import annotations

import asyncio
import sys

import pytest
from textual.widgets import Button, Input, Static

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


def _regions(app: SmbrApp) -> dict[str, tuple[int, int, int, int]]:
    from textual.widgets import Footer

    out: dict[str, tuple[int, int, int, int]] = {}
    targets = [
        ("left", app.query_one("#left")),
        ("events", app.query_one("#events")),
        ("plan", app.query_one("#plan")),
        ("request", app.query_one("#request")),
        ("step", app.query_one("#step")),
        ("footer", app.query_one(Footer)),
    ]
    for name, widget in targets:
        region = widget.region
        out[name] = (region.x, region.y, region.width, region.height)
    return out


def _overlaps(regions: dict[str, tuple[int, int, int, int]]) -> list[str]:
    """Partial overlaps only: a pane containing its children is not a bug."""
    names = list(regions)
    found: list[str] = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = regions[names[i]], regions[names[j]]
            overlap_x = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
            overlap_y = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
            if not (overlap_x and overlap_y):
                continue
            if _contains(a, b) or _contains(b, a):
                continue
            found.append(f"{names[i]} overlaps {names[j]} by {overlap_x}x{overlap_y}")
    return found


def _contains(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ix >= ox and iy >= oy and ix + iw <= ox + ow and iy + ih <= oy + oh


def _log_lines(app: SmbrApp) -> list[str]:
    return list(app.events)


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


@pytest.mark.parametrize("size", [(80, 24), (120, 36), (200, 50)])
def test_nothing_overlaps_at_any_terminal_size(project, size) -> None:
    async def main(app: SmbrApp) -> list[str]:
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            app.set_plan("a deliberately long plan that must wrap instead of spilling")
            app.record("x" * 300)
            await pilot.pause()
            return _overlaps(_regions(app))

    app = SmbrApp()
    assert asyncio.run(main(app)) == []


def test_long_lines_wrap_instead_of_spilling(project) -> None:
    async def main(app: SmbrApp) -> int:
        async with app.run_test(size=(100, 30)) as pilot:
            before = app.query_one("#events").region.width
            app.record("y" * 500)
            await pilot.pause()
            return app.query_one("#events").region.width - before

    app = SmbrApp()
    # the log's width is fixed by the layout; a long line cannot widen it
    assert asyncio.run(main(app)) == 0
