"""TUI smoke: the harness surfaces must exist and update."""

from __future__ import annotations

import asyncio

from textual.widgets import Static

from smbr.tui import SmbrApp


def test_app_smoke() -> None:
    async def main(app: SmbrApp) -> str:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#step", Static).content == "Step: intake"
            app.record_gate("read_before_edit", False, "file not read")
            app.set_step("edit")
            app.set_plan("validate signup form")
            await pilot.pause()
            return str(app.query_one("#step", Static).content)

    app = SmbrApp()
    assert asyncio.run(main(app)) == "Step: edit"
