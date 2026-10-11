"""The TUI: the harness made visible.

The user always sees which step the agent is in, what it was allowed to do,
and what stopped it. This is the v1 skeleton — layout and live surfaces are in
place; the model-driven panels arrive with the Phase 1 model backend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Log, Static

if TYPE_CHECKING:
    from smbr.agent.loop import SmbrAgent
    from smbr.kernel.state import Exit

DEFAULT_PLAN = "waiting for clarification / preflight"


class SmbrApp(App):
    """SMBR terminal interface."""

    CSS = """
    #left { width: 40%; border-right: solid $primary; }
    #step { padding: 1; text-style: bold; }
    #plan { padding: 1; }
    #events { width: 60%; }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("q", "quit", "Quit")]

    def __init__(self, step: str = "intake", plan: str = DEFAULT_PLAN) -> None:
        super().__init__()
        self.step = step
        self.plan = plan

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="left"):
                yield Static(f"Step: {self.step}", id="step")
                yield Static(f"Plan: {self.plan}", id="plan")
            yield Log(id="events")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "SMBR"
        self.sub_title = "Small Model, Big Results"
        self.record("harness started")

    def record(self, message: str) -> None:
        """Append to the live event log (tool calls, gate results)."""
        self.query_one("#events", Log).write_line(message)

    def set_step(self, step: str) -> None:
        self.step = step
        self.query_one("#step", Static).update(f"Step: {step}")

    def set_plan(self, plan: str) -> None:
        self.plan = plan
        self.query_one("#plan", Static).update(f"Plan: {plan}")

    def record_gate(self, gate: str, passed: bool, reason: str) -> None:
        status = "PASS" if passed else "FAIL"
        self.record(f"[gate:{status}] {gate} — {reason}")

    def record_tool_call(self, name: str, result: str) -> None:
        self.record(f"[tool] {name} — {result}")

    def ask_user(self, question: str, options: list[str]) -> None:
        """clarification questions surface here, with options and a default"""
        opts = " | ".join(options)
        self.record(f"[ask] {question} ({opts})")

    @work(thread=True, name="smbr-agent")
    def run_agent(self, agent: SmbrAgent, request: str) -> None:
        """Drive one request in a worker thread; the UI keeps pumping."""
        result = agent.run(request)
        final = "done" if result.exit is Exit.DONE else result.exit.value
        self.call_from_thread(self.set_step, final)
        self.call_from_thread(self.record, f"run finished: {final} - {result.reason}")
