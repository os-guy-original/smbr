"""The kernel runner: the frozen loop.

The runner owns ordering, budgets, gate evaluation, overrides and the tool
call log. It never asks the model whether something is allowed — it decides
with code and only reports. Step *handlers* are injected (by the TUI, CLI, or
tests), so the kernel itself is fully testable without a model.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from smbr.kernel.gates import Gate, GateContext, GateRunner
from smbr.kernel.state import Exit, GateOverride, Session, Step, StepOutcome, decide_next
from smbr.preflight.capabilities import Capability

if TYPE_CHECKING:
    from smbr.tools.registry import ToolRegistry

# Which gates must pass for each transition. Action-level gates (read before
# edit, symbol check, grounded claims, declared capabilities) are enforced by
# Kernel.guard_action when the model asks for the action.
TRANSITION_GATES: dict[tuple[Step, Step], tuple[str, ...]] = {
    (Step.EDIT, Step.VERIFY): ("comment_hygiene",),
    (Step.VERIFY, Step.REPORT): ("verify_before_done",),
}

StepHandler = Callable[["Kernel"], StepOutcome | None]


@dataclass
class RunResult:
    exit: Exit
    steps: list[Step] = field(default_factory=list)
    reason: str = ""
    overrides: list[GateOverride] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)


class GateRefusal(Exception):
    """Raised when a gate refuses an action and no override exists."""

    def __init__(self, result) -> None:
        super().__init__(result.reason)
        self.result = result


class Kernel:
    """Runs one task through the state machine under the gates."""

    def __init__(
        self,
        *,
        registry: ToolRegistry | None = None,
        gates: GateRunner | None = None,
        max_edit_attempts: int = 3,
    ) -> None:
        if registry is None:
            from smbr.tools.registry import ToolRegistry  # local import: breaks the cycle

            registry = ToolRegistry()
        self.registry = registry
        self.gates = gates if gates is not None else GateRunner([])
        self.max_edit_attempts = max_edit_attempts
        self.session = Session()
        self.tool_calls: list[str] = []

    # -- tools -----------------------------------------------------------

    def exposed_tools(self, step: Step) -> list[str]:
        """The only tools the model may see at this step (3-5 by design)."""
        return self.registry.expose(step)

    def call_tool(self, name: str) -> None:
        """Record a tool call. Capability enforcement happens in gates."""
        self.tool_calls.append(name)

    # -- actions ---------------------------------------------------------

    def guard_action(self, action: str, ctx: GateContext) -> None:
        """Run every gate against an action; refuse or allow, never suggest."""
        for gate in self.gates.gates:
            if not gate.applies_to(ctx):
                continue
            result = self.gates.check(gate, ctx, self.session)
            if not result.passed:
                raise GateRefusal(result)

    def override(self, gate: str, action: str, justification: str) -> None:
        """Explicit user override; logged on the session for the TUI."""
        self.session.override(gate, action, justification)

    # -- the loop ----------------------------------------------------------

    def run(self, *, handlers: dict[Step, StepHandler]) -> RunResult:
        step = Step.INTAKE
        visited: list[Step] = []
        reason = ""
        while True:
            visited.append(step)
            handler = handlers.get(step)
            if handler is None:
                return RunResult(Exit.HALTED, visited, f"no handler for step {step.value}")
            outcome = handler(self)
            if outcome is None:
                outcome = StepOutcome(default_next(step))
            reason = outcome.reason or reason
            nxt = decide_next(step, outcome, self.session, max_edit_attempts=self.max_edit_attempts)
            blocked = self._blocked_transition(step, nxt)
            if blocked is not None:
                return RunResult(Exit.HALTED, visited, f"transition blocked by gate: {blocked}")
            if isinstance(nxt, Exit):
                return RunResult(nxt, visited, reason, self.session.overrides, self.tool_calls)
            if step is Step.EDIT:
                self.session.edit_attempts += 1
            step = nxt

    def _blocked_transition(self, step: Step, nxt: Step | Exit) -> str | None:
        if not isinstance(nxt, Step):
            return None
        for gate_name in TRANSITION_GATES.get((step, nxt), ()):
            gate = self._gate_by_name(gate_name)
            if gate is None:
                continue
            ctx = self._transition_ctx(gate_name)
            if not gate.applies_to(ctx):
                continue
            result = self.gates.check(gate, ctx, self.session)
            if not result.passed:
                return gate_name
        return None

    def _gate_by_name(self, name: str) -> Gate | None:
        for gate in self.gates.gates:
            if gate.name == name:
                return gate
        return None

    def _transition_ctx(self, gate_name: str) -> GateContext:
        if gate_name == "comment_hygiene":
            return GateContext(
                action=f"transition:{gate_name}",
                comment_findings=self.session.pending_comment_findings,
            )
        return GateContext(action=f"transition:{gate_name}")

    def declared(self, capabilities: Iterable[Capability]) -> None:
        self.session.declared_capabilities = set(capabilities)


def default_next(step: Step) -> Step | Exit:
    """The natural successor of a step when nothing unusual happened."""
    return {
        Step.INTAKE: Step.PREFLIGHT,
        Step.CLARIFY: Step.PREFLIGHT,
        Step.PREFLIGHT: Step.PLAN,
        Step.PLAN: Step.EDIT,
        Step.EDIT: Step.VERIFY,
        Step.VERIFY: Step.REPORT,
        Step.REPORT: Exit.DONE,
    }[step]
