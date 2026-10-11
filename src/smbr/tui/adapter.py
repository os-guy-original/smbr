"""TUI port: clarification questions and patch approval as modal screens.

The agent runs in a worker thread (``SmbrApp.run_agent``); every interrupt
crosses to the UI thread through ``call_from_thread`` and blocks on a future
the screen resolves. Harness messages (gate results, tool calls, warnings)
land in the live event log.
"""

from __future__ import annotations

from concurrent.futures import Future

from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from smbr.tui.app import SmbrApp


class QuestionScreen(ModalScreen[str]):
    """Multiple choice with the options the model proposed."""

    def __init__(self, question: str, options: list[str]) -> None:
        super().__init__()
        self.question = question
        self.options = options

    def compose(self):
        yield Vertical(
            Static(self.question, id="question"),
            *[Button(option, id=f"opt-{i}") for i, option in enumerate(self.options)],
            id="question-dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#opt-0", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        index = int(event.button.id.removeprefix("opt-"))
        self.dismiss(self.options[index])


class ApprovalScreen(ModalScreen[bool]):
    """Diff approval before anything touches the working tree."""

    def __init__(self, path: str, diff: str, findings: list[str]) -> None:
        super().__init__()
        self.path = path
        self.diff = diff
        self.findings = findings

    def compose(self):
        hygiene = "\n".join(self.findings) or "no hygiene findings"
        yield Vertical(
            Static(f"Apply patch to {self.path}?\n\n{self.diff}\n\nComment hygiene: {hygiene}"),
            Horizontal(
                Button("Approve", id="approve", variant="success"),
                Button("Reject", id="reject", variant="error"),
            ),
            id="approval-dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "approve")


class TuiUser:
    """UserPort backed by the running app's screens and event log."""

    def __init__(self, app: SmbrApp) -> None:
        self.app = app

    def ask(self, question: str, options: list[str]) -> str:
        future: Future[str] = Future()
        self.app.call_from_thread(
            self.app.push_screen, QuestionScreen(question, options), future.set_result
        )
        return future.result()

    def notify(self, message: str) -> None:
        self.app.call_from_thread(self.app.record, message)

    def approve_patch(self, path: str, diff: str, findings: list[str]) -> bool:
        future: Future[bool] = Future()
        self.app.call_from_thread(
            self.app.push_screen, ApprovalScreen(path, diff, findings), future.set_result
        )
        return future.result()
