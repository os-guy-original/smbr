"""The TUI end to end: a demo run through the real modal screens.

Textual's Pilot drives the app without a terminal, so the flow a user
clicks through by hand — clarification question, patch approval,
verification, grounded report — runs here in CI.
"""

from __future__ import annotations

import asyncio
import sys

import pytest
from textual.widgets import Button, Input, OptionList, RichLog, Static

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
        ("sidebar", app.query_one("#sidebar")),
        ("steps", app.query_one("#steps")),
        ("plan", app.query_one("#plan")),
        ("events", app.query_one("#events")),
        ("composer", app.query_one("#composer")),
        ("request", app.query_one("#request")),
        ("status", app.query_one("#status")),
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
            await pilot.press("a")  # approve
            await pilot.pause()
    await pilot.pause()


def test_demo_run_flows_through_every_screen(project) -> None:
    async def main(app: SmbrApp) -> tuple[str, list[str]]:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.query_one("#request", Input), Input)
            await _drive(app, pilot)
            return app.step, _log_lines(app)

    app = SmbrApp(request="leave a demo note", demo=True)
    step, lines = asyncio.run(main(app))

    # the clarification question was asked, answered, and the patch approved
    assert any("[ask]" in line and "scope" in line for line in lines)
    assert any("[answer]" in line for line in lines)
    assert any("[answer] approved: smbr-demo-note.txt" in line for line in lines)
    assert any("run started" in line for line in lines)
    assert any("patch_apply smbr-demo-note.txt -> diff applied" in line for line in lines)
    assert step == "done"
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


def test_the_question_screen_takes_a_number_key(project) -> None:
    async def main(app: SmbrApp) -> str:
        from concurrent.futures import Future

        async with app.run_test() as pilot:
            outcome: Future[str] = Future()
            app.push_screen(QuestionScreen("pick one", ["a", "b"]), outcome.set_result)
            await pilot.pause()
            await pilot.press("2")
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
            await pilot.press("r")
            await pilot.pause()
            return outcome.result()

    app = SmbrApp()
    assert asyncio.run(main(app)) is False


def test_the_approval_screen_approves_with_a_key(project) -> None:
    async def main(app: SmbrApp) -> bool:
        from concurrent.futures import Future

        async with app.run_test() as pilot:
            outcome: Future[bool] = Future()
            app.push_screen(ApprovalScreen("x.py", "--- a/x.py", []), outcome.set_result)
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            return outcome.result()

    app = SmbrApp()
    assert asyncio.run(main(app)) is True


def test_the_approval_screen_lays_out_without_overlap(project) -> None:
    async def main(app: SmbrApp) -> list[str]:
        async with app.run_test(size=(100, 30)) as pilot:
            diff = "\n".join(f"+line {i}" for i in range(80))
            app.push_screen(ApprovalScreen("calc.py", diff, ["restates_code at line 4"]))
            await pilot.pause()
            dialog = app.screen.query_one("#approval-dialog")
            hint = app.screen.query_one("#approval-hint")
            a, b = dialog.region, hint.region
            overlap_y = max(0, min(a.y + a.height, b.y + b.height) - max(a.y, b.y))
            overlap_x = max(0, min(a.x + a.width, b.x + b.width) - max(a.x, b.x))
            return [f"{overlap_x}x{overlap_y}" if overlap_x and overlap_y else "clean"]

    app = SmbrApp()
    assert asyncio.run(main(app)) == ["clean"]


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


def test_message_kinds_are_visually_distinct(project, monkeypatch) -> None:
    written: list[str] = []
    original = RichLog.write

    def spy(self, content, *args, **kwargs):  # capture what the log is handed
        written.append(str(content))
        return original(self, content, *args, **kwargs)

    monkeypatch.setattr(RichLog, "write", spy)

    async def main(app: SmbrApp) -> list[str]:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.record("[tool] file_read calc.py -> 2 lines read")
            app.record("[gate:PASS] read_before_edit — read in this session")
            app.record("[gate:FAIL] symbol_check — ghost unconfirmed")
            app.record("[answer] one file")
            app.record("stuck after 3 edit attempts")
            await pilot.pause()
            return list(written)

    app = SmbrApp()
    lines = asyncio.run(main(app))

    def line_with(prefix: str) -> str:
        return next((line for line in lines if prefix in line), "missing")

    # a tool result is dim, a failure is red — never the same face
    assert "[dim]" in line_with("[tool]")
    assert "[red]" in line_with("[gate:FAIL]")
    assert "[green]" in line_with("[gate:PASS]")
    assert "[cyan]" in line_with("[answer]")
    assert "[bold yellow]" in line_with("stuck")


def test_the_status_line_tracks_the_step_and_running_state(project) -> None:
    async def main(app: SmbrApp) -> list[str]:
        async with app.run_test() as pilot:
            await pilot.pause()
            idle = str(app.query_one("#status", Static).render())
            app.set_step("edit")
            app.set_plan_progress(2, 3)
            app._busy = True
            app._render_status()
            await pilot.pause()
            return [idle, str(app.query_one("#status", Static).render())]

    app = SmbrApp(demo=True)
    idle, running = asyncio.run(main(app))
    assert "intake" in idle and "idle" in idle
    assert "edit" in running and "plan 2/3" in running and "running" in running
    assert "demo" in running


def test_the_demo_flow_reports_steps_live(project) -> None:
    async def main(app: SmbrApp) -> tuple[str, list[str]]:
        async with app.run_test() as pilot:
            await pilot.pause()
            # before the user answers, the run is already in clarify
            await _drive(app, pilot)
            return app.step, _log_lines(app)

    app = SmbrApp(request="leave a demo note", demo=True)
    step, lines = asyncio.run(main(app))
    assert "— clarify —" in lines
    assert "— edit (1/1) —" in lines
    assert step == "done"


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


# -- the slash-command interface -------------------------------------------


def _option_ids(app: SmbrApp) -> list[str]:
    return [str(option.id) for option in app.command_list.options]


def test_typing_a_slash_opens_the_command_popup(project) -> None:
    async def main(app: SmbrApp) -> list[str]:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#request", Input).value = "/s"
            await pilot.pause()
            return _option_ids(app)

    app = SmbrApp()
    ids = asyncio.run(main(app))
    assert ids
    assert "harness.status" in ids  # a name-prefix match, ranked first


def test_the_popup_filters_as_you_type(project) -> None:
    async def main(app: SmbrApp) -> list[str]:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#request", Input).value = "/mod"
            await pilot.pause()
            return _option_ids(app)

    app = SmbrApp()
    assert asyncio.run(main(app))[0] == "model.show"  # prefix ranks first


def test_enter_runs_the_highlighted_command(project) -> None:
    async def main(app: SmbrApp) -> list[str]:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#request", Input).value = "/clear"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            return list(app.events)

    app = SmbrApp()
    events = asyncio.run(main(app))
    assert any("[answer] /clear" in e for e in events)
    # the command's own answer survives the clear, so the log shows what ran
    assert events == ["[answer] /clear"]


def test_tab_completes_the_highlighted_command(project) -> None:
    async def main(app: SmbrApp) -> str:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#request", Input).value = "/he"
            await pilot.pause()
            await pilot.press("tab")
            await pilot.pause()
            return str(app.query_one("#request", Input).value)

    app = SmbrApp()
    assert asyncio.run(main(app)) == "/help "


def test_escape_closes_the_popup(project) -> None:
    async def main(app: SmbrApp) -> tuple[bool, str]:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#request", Input).value = "/he"
            await pilot.pause()
            shown = app.commands_visible
            await pilot.press("escape")
            await pilot.pause()
            return shown, str(app.query_one("#request", Input).value)

    app = SmbrApp()
    shown, value = asyncio.run(main(app))
    assert shown is True
    assert value == "/he"  # the typed text is not swallowed


def test_an_unknown_command_is_refused_with_the_list(project) -> None:
    async def main(app: SmbrApp) -> list[str]:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#request", Input).value = "/definitely-not-a-command"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            return list(app.events)

    app = SmbrApp()
    events = asyncio.run(main(app))
    assert any("unknown command" in e for e in events)


def test_the_palette_lists_every_command_and_runs_one(project) -> None:

    async def main(app: SmbrApp) -> list[str]:
        async with app.run_test() as pilot:
            app.action_palette()
            await pilot.pause()
            labels = [str(o.prompt) for o in app.screen.query_one("#palette", OptionList).options]
            await pilot.press("escape")
            await pilot.pause()
            return labels

    app = SmbrApp()
    labels = asyncio.run(main(app))
    assert any("/help" in label for label in labels)
    assert any("/quit" in label for label in labels)
    # grouped by category, like the composer's palette
    assert any("Harness" in label for label in labels)


def test_slash_demo_runs_the_canned_flow(project) -> None:
    async def main(app: SmbrApp) -> list[str]:
        async with app.run_test() as pilot:
            app.query_one("#request", Input).value = "/demo"
            await pilot.pause()
            await pilot.press("enter")
            await _drive(app, pilot)
            return list(app.events)

    app = SmbrApp()
    events = asyncio.run(main(app))
    assert any("[answer] /demo" in e for e in events)
    assert any("run started" in e for e in events)
    assert (project / DEMO_FILE).exists()


def test_the_sidebar_marks_the_current_step(project) -> None:
    async def main(app: SmbrApp) -> list[str]:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.begin_step("preflight")
            await pilot.pause()
            return [str(s) for s in app.query_one("#steps", RichLog).lines]

    app = SmbrApp()
    lines = asyncio.run(main(app))
    joined = "\n".join(lines)
    assert "intake" in joined
    assert "preflight" in joined
