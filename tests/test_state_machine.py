"""State-machine transitions: order, repair loop, exits."""

from __future__ import annotations

from smbr.kernel import (
    Exit,
    Kernel,
    Session,
    Step,
    StepOutcome,
    decide_next,
    default_gates,
)
from smbr.preflight.capabilities import Capability, CapabilityFailure, FailureType


def _handlers(verify_passed: bool, capability_failure: bool = False) -> dict:
    def preflight(kernel: Kernel) -> None:
        kernel.declared([Capability.FILE_READ, Capability.TEST_RUNNER, Capability.LINTER])
        if capability_failure:
            kernel.session.open_capability_failures.append(
                CapabilityFailure(Capability.TEST_RUNNER, FailureType.NOT_INSTALLED)
            )

    def edit(kernel: Kernel) -> None:
        kernel.session.edit_attempts += 0  # attempts counted by the runner

    def verify(kernel: Kernel) -> StepOutcome:
        kernel.session.check_outcomes = {"test_runner": verify_passed, "linter": verify_passed}
        if verify_passed:
            return StepOutcome(Step.REPORT)
        return StepOutcome(Step.EDIT, "checks failed; repairing")

    return {
        Step.INTAKE: lambda k: StepOutcome(Step.CLARIFY),
        Step.CLARIFY: lambda k: None,
        Step.PREFLIGHT: preflight,
        Step.PLAN: lambda k: None,
        Step.EDIT: edit,
        Step.VERIFY: verify,
        Step.REPORT: lambda k: None,
    }


def test_happy_path_reaches_done() -> None:
    kernel = Kernel(gates=default_gates(("test_runner", "linter")))
    result = kernel.run(handlers=_handlers(verify_passed=True))
    assert result.exit is Exit.DONE
    assert result.steps == [
        Step.INTAKE,
        Step.CLARIFY,
        Step.PREFLIGHT,
        Step.PLAN,
        Step.EDIT,
        Step.VERIFY,
        Step.REPORT,
    ]


def test_repair_loop_returns_to_edit_then_sticks() -> None:
    kernel = Kernel(gates=default_gates(("test_runner", "linter")))
    result = kernel.run(handlers=_handlers(verify_passed=False))
    assert result.exit is Exit.STUCK
    assert result.steps.count(Step.EDIT) == 3  # budget spent


def test_capability_failure_halts_before_planning() -> None:
    kernel = Kernel(gates=default_gates(("test_runner", "linter")))
    result = kernel.run(handlers=_handlers(verify_passed=True, capability_failure=True))
    assert result.exit is Exit.HALTED
    assert Step.PLAN not in result.steps


def test_intake_can_skip_clarification() -> None:
    result = decide_next(Step.INTAKE, StepOutcome(Step.PREFLIGHT), Session())
    assert result is Step.PREFLIGHT
