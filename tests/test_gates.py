"""Every gate blocks without grounding and passes with it; overrides log."""

from __future__ import annotations

import pytest

from smbr.kernel import (
    CommentHygieneGate,
    DeclaredCapabilitiesGate,
    GateContext,
    GateRefusal,
    GroundedClaimsGate,
    Kernel,
    ReadBeforeEditGate,
    Session,
    SymbolCheckGate,
    VerifyBeforeDoneGate,
    default_gates,
)
from smbr.preflight.capabilities import Capability


def test_read_before_edit_refuses_unread_file() -> None:
    gate = ReadBeforeEditGate()
    ctx = GateContext(action="edit:app.py", path="app.py")
    result = gate.check(ctx, Session())
    assert not result.passed
    assert "app.py" in result.reason  # harness template names the file

    session = Session(read_files={"app.py"})
    assert gate.check(ctx, session).passed


def test_symbol_check_requires_confirmed_symbols() -> None:
    gate = SymbolCheckGate()
    ctx = GateContext(action="edit:app.py", symbols=["Client", "helper"])
    assert not gate.check(ctx, Session()).passed

    session = Session(confirmed_symbols={"Client", "helper"})
    assert gate.check(ctx, session).passed

    partial = Session(confirmed_symbols={"Client"})
    result = gate.check(ctx, partial)
    assert not result.passed
    assert "helper" in result.reason


def test_verify_before_done_requires_passing_checks() -> None:
    gate = VerifyBeforeDoneGate(("test_runner", "linter"))

    not_run = gate.check(GateContext(action="report_done"), Session())
    assert not not_run.passed and "test_runner" in not_run.reason

    failed = gate.check(
        GateContext(action="report_done"),
        Session(check_outcomes={"test_runner": False, "linter": True}),
    )
    assert not failed.passed and "failed" in failed.reason

    ok = gate.check(
        GateContext(action="report_done"),
        Session(check_outcomes={"test_runner": True, "linter": True}),
    )
    assert ok.passed


def test_grounded_claims_requires_tool_result() -> None:
    gate = GroundedClaimsGate()
    ctx = GateContext(action="claim", evidence=[])
    assert not gate.check(ctx, Session()).passed

    session = Session(tool_results={"call-1": "grep output"})
    assert gate.check(GateContext(action="claim", evidence=["call-1"]), session).passed

    # citing a tool result that does not exist is still ungrounded
    assert not gate.check(GateContext(action="claim", evidence=["nope"]), session).passed


def test_comment_hygiene_gate_reads_findings() -> None:
    gate = CommentHygieneGate()
    assert gate.check(GateContext(action="apply_patch"), Session()).passed
    blocked = gate.check(
        GateContext(action="apply_patch", comment_findings=["line 2: restates_code"]), Session()
    )
    assert not blocked.passed and "restates_code" in blocked.reason


def test_declared_capabilities_gate() -> None:
    gate = DeclaredCapabilitiesGate()
    ctx = GateContext(action="tool_call:test_runner", capability="test_runner")
    assert not gate.check(ctx, Session()).passed

    session = Session(declared_capabilities={Capability.TEST_RUNNER})
    assert gate.check(ctx, session).passed

    approved = Session(harness_approved_capabilities={Capability.TEST_RUNNER})
    assert gate.check(ctx, approved).passed


def test_kernel_guard_raises_and_override_unblocks() -> None:
    kernel = Kernel(gates=default_gates())
    ctx = GateContext(action="edit:app.py", path="app.py")
    with pytest.raises(GateRefusal):
        kernel.guard_action("edit:app.py", ctx)

    kernel.override("read_before_edit", "edit:app.py", "user reviewed the file externally")
    kernel.guard_action("edit:app.py", ctx)  # no raise
    assert kernel.session.overrides[0].gate == "read_before_edit"
