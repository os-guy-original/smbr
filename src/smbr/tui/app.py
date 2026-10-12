"""The TUI: the harness made visible.

The user always sees which step the agent is in, what it was allowed to do,
and what stopped it. Type a request in the bottom input to drive a run;
clarification questions and patch approvals arrive as modal screens, and
harness messages land in the live event log.

Layout rules: nothing docks and nothing overlaps. Header, the two panes,
the request input and the footer stack in one column, the panes take the
remaining height, and both log surfaces wrap rather than spill.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static

from smbr.kernel.state import Exit

if TYPE_CHECKING:
    from smbr.agent.loop import SmbrAgent

DEFAULT_PLAN = "waiting for clarification / preflight"

REQUEST_PLACEHOLDER = "describe the task — Enter to run it (q quits)"


class SmbrApp(App):
    """SMBR terminal interface."""

    CSS = """
    #panes { height: 1fr; }
    #left { width: 40%; border-right: solid $primary; }
    #step { padding: 0 1; text-style: bold; }
    #plan-label { padding: 0 1; color: $text-muted; }
    #plan { height: 1fr; padding: 0 1; }
    #events { width: 60%; }
    #request { height: 3; }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("q", "quit", "Quit")]

    def __init__(
        self,
        step: str = "intake",
        plan: str = DEFAULT_PLAN,
        request: str | None = None,
        demo: bool = False,
    ) -> None:
        super().__init__()
        self.step = step
        self.plan = plan
        self.events: list[str] = []
        self._request = request
        self._demo = demo
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="panes"):
            with Vertical(id="left"):
                yield Static(f"Step: {self.step}", id="step")
                yield Static("Plan", id="plan-label")
                yield RichLog(id="plan", markup=False, wrap=True)
            yield RichLog(id="events", markup=False, wrap=True)
        yield Input(placeholder=REQUEST_PLACEHOLDER, id="request")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "SMBR"
        self.sub_title = "Small Model, Big Results"
        self.set_plan(self.plan)
        self.record("harness started")
        if self._demo:
            self.record("demo mode: no model server needed")
        if self._request:
            self._start_run(self._request)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        request = event.value.strip()
        event.input.value = ""
        if request:
            self._start_run(request)

    def record(self, message: str) -> None:
        """Append to the live event log (tool calls, gate results)."""
        self.events.append(message)
        self.query_one("#events", RichLog).write(message)

    def set_step(self, step: str) -> None:
        self.step = step
        self.query_one("#step", Static).update(f"Step: {step}")

    def set_plan(self, plan: str) -> None:
        self.plan = plan
        log = self.query_one("#plan", RichLog)
        log.clear()
        log.write(plan)

    def record_gate(self, gate: str, passed: bool, reason: str) -> None:
        status = "PASS" if passed else "FAIL"
        self.record(f"[gate:{status}] {gate} — {reason}")

    def record_tool_call(self, name: str, result: str) -> None:
        self.record(f"[tool] {name} — {result}")

    def ask_user(self, question: str, options: list[str]) -> None:
        """clarification questions surface here, with options and a default"""
        opts = " | ".join(options)
        self.record(f"[ask] {question} ({opts})")

    # -- running a request -------------------------------------------------

    def _start_run(self, request: str) -> None:
        """Build the agent and drive it in a worker thread."""
        from smbr.agent import SmbrAgent, build_decision_router
        from smbr.config import Settings

        if self._busy:
            self.record("a run is already in progress; wait for it to finish")
            return
        self._busy = True
        settings = Settings(project_root=Path.cwd())
        if self._demo:
            from smbr.agent.demo import DemoClient

            client = DemoClient()
        else:
            from smbr.agent.client import build_completion_client

            try:
                client = build_completion_client(settings)
            except ValueError as exc:
                self._busy = False
                self.record(f"cannot start a run: {exc}")
                return
        router = build_decision_router(settings, client)
        agent = SmbrAgent(settings=settings, client=client, user=self._user_port(), router=router)
        self.set_step("intake")
        self.record(f"run started: {request}")
        self.run_agent(agent, request)

    def _user_port(self):
        """The modal-screen port: questions and approvals raise real screens."""
        from smbr.tui.adapter import TuiUser

        return TuiUser(self)

    @work(thread=True, name="smbr-agent")
    def run_agent(self, agent: SmbrAgent, request: str) -> None:
        """Drive one request in a worker thread; the UI keeps pumping."""
        try:
            result = agent.run(request)
        except Exception as exc:  # a crashed worker must not kill the UI
            self.call_from_thread(self.record, f"run crashed: {exc}")
            self.call_from_thread(self._finish_run, "halted")
            return
        final = "done" if result.exit is Exit.DONE else result.exit.value
        self.call_from_thread(self.set_step, final)
        self.call_from_thread(self.record, f"run finished: {final} - {result.reason}")
        self.call_from_thread(self._finish_run, final)

    def _finish_run(self, _: str) -> None:
        self._busy = False
