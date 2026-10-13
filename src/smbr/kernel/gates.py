"""Gates: code-enforced rules the model cannot argue with.

A gate either returns a pass, or a refusal whose message is filled from the
harness templates below. The model never sees this text before the user does
and never gets to phrase it. Every gate is user-overridable; every override is
logged on the session and surfaced in the TUI.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import ClassVar, Protocol

from smbr.kernel.state import Session

# Harness-owned message templates. The model cannot soften, rephrase, or
# skip these: it never writes them.
TEMPLATES: dict[str, str] = {
    "read_before_edit": (
        "Refused edit of {path}: the file was not read in this session. Run a read first."
    ),
    "symbol_check": (
        "Refused edit: symbol(s) {symbols} were not confirmed by symbol lookup. "
        "Look them up, or say you don't know and ask the user."
    ),
    "verify_before_done": (
        "Refused 'done': checks did not pass ({missing}). "
        "Return to edit; the repair loop is still open."
    ),
    "grounded_claims": (
        "Refused claim: no tool result cited. Ground it in a tool call, "
        "or state that you don't know."
    ),
    "comment_hygiene": (
        "Refused patch: added comment(s) failed hygiene ({findings}). Revise the patch."
    ),
    "declared_capabilities": (
        "Refused tool call for {capability}: it was not declared in the "
        "preflight manifest and the harness did not approve it."
    ),
}


@dataclass(frozen=True)
class GateContext:
    """The facts about the requested action, all sourced from tool output."""

    action: str
    path: str | None = None
    symbols: Sequence[str] = field(default_factory=tuple)
    evidence: Sequence[str] = field(default_factory=tuple)
    capability: str | None = None
    comment_findings: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class GateResult:
    gate: str
    passed: bool
    reason: str
    overridden: bool = False


class Gate(Protocol):
    """A checkable rule guarding one class of action."""

    name: str

    def applies_to(self, ctx: GateContext) -> bool:
        """Whether this gate has anything to say about this action."""

    def check(self, ctx: GateContext, session: Session) -> GateResult: ...


class ReadBeforeEditGate:
    name = "read_before_edit"

    def applies_to(self, ctx: GateContext) -> bool:
        return ctx.path is not None

    def check(self, ctx: GateContext, session: Session) -> GateResult:
        assert ctx.path is not None, "read_before_edit needs a path"
        if ctx.path in session.read_files:
            return GateResult(self.name, True, "file was read in this session")
        return GateResult(
            self.name,
            False,
            TEMPLATES["read_before_edit"].format(path=ctx.path),
        )


class SymbolCheckGate:
    name = "symbol_check"

    def applies_to(self, ctx: GateContext) -> bool:
        return bool(ctx.symbols)

    def check(self, ctx: GateContext, session: Session) -> GateResult:
        unconfirmed = [s for s in ctx.symbols if s not in session.confirmed_symbols]
        if not unconfirmed:
            return GateResult(self.name, True, "all symbols confirmed by lookup")
        return GateResult(
            self.name,
            False,
            TEMPLATES["symbol_check"].format(symbols=", ".join(sorted(unconfirmed))),
        )


class VerifyBeforeDoneGate:
    name = "verify_before_done"

    def __init__(self, required_checks: Sequence[str]) -> None:
        self.required_checks = tuple(required_checks)

    def applies_to(self, ctx: GateContext) -> bool:
        return ctx.action == "report_done"

    def check(self, ctx: GateContext, session: Session) -> GateResult:
        missing = [c for c in self.required_checks if c not in session.check_outcomes]
        failed = [c for c, ok in session.check_outcomes.items() if not ok]
        if not missing and not failed:
            return GateResult(self.name, True, "all required checks ran and passed")
        problems = missing + [f"{c} (failed)" for c in failed]
        return GateResult(
            self.name,
            False,
            TEMPLATES["verify_before_done"].format(missing=", ".join(problems)),
        )


class GroundedClaimsGate:
    name = "grounded_claims"

    def applies_to(self, ctx: GateContext) -> bool:
        return ctx.action.startswith("claim")

    def check(self, ctx: GateContext, session: Session) -> GateResult:
        cited = [e for e in ctx.evidence if e in session.tool_results]
        if cited:
            return GateResult(self.name, True, f"claim cites tool result(s): {', '.join(cited)}")
        return GateResult(self.name, False, TEMPLATES["grounded_claims"])


class CommentHygieneGate:
    name = "comment_hygiene"

    def applies_to(self, ctx: GateContext) -> bool:
        return bool(ctx.comment_findings)

    def check(self, ctx: GateContext, session: Session) -> GateResult:
        if not ctx.comment_findings:
            return GateResult(self.name, True, "added comments passed hygiene")
        return GateResult(
            self.name,
            False,
            TEMPLATES["comment_hygiene"].format(findings="; ".join(ctx.comment_findings)),
        )


class DeclaredCapabilitiesGate:
    name = "declared_capabilities"

    def applies_to(self, ctx: GateContext) -> bool:
        return ctx.capability is not None

    def check(self, ctx: GateContext, session: Session) -> GateResult:
        assert ctx.capability is not None, "declared_capabilities needs a capability"
        known = session.declared_capabilities | session.harness_approved_capabilities
        if ctx.capability in known:
            return GateResult(self.name, True, "capability declared in preflight")
        return GateResult(
            self.name,
            False,
            TEMPLATES["declared_capabilities"].format(capability=ctx.capability),
        )


class GateRunner:
    """Runs the gates; the templates live here, never in the model."""

    GATE_NAMES: ClassVar[tuple[str, ...]] = (
        "read_before_edit",
        "symbol_check",
        "verify_before_done",
        "grounded_claims",
        "comment_hygiene",
        "declared_capabilities",
    )

    """Applies gates in order, honoring logged user overrides."""

    def __init__(self, gates: Sequence[Gate]) -> None:
        self.gates = tuple(gates)

    def check(self, gate: Gate, ctx: GateContext, session: Session) -> GateResult:
        result = gate.check(ctx, session)
        if not result.passed and session.is_overridden(gate.name, ctx.action):
            return GateResult(gate.name, True, "user override (logged)", overridden=True)
        return result


def default_gates(required_checks: Sequence[str] = ("test_runner", "linter")) -> GateRunner:
    """The standard v1 gate set, in evaluation order."""
    return GateRunner(
        [
            ReadBeforeEditGate(),
            SymbolCheckGate(),
            CommentHygieneGate(),
            DeclaredCapabilitiesGate(),
            GroundedClaimsGate(),
            VerifyBeforeDoneGate(required_checks),
        ]
    )
