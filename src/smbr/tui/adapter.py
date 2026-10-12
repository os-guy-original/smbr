"""TUI port: clarification questions and patch approval as modal screens.

The agent runs in a worker thread (``SmbrApp.run_agent``); every interrupt
crosses to the UI thread through ``call_from_thread`` and blocks on a future
the screen resolves. Harness messages (gate results, tool calls, warnings)
land in the live event log.

Both screens are keyboard-first (the decision they ask for is a keypress)
and fully scrollable, because a real diff does not fit on one screen.
"""

from __future__ import annotations

from concurrent.futures import Future
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Static

from smbr.tui.app import SmbrApp


def _styled_diff(diff: str) -> Text:
    """Color a unified diff: additions green, removals red, hunks dim."""
    text = Text()
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            text.append(line + "\n", "bold")
        elif line.startswith("+"):
            text.append(line + "\n", "green")
        elif line.startswith("-"):
            text.append(line + "\n", "red")
        elif line.startswith("@@"):
            text.append(line + "\n", "cyan")
        else:
            text.append(line + "\n", "dim")
    return text


def _diff_stats(diff: str) -> str:
    lines = diff.splitlines()
    added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    return f"+{added} -{removed}"


class QuestionScreen(ModalScreen[str]):
    """Multiple choice with the options the model proposed."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "quit", "Cancel")]

    def __init__(self, question: str, options: list[str]) -> None:
        super().__init__()
        self.question = question
        self.options = options

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self.question, id="question"),
            *[Button(f"{i}. {option}", id=f"opt-{i}") for i, option in enumerate(self.options)],
            id="question-dialog",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#opt-0", Button).focus()

    def on_key(self, event) -> None:
        # number keys pick an option directly: 1..n
        if event.character and event.character.isdigit():
            index = int(event.character) - 1
            if 0 <= index < len(self.options):
                event.stop()
                event.prevent_default()
                self.dismiss(self.options[index])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        index = int(event.button.id.removeprefix("opt-"))
        self.dismiss(self.options[index])


class ApprovalScreen(ModalScreen[bool]):
    """Diff approval before anything touches the working tree."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("a", "approve", "Approve"),
        ("r", "reject", "Reject"),
        ("escape", "reject", "Reject"),
    ]

    def __init__(self, path: str, diff: str, findings: list[str]) -> None:
        super().__init__()
        self.path = path
        self.diff = diff
        self.findings = findings

    def compose(self) -> ComposeResult:
        stats = _diff_stats(self.diff)
        yield VerticalScroll(
            Static(
                Text.assemble(
                    ("Apply patch to ", "b"),
                    (self.path, "b cyan"),
                    (f"  ({stats})", "dim"),
                ),
                id="approval-title",
            ),
            Static(_styled_diff(self.diff), id="diff", markup=False),
            *[
                Static(f"[comment hygiene] {finding}", classes="finding")
                for finding in self.findings
            ],
            id="approval-dialog",
        )
        yield Static(
            Text.assemble(
                ("a", "b green"),
                " approve · ",
                ("r", "b red"),
                " reject · scroll with the mouse or arrow keys",
            ),
            id="approval-hint",
        )
        yield Footer()

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_reject(self) -> None:
        self.dismiss(False)


class TuiUser:
    """UserPort backed by the running app's screens and event log."""

    def __init__(self, app: SmbrApp) -> None:
        self.app = app

    def ask(self, question: str, options: list[str]) -> str:
        opts = " | ".join(options)
        self.app.call_from_thread(self.app.record, f"[ask] {question} ({opts})")
        future: Future[str] = Future()
        self.app.call_from_thread(
            self.app.push_screen, QuestionScreen(question, options), future.set_result
        )
        answer = future.result()
        self.app.call_from_thread(self.app.record, f"[answer] {answer}")
        return answer

    def notify(self, message: str) -> None:
        self.app.call_from_thread(self.app.record, message)

    def approve_patch(self, path: str, diff: str, findings: list[str]) -> bool:
        self.app.call_from_thread(self.app.record, f"[ask] approve the patch for {path}?")
        future: Future[bool] = Future()
        self.app.call_from_thread(
            self.app.push_screen, ApprovalScreen(path, diff, findings), future.set_result
        )
        approved = future.result()
        self.app.call_from_thread(
            self.app.record, f"[answer] {'approved' if approved else 'rejected'}: {path}"
        )
        return approved
