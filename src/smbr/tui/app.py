"""The TUI: the harness made visible, laid out like a modern agent interface.

The screen answers three questions at a glance — *where is the run*, *what
just happened to it*, *what is being asked of me*:

- **Sidebar** — the kernel's steps with their state, and the live plan.
- **Transcript** — every harness message, styled by what it means.
- **Composer** — a bordered input. ``/`` opens the command popup (filtered,
  arrow-navigable, Tab-completable); Ctrl+P opens the full palette.
- **Status line** — model, project, step, and the keys that do things.

Layout is a single stacked column with nothing docked and nothing
overlapping; geometry tests keep it that way.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from smbr.kernel.state import Exit, Step
from smbr.tui.commands import COMMANDS, Command, by_id, match, resolve

if TYPE_CHECKING:
    from smbr.agent.loop import SmbrAgent

DEFAULT_PLAN = "waiting for clarification / preflight"

REQUEST_PLACEHOLDER = "ask anything… / for commands"

#: The kernel's steps, in order, for the sidebar.
STEP_SEQUENCE: tuple[str, ...] = tuple(step.value for step in Step)

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


class CommandInput(Input):
    """The composer: ``/`` opens the command popup over the same input."""

    def on_key(self, event) -> None:
        app: SmbrApp = self.app  # type: ignore[assignment]
        if not app.commands_visible:
            return
        if event.key == "down":
            event.prevent_default()
            event.stop()
            app.command_list.action_cursor_down()
        elif event.key == "up":
            event.prevent_default()
            event.stop()
            app.command_list.action_cursor_up()
        elif event.key == "tab":
            event.prevent_default()
            event.stop()
            app.complete_command()
        elif event.key == "escape":
            event.prevent_default()
            event.stop()
            app.hide_commands()
        elif event.key == "enter":
            event.prevent_default()
            event.stop()
            app.run_highlighted_command()


class SmbrApp(App):
    """SMBR terminal interface."""

    CSS = """
    #body { height: 1fr; }
    #sidebar { width: 30%; min-width: 18; border-right: solid $primary; }
    #sidebar-header { padding: 0 1; text-style: bold; }
    #steps { height: 1fr; padding: 0 1; }
    #plan-label { padding: 0 1; color: $text-muted; }
    #plan { height: 8; padding: 0 1; }
    #events { width: 70%; }
    #composer { height: auto; border: round $primary; }
    #commands { height: 8; display: none; }
    #request { border: none; }
    #status { height: 1; background: $panel; padding: 0 1; }
    PaletteScreen { align: center middle; }
    #palette {
        width: 70%; height: 80%;
        border: round $primary; background: $surface; padding: 1 2;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("q", "quit", "Quit"),
        ("ctrl+p", "palette", "Commands"),
    ]

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
        self._seen_steps: list[str] = []

    # -- layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("Run", id="sidebar-header")
                yield RichLog(id="steps", markup=True, wrap=True)
                yield Static("Plan", id="plan-label")
                yield RichLog(id="plan", markup=False, wrap=True)
            yield RichLog(id="events", markup=True, wrap=True)
        with Vertical(id="composer"):
            yield OptionList(id="commands")
            yield CommandInput(placeholder=REQUEST_PLACEHOLDER, id="request")
        yield Static("", id="status", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "SMBR"
        self.sub_title = "Small Model, Big Results"
        self.set_plan(self.plan)
        self.render_steps()
        self._render_status()
        self.set_interval(1.0, self._tick)
        self.query_one("#request", Input).focus()
        self.record("harness started")
        if self._demo:
            self.record("demo mode: no model server needed")
        if self._request:
            self._start_run(self._request)

    # -- transcripts -------------------------------------------------------

    def record(self, message: str) -> None:
        """Append one harness message, styled by what it means."""
        self.events.append(message)
        style = _KIND_STYLES[classify(message)]
        rendered = message if not style else f"[{style}]{message}[/]"
        self.query_one("#events", RichLog).write(rendered)

    def begin_step(self, step: str) -> None:
        """A new step starts: announce it, mark it in the sidebar."""
        self.set_step(step)
        self.record(f"— {step} —")

    def set_step(self, step: str) -> None:
        self.step = step
        if step not in self._seen_steps:
            self._seen_steps.append(step)
        self.render_steps()
        self._render_status()

    def set_plan(self, plan: str) -> None:
        self.plan = plan
        log = self.query_one("#plan", RichLog)
        log.clear()
        log.write(plan)

    def set_plan_progress(self, current: int, total: int) -> None:
        self._plan_progress = f" · plan {current}/{total}" if total else ""
        self._render_status()

    def render_steps(self) -> None:
        """The kernel's steps with their state: done, current, upcoming."""
        lines: list[str] = []
        for name in STEP_SEQUENCE:
            if name in self._seen_steps and name != self.step:
                lines.append(f"[green]✓[/] {name}")
            elif name == self.step:
                lines.append(f"[cyan]▸ {name}[/]")
            else:
                lines.append(f"[dim]  {name}[/]")
        log = self.query_one("#steps", RichLog)
        log.clear()
        log.write("\n".join(lines))

    def record_gate(self, gate: str, passed: bool, reason: str) -> None:
        status = "PASS" if passed else "FAIL"
        self.record(f"[gate:{status}] {gate} — {reason}")

    def record_tool_call(self, name: str, result: str) -> None:
        self.record(f"[tool] {name} — {result}")

    # -- status line -------------------------------------------------------

    def _render_status(self) -> None:
        state = "running" if self._busy else "idle"
        clock = ""
        if self._started_at is not None:
            clock = f" · {time.monotonic() - self._started_at:4.0f}s"
        model = self._model or ("demo model" if self._demo else "no model configured")
        cwd = Path.cwd().name or str(Path.cwd())
        self.query_one("#status", Static).update(
            Text.assemble(
                ("SMBR", "b"),
                f" · {model}",
                f" · {cwd}",
                f" · {self.step}",
                (f" · {state}", "b" if self._busy else "dim"),
                self._plan_progress,
                clock,
                " · ctrl+p commands",
            )
        )

    def _tick(self) -> None:
        if self._busy:
            self._render_status()

    # -- the command popup -------------------------------------------------

    @property
    def command_list(self) -> OptionList:
        return self.query_one("#commands", OptionList)

    @property
    def commands_visible(self) -> bool:
        return self.query_one("#commands", OptionList).display

    def show_commands(self, query: str) -> None:
        options = [Option(f"/{c.name}  {c.description}", id=c.id) for c in match(query)]
        if not options:
            self.hide_commands()
            return
        listing = self.command_list
        listing.clear_options()
        listing.add_options(options)
        listing.display = True
        listing.highlighted = 0
        self._render_status()

    def hide_commands(self) -> None:
        self.command_list.display = False

    def complete_command(self) -> None:
        """Tab: fill the composer with the highlighted command's name."""
        command = self._highlighted_command()
        if command is not None:
            self.query_one("#request", Input).value = f"/{command.name} "

    def run_highlighted_command(self) -> None:
        command = self._highlighted_command()
        if command is not None:
            self.hide_commands()
            self.query_one("#request", Input).value = ""
            self.run_command(command, "")

    def action_palette(self) -> None:
        """Ctrl+P: every command, grouped, with a footer."""
        self.push_screen(PaletteScreen())

    def _highlighted_command(self) -> Command | None:
        """The highlighted (or, before the list has focus, first) command."""
        listing = self.command_list
        if not listing.options:
            return None
        index = listing.highlighted if listing.highlighted is not None else 0
        index = max(0, min(index, len(listing.options) - 1))
        return by_id(str(listing.options[index].id))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        command = by_id(str(event.option_id))
        if command is not None:
            self.hide_commands()
            self.query_one("#request", Input).value = ""
            self.run_command(command, "")

    def on_input_changed(self, event: Input.Changed) -> None:
        value = event.value
        if value.startswith("/"):
            self.show_commands(value[1:])
        else:
            self.hide_commands()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        event.input.value = ""
        if not value:
            return
        if value.startswith("/"):
            name, _, argument = value[1:].partition(" ")
            command = resolve(name)
            if command is None:
                self.record(f"[refused] unknown command: /{name} (try /help)")
                return
            self.hide_commands()
            self.run_command(command, argument.strip())
            return
        self._start_run(value)

    # -- running commands and requests -------------------------------------

    def run_command(self, command: Command, argument: str) -> None:
        """Handle one slash command. The palette routes here too."""
        self._dispatch_command(command, argument)
        # recorded last: a command that clears the transcript still shows what ran
        self.record(f"[answer] /{command.name}" + (f" {argument}" if argument else ""))

    def _dispatch_command(self, command: Command, argument: str) -> None:
        if command.id == "interface.help":
            self._help()
        elif command.id == "interface.quit":
            self.exit()
        elif command.id == "interface.palette":
            self.action_palette()
        elif command.id == "session.clear":
            self.query_one("#events", RichLog).clear()
            self.events.clear()
        elif command.id == "session.new":
            self._reset_run()
        elif command.id == "harness.status":
            self._status()
        elif command.id == "harness.gates":
            self._gates()
        elif command.id == "harness.tools":
            self._tools()
        elif command.id == "harness.demo":
            self._start_run("leave a demo note", force_demo=True)
        elif command.id == "tools.import":
            self._import()
        elif command.id == "model.show":
            self._model_info()
        else:  # pragma: no cover - every command has a handler
            self.record(f"[refused] /{command.name} is not wired up")

    def _help(self) -> None:
        self.record("SMBR takes guessing away from the model: one constrained-JSON")
        self.record("question at a time, and a gate decides whether that step may happen.")
        self.record("q quit · ctrl+p every command · / opens the command popup")
        for command in COMMANDS:
            self.record(f"  /{command.name} — {command.description}")

    def _status(self) -> None:
        from smbr.config import Settings

        settings = Settings(project_root=Path.cwd())
        self.record(
            f"step: {self.step} · backend: {settings.model_backend} · model: {settings.model}"
        )
        self.record(f"checks: {settings.test_command} · {settings.lint_command}")
        if self._busy:
            self.record("a run is in progress")

    def _gates(self) -> None:
        from smbr.kernel.gates import GateRunner

        for gate in GateRunner.GATE_NAMES:
            self.record(f"[gate:—] {gate}")

    def _tools(self) -> None:
        from smbr.config import Settings
        from smbr.tools.registry import registry_from_settings

        registry = registry_from_settings(Settings(project_root=Path.cwd()))
        for name in registry.expose(Step(self.step)):
            self.record(f"[tool] {name}")

    def _import(self) -> None:
        from smbr.imports import discover_mcp
        from smbr.imports.sources import source_paths

        results = discover_mcp(source_paths(Path.cwd()), Path.cwd())
        found = sum(len(result.servers) for result in results)
        skipped = sum(len(result.skipped) for result in results)
        self.record(f"scan: {found} MCP server(s) and skills from other agents")
        self.record(f"        {skipped} entry(ies) skipped (remote transport, disabled)")
        self.record("run 'smbr import mcp' in a terminal to write them, disabled")

    def _model_info(self) -> None:
        from smbr.config import Settings

        settings = Settings(project_root=Path.cwd())
        self.record(f"[tool] backend: {settings.model_backend}")
        self.record(f"[tool] model: {settings.model}")
        if settings.model_backend == "openai":
            self.record(f"[tool] api base: {settings.api_base_url}")

    def _reset_run(self) -> None:
        self._seen_steps = []
        self._plan = []
        self._plan_progress = ""
        self.step = "intake"
        self.set_plan(DEFAULT_PLAN)
        self.query_one("#events", RichLog).clear()
        self.events.clear()
        self.render_steps()
        self._render_status()
        self.record("a fresh run starts with the next request")

    # -- running a request -------------------------------------------------

    def _start_run(self, request: str, force_demo: bool = False) -> None:
        """Build the agent and drive it in a worker thread."""
        from smbr.agent import SmbrAgent, build_decision_router
        from smbr.config import Settings

        if self._busy:
            self.record("[warn] a run is already in progress; wait for it to finish")
            return
        self._busy = True
        self._started_at = time.monotonic()
        self._seen_steps = []
        settings = Settings(project_root=Path.cwd())
        if self._demo or force_demo:
            from smbr.agent.demo import DemoClient

            client = DemoClient()
            self._model = "demo model"
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
        if "(" in step:
            inside = step.split("(", 1)[1].split(")", 1)[0]
            current, _, total = inside.partition("/")
            try:
                progress = (int(current), int(total))
            except ValueError:
                progress = (0, 0)
        else:
            progress = (0, 0)
        self.call_from_thread(self.set_plan_progress, *progress)
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
        self._plan_progress = ""
        self._render_status()


class PaletteScreen(ModalScreen[None]):
    """Ctrl+P: every command, grouped by category, with a footer."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        options = [
            Option(
                f"{command.category:<10} /{command.name:<10} {command.description}",
                id=command.id,
            )
            for command in COMMANDS
        ]
        yield OptionList(*options, id="palette")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        command = by_id(str(event.option_id))
        self.dismiss(None)
        if command is not None and self.app is not None:
            self.app.run_command(command, "")  # type: ignore[attr-defined]
