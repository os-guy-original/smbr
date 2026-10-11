"""State machine types and transitions.

The harness owns the flow: the model proposes, the state machine decides.
Every transition below is deterministic code — nothing here consults the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from smbr.preflight.capabilities import Capability, CapabilityFailure


class Step(StrEnum):
    """The seven ordered steps of one task run."""

    INTAKE = "intake"
    CLARIFY = "clarify"
    PREFLIGHT = "preflight"
    PLAN = "plan"
    EDIT = "edit"
    VERIFY = "verify"
    REPORT = "report"


class Exit(StrEnum):
    """The three ways a run can leave the loop."""

    DONE = "done"
    STUCK = "stuck"
    HALTED = "halted"


@dataclass(frozen=True)
class GateOverride:
    """A user's explicit override of a gate refusal. Always logged."""

    gate: str
    action: str
    justification: str


@dataclass
class Session:
    """Everything the gates are allowed to look at when judging an action.

    The model never writes to this directly; the harness updates it from real
    tool output (a file was actually read, a symbol was actually found, a
    check actually ran).
    """

    read_files: set[str] = field(default_factory=set)
    confirmed_symbols: set[str] = field(default_factory=set)
    declared_capabilities: set[Capability] = field(default_factory=set)
    harness_approved_capabilities: set[Capability] = field(default_factory=set)
    open_capability_failures: list[CapabilityFailure] = field(default_factory=list)
    tool_results: dict[str, str] = field(default_factory=dict)
    check_outcomes: dict[str, bool] = field(default_factory=dict)
    overrides: list[GateOverride] = field(default_factory=list)
    edit_attempts: int = 0
    # Findings from the comment-hygiene check on the latest patch; non-empty
    # sends the patch back for revision and blocks the move to verify.
    pending_comment_findings: list[str] = field(default_factory=list)

    def override(self, gate: str, action: str, justification: str) -> None:
        self.overrides.append(GateOverride(gate, action, justification))

    def is_overridden(self, gate: str, action: str) -> bool:
        return any(o.gate == gate and o.action == action for o in self.overrides)


@dataclass(frozen=True)
class StepOutcome:
    """What the harness observed when leaving a step."""

    next: Step | Exit
    reason: str = ""


def decide_next(
    step: Step,
    outcome: StepOutcome,
    session: Session,
    *,
    max_edit_attempts: int = 3,
) -> Step | Exit:
    """Return the next step (or exit) for the current step.

    The repair loop is the only cycle: verify failing returns to edit until the
    edit budget is spent, then the run exits STUCK with its history intact.
    """
    if step is Step.INTAKE:
        return Step.CLARIFY if outcome.next is Step.CLARIFY else Step.PREFLIGHT
    if step is Step.CLARIFY:
        return Step.PREFLIGHT
    if step is Step.PREFLIGHT:
        # Missing or unhealthy capabilities halt the run for the user.
        return Exit.HALTED if session.open_capability_failures else Step.PLAN
    if step is Step.PLAN:
        return Step.EDIT
    if step is Step.EDIT:
        return Step.VERIFY
    if step is Step.VERIFY:
        if outcome.next is Step.REPORT:
            return Step.REPORT
        if session.edit_attempts < max_edit_attempts:
            return Step.EDIT
        return Exit.STUCK
    if step is Step.REPORT:
        return Exit.DONE
    msg = f"unknown step: {step}"
    raise ValueError(msg)
