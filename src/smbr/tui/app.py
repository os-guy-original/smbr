"""The TUI: the harness made visible.

What a user needs at a glance is *where the run is*, *what just happened to
it*, and *what is being asked of them*. So the screen is a status line, a
structured transcript, and a request input — and every message carries its
kind: tools are dim, gate results are green/red, questions yellow, refusals
and overrides loud, and the run's final line bold.

Layout is a single stacked column with nothing docked and nothing
overlapping; a geometry test keeps it that way.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Input, RichLog, Static

from smbr.kernel.state import Exit

if TYPE_CHECKING:
    from smbr.agent.loop import SmbrAgent

DEFAULT_PLAN = "waiting for clarification / preflight"

REQUEST_PLACEHOLDER = "describe the task — Enter to run it (q quits)"

#: Message kinds, in descending volume. The kind decides the style, so a
#: refusal never looks like a tool result again.
_KIND_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("refused", ("refus", "blocked", "was not confirmed", "did not apply", "cannot")),
    ("override", ("override",)),
    ("question", ("[ask]",)),
    ("answer", ("[answer]",)),
    ("gate_fail", ("[gate:fail]",)),
    ("gate_pass", ("[gate:pass]",)),
    ("tool", ("[tool]",)),
    ("warn", ("warning", "stuck", "halted", "unavailable")),
    ("result", ("done:", "run finished")),
)

_KIND_STYLES = {
    "plain": "",
    "refused": "bold red",
    "override": "magenta",
    "question": "yellow",
    "answer": "cyan",
    "gate_fail": "red",
    "gate_pass": "green",
    "tool": "dim",
    "warn": "bold yellow",
    "result": "bold green",
}


def classify(message: str) -> str:
    """The visual kind of one harness message."""
    lowered = message.lower()
    for kind, markers in _KIND_RULES:
        if any(marker in lowered for marker in markers):
            return kind
    return "plain"


class SmbrApp(App):
    """SMBR terminal interface."""

    CSS = """
    #status { height: 1; background: $panel; color: $text; padding: 0 1; }
    #panes { height: 1fr; }
    #left { width: 34%; border-right: solid $primary; }
    #step-label { padding: 0 1; color: $text-muted; }
    #step { padding: 0 1; text-style: bold; }
    #plan-label { padding: 0 1; color: $text-muted; }
    #plan { height: 1fr; padding: 0 1; }
    #events { width: 66%; }
    #request { height: 1; border: none; }
    QuestionScreen { align: center middle; }
    #question-dialog {
        width: 80%; height: auto; max-height: 80%;
        border: solid $primary; background: $surface; padding: 1 2;
    }
    #question { padding: 0 0 1 0; }
    ApprovalScreen { align: center middle; }
    #approval-dialog {
        width: 90%; height: 80%;
        border: solid $primary; background: $surface; padding: 1 2;
    }
    #approval-title { height: 1; }
    #diff { height: 1fr; }
    .finding { color: $warning; }
    #approval-hint { dock: bottom; height: 1; background: $panel; }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("q", "quit", "Quit")]

    def __init__(
        self,
        step: str = "intake",
        plan: str = DEFAULT_PLAN,
        request: str | None = None,
        demo: bool = False,
        model: str = "",
    ) -> None:
        super().__init__()
        self.step = step
        self.plan = plan
        self.events: list[str] = []
        self._request = request
        self._demo = demo
        self._busy = False
        self._model = model
        self._started_at: float | None = None
        self._plan_progress = ""

    def compose(self) -> ComposeResult:
        yield Static("", id="status", markup=True)
        with Horizontal(id="panes"):
            with Vertical(id="left"):
                yield Static("Step", id="step-label")
                yield Static(f"Step: {self.step}", id="step")
                yield Static("Plan", id="plan-label")
                yield RichLog(id="plan", markup=False, wrap=True)
            yield RichLog(id="events", markup=True, wrap=True)
        yield Input(placeholder=REQUEST_PLACEHOLDER, id="request")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "SMBR"
        self.sub_title = "Small Model, Big Results"
        self.set_plan(self.plan)
        self.set_step(self.step)
        self._render_status()
        self.set_interval(1.0, self._tick)
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

    # -- surfaces ----------------------------------------------------------

    def record(self, message: str) -> None:
        """Append one harness message, styled by what it means."""
        self.events.append(message)
        style = _KIND_STYLES[classify(message)]
        rendered = message if not style else f"[{style}]{message}[/]"
        self.query_one("#events", RichLog).write(rendered)

    def begin_step(self, step: str) -> None:
        """A new step starts: announce it, and make it the current one."""
        self.set_step(step)
        self.record(f"— {step} —")

    def set_step(self, step: str) -> None:
        self.step = step
        self.query_one("#step", Static).update(f"Step: {step}")
        self._render_status()

    def set_plan(self, plan: str) -> None:
        self.plan = plan
        log = self.query_one("#plan", RichLog)
        log.clear()
        log.write(plan)

    def set_plan_progress(self, current: int, total: int) -> None:
        """Where in the plan the run is, for the status line."""
        self._plan_progress = f" · plan {current}/{total}" if total else ""
        self._render_status()

    def record_gate(self, gate: str, passed: bool, reason: str) -> None:
        status = "PASS" if passed else "FAIL"
        self.record(f"[gate:{status}] {gate} — {reason}")

    def record_tool_call(self, name: str, result: str) -> None:
        self.record(f"[tool] {name} — {result}")

    def _render_status(self) -> None:
        state = "running" if self._busy else "idle"
        clock = ""
        if self._started_at is not None:
            clock = f" · {time.monotonic() - self._started_at:4.0f}s"
        model = self._model or ("demo model" if self._demo else "no model configured")
        self.query_one("#status", Static).update(
            Text.assemble(
                ("SMBR", "b"),
                f" · {self.step}",
                (f" · {state}", "b" if self._busy else "dim"),
                self._plan_progress,
                clock,
                f" · {model}",
                " · q quits",
            )
        )

    def _tick(self) -> None:
        if self._busy:
            self._render_status()

    # -- running a request -------------------------------------------------

    def _start_run(self, request: str) -> None:
        """Build the agent and drive it in a worker thread."""
        from smbr.agent import SmbrAgent, build_decision_router
        from smbr.config import Settings

        if self._busy:
            self.record("[warn] a run is already in progress; wait for it to finish")
            return
        self._busy = True
        self._started_at = time.monotonic()
        settings = Settings(project_root=Path.cwd())
        if self._demo:
            from smbr.agent.demo import DemoClient

            client = DemoClient()
            self._model = "demo"
        else:
            from smbr.agent.client import build_completion_client

            try:
                client = build_completion_client(settings)
            except ValueError as exc:
                self._busy = False
                self._started_at = None
                self.record(f"[refused] cannot start a run: {exc}")
                return
            self._model = settings.model
        router = build_decision_router(settings, client)
        agent = SmbrAgent(
            settings=settings,
            client=client,
            user=self._user_port(),
            router=router,
            on_step=self._on_step,
        )
        self.record(f"run started: {request}")
        self._render_status()
        self.run_agent(agent, request)

    def _on_step(self, step: str) -> None:
        """Step transitions arrive from the worker thread."""
        if step.startswith("edit") or "/" in step:
            self.call_from_thread(self.set_plan_progress, *_parse_progress(step))
        else:
            self.call_from_thread(self.set_plan_progress, 0, 0)
        self.call_from_thread(self.begin_step, step)

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
            self.call_from_thread(self.record, f"[refused] run crashed: {exc}")
            self.call_from_thread(self._finish_run, "halted")
            return
        final = "done" if result.exit is Exit.DONE else result.exit.value
        self.call_from_thread(self.set_step, final)
        overrides = f" · {len(result.overrides)} override(s)" if result.overrides else ""
        self.call_from_thread(self.record, f"run finished: {final} — {result.reason}{overrides}")
        self.call_from_thread(self._finish_run, final)

    def _finish_run(self, _: str) -> None:
        self._busy = False
        self._started_at = None
        self._render_status()


def _parse_progress(step: str) -> tuple[int, int]:
    """`edit (2/3)` → (2, 3); anything else means no plan progress."""
    if "(" not in step:
        return 0, 0
    inside = step.split("(", 1)[1].split(")", 1)[0]
    current, _, total = inside.partition("/")
    try:
        return int(current), int(total)
    except ValueError:
        return 0, 0
