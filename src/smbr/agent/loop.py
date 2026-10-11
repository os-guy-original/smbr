"""The agent loop: the kernel driven by a local model, under the gates.

Every model interaction is one constrained-JSON question. Every file touch
goes through a tool that records a real result. Every gate refusal surfaces
to the user with a harness message. A model that fails, returns garbage, or
cites nothing halts the run — the harness never fills the gap with a guess.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from smbr.agent.ports import UserPort
from smbr.agent.prompts import (
    CLAIMS_SCHEMA,
    INTAKE_SCHEMA,
    MANIFEST_SCHEMA,
    PATCH_SCHEMA,
    PLAN_SCHEMA,
    SLOT_QUESTION_SCHEMA,
    claims_prompt,
    intake_prompt,
    manifest_prompt,
    patch_prompt,
    plan_prompt,
    slot_question_prompt,
)
from smbr.clarify.slots import (
    ExtractedSlot,
    SlotExtraction,
    TaskType,
    needs_clarification,
    plan_questions,
)
from smbr.config import Settings
from smbr.decisions.provider import CompletionClient, DecisionRouter
from smbr.hygiene.comments import comment_findings
from smbr.kernel.gates import GateContext, default_gates
from smbr.kernel.runner import GateRefusal, Kernel, RunResult
from smbr.kernel.state import Exit, Step, StepOutcome
from smbr.preflight.manifest import ManifestParseError, check_manifest, parse_manifest
from smbr.tools.checks import command_from_str, run_check
from smbr.tools.files import read_file
from smbr.tools.patch import PatchApplyTool, PatchError
from smbr.tools.registry import ToolRegistry, registry_from_settings
from smbr.tools.symbols import index_source, lookup_symbol

MAX_CLARIFY_ROUNDS = 3


class ModelUnavailable(RuntimeError):
    """The model could not answer. Halts the run; never silently guessed past."""


class _Halt(Exception):
    """Stop the run for the user, with a harness message."""


@dataclass
class PlanStep:
    what: str
    files: list[str] = field(default_factory=list)


class SmbrAgent:
    """Runs one request through the kernel with a scripted-by-schema model."""

    def __init__(
        self,
        *,
        settings: Settings,
        client: CompletionClient,
        user: UserPort,
        registry: ToolRegistry | None = None,
        router: DecisionRouter | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.user = user
        self.registry = registry or registry_from_settings(settings)
        self.router = router
        self.patch_tool = PatchApplyTool(cwd=str(settings.project_root))
        self.gates = default_gates(self._required_checks())
        self.kernel = Kernel(
            registry=self.registry,
            gates=self.gates,
            max_edit_attempts=settings.max_edit_attempts,
        )
        self._request = ""
        self._extraction: SlotExtraction | None = None
        self._plan: list[PlanStep] = []
        self._repair_context = ""
        self._tool_seq = 0

    # -- public API -------------------------------------------------------

    def run(self, request: str) -> RunResult:
        self._request = request
        handlers = {step: getattr(self, f"_h_{step.value}") for step in Step}
        try:
            return self.kernel.run(handlers=handlers)
        except _Halt as exc:
            return self._halted(str(exc))
        except ModelUnavailable as exc:
            self.user.notify(f"model unavailable: {exc}")
            return self._halted(f"model unavailable: {exc}")

    # -- model plumbing ---------------------------------------------------

    def _model_json(self, prompt: str, schema: dict) -> dict:
        try:
            data = self.client.complete_json(prompt, schema)
        except Exception as exc:  # any backend failure means "no answer", never a guess
            raise ModelUnavailable(f"{type(exc).__name__}: {exc}") from exc
        if not isinstance(data, dict):
            raise ModelUnavailable("model did not return a JSON object")
        return data

    def _record_tool(self, name: str, result: str) -> str:
        self._tool_seq += 1
        result_id = f"tool-{self._tool_seq}: {name}"
        self.kernel.session.tool_results[result_id] = result[:200]
        self.kernel.call_tool(name)
        self.user.notify(f"{name} -> {result[:120]}")
        return result_id

    def _halted(self, reason: str) -> RunResult:
        self.user.notify(f"run halted: {reason}")
        return RunResult(
            Exit.HALTED,
            [],
            reason,
            self.kernel.session.overrides,
            self.kernel.tool_calls,
        )

    def _required_checks(self) -> tuple[str, ...]:
        pairs = (
            ("type_checker", self.settings.typecheck_command),
            ("test_runner", self.settings.test_command),
            ("linter", self.settings.lint_command),
        )
        return tuple(cap for cap, cmd in pairs if cmd.strip())

    # -- step handlers ----------------------------------------------------

    def _h_intake(self, kernel: Kernel) -> StepOutcome:
        data = self._model_json(intake_prompt(self._request), INTAKE_SCHEMA)
        try:
            extraction = SlotExtraction.model_validate(data)
        except ValidationError:
            extraction = SlotExtraction(task_type=TaskType.MODIFY_CODE, slots=[])
        self._extraction = extraction
        if needs_clarification(extraction.task_type, extraction):
            return StepOutcome(Step.CLARIFY, "required slots are missing")
        return StepOutcome(Step.PREFLIGHT)

    def _h_clarify(self, kernel: Kernel) -> StepOutcome | None:
        assert self._extraction is not None
        extraction = self._extraction
        for round_no in range(1, MAX_CLARIFY_ROUNDS + 1):
            questions = plan_questions(
                extraction.task_type, extraction, cap=self.settings.questions_per_round
            )
            if not questions:
                return None
            for slot in questions:
                self._ask_one_slot(extraction, slot, round_no)
        if needs_clarification(extraction.task_type, extraction):
            raise _Halt("clarification incomplete after the maximum rounds")
        return None

    def _ask_one_slot(self, extraction: SlotExtraction, slot: str, round_no: int) -> None:
        data = self._model_json(
            slot_question_prompt(slot, extraction.task_type.value), SLOT_QUESTION_SCHEMA
        )
        question = str(data.get("question") or f"What {slot} should this task use?")
        raw_options = data.get("options", [])
        options = [str(o) for o in raw_options][:4] if isinstance(raw_options, list) else []
        options = options or ["(no preference)"]
        answer = self.user.ask(question, [*options, "you decide"])
        if answer == "you decide":
            decided = self.router.decide_for_user(slot) if self.router else None
            if not decided:
                raise _Halt(f"no decision-profile value for '{slot}' and the user delegated")
            self._set_slot(extraction, slot, decided, "user delegated to decision profile")
            return
        self._set_slot(extraction, slot, answer, f"user answer (clarification round {round_no})")

    @staticmethod
    def _set_slot(extraction: SlotExtraction, name: str, value: str, evidence: str) -> None:
        for slot in extraction.slots:
            if slot.name == name:
                slot.value = value
                slot.evidence = evidence
                return
        extraction.slots.append(ExtractedSlot(name=name, value=value, evidence=evidence))

    def _h_preflight(self, kernel: Kernel) -> StepOutcome | None:
        data = self._model_json(manifest_prompt(self._request), MANIFEST_SCHEMA)
        try:
            manifest = parse_manifest(json.dumps(data))
        except ManifestParseError as exc:
            raise _Halt(f"capability manifest rejected: {exc}") from exc
        failures = check_manifest(manifest, self.registry)
        kernel.declared({req.capability for req in manifest.requires})
        if failures:
            for failure in failures:
                self.user.notify(failure.message())
            raise _Halt("preflight found missing capabilities")
        self._record_tool(
            "preflight", f"{len(manifest.requires)} capability(ies) declared and available"
        )
        return None

    def _h_plan(self, kernel: Kernel) -> StepOutcome | None:
        data = self._model_json(plan_prompt(self._request, self._slots_text()), PLAN_SCHEMA)
        steps = [
            PlanStep(what=str(step.get("what", "")), files=[str(f) for f in step.get("files", [])])
            for step in data.get("steps", [])
            if isinstance(step, dict)
        ]
        self._plan = [s for s in steps if s.what]
        if not self._plan:
            raise _Halt("plan was empty")
        self.user.notify(f"plan: {'; '.join(s.what for s in self._plan)}")
        return None

    def _slots_text(self) -> str:
        assert self._extraction is not None
        return ", ".join(
            f"{s.name}={s.value}" for s in self._extraction.slots if s.value is not None
        )

    def _h_edit(self, kernel: Kernel) -> StepOutcome | None:
        if not self._plan:
            raise _Halt("edit step has no plan")
        for step in self._plan:
            for path in step.files:
                self._edit_path(kernel, path, step.what)
        return None

    def _edit_path(self, kernel: Kernel, path: str, what: str) -> None:
        before = self._read_for_edit(path)
        data = self._model_json(
            patch_prompt(path, before, what, self._repair_context), PATCH_SCHEMA
        )
        diff = str(data.get("diff", ""))
        raw_symbols = data.get("symbols_used", [])
        symbols = [str(s) for s in raw_symbols] if isinstance(raw_symbols, list) else []
        after = self.patch_tool.preview(path, diff)
        if after is None:
            self.user.notify(f"patch for {path} did not apply; step skipped")
            return
        findings = comment_findings(before, after)
        if findings:
            diff, after, findings = self._revise_for_hygiene(path, before, diff, findings)
        kernel.session.pending_comment_findings = [f"{f.kind} at line {f.line}" for f in findings]
        kernel.session.confirmed_symbols.update(
            s for s in symbols if lookup_symbol(before, s) is not None
        )
        if not self._passes_action_gates(kernel, path, diff, symbols):
            return
        if not self.user.approve_patch(path, diff, kernel.session.pending_comment_findings):
            kernel.session.pending_comment_findings = []
            self.user.notify(f"user rejected the patch for {path}")
            return
        try:
            self.patch_tool.apply(path, diff)
        except PatchError as exc:
            self.user.notify(str(exc))
            return
        kernel.session.pending_comment_findings = []
        self._record_tool(f"patch_apply {path}", "diff applied")
        applied = Path(self.settings.project_root, path).read_text(encoding="utf-8")
        kernel.session.confirmed_symbols.update(s.name for s in index_source(applied))

    def _read_for_edit(self, path: str) -> str:
        try:
            before = read_file(Path(self.settings.project_root, path))
        except FileNotFoundError:
            self._record_tool(f"file_read {path}", "new file (does not exist yet)")
            self.kernel.session.read_files.add(path)
            return ""
        self._record_tool(f"file_read {path}", f"{len(before.splitlines())} lines read")
        self.kernel.session.read_files.add(path)
        return before

    def _revise_for_hygiene(self, path: str, before: str, diff: str, findings):
        listed = "; ".join(f"{f.kind} at line {f.line}" for f in findings)
        self.user.notify(f"comment hygiene rejected the patch for {path}: {listed}")
        data = self._model_json(
            patch_prompt(path, before, "(revise the previous patch)")
            + f"\nThe previous diff was rejected by comment hygiene: {listed}. "
            "Return a corrected diff that removes the offending comments.",
            PATCH_SCHEMA,
        )
        revised = str(data.get("diff", ""))
        after = self.patch_tool.preview(path, revised)
        if after is None:
            return diff, self.patch_tool.preview(path, diff), findings
        return revised, after, comment_findings(before, after)

    def _passes_action_gates(
        self, kernel: Kernel, path: str, diff: str, symbols: list[str]
    ) -> bool:
        ctx = GateContext(
            action=f"apply_patch:{path}",
            path=path,
            symbols=symbols,
            capability="patch_apply",
            comment_findings=kernel.session.pending_comment_findings,
        )
        try:
            kernel.guard_action(ctx.action, ctx)
        except GateRefusal as refusal:
            self.user.notify(refusal.result.reason)
            choice = self.user.ask(
                "a gate refused this edit", ["override the gate", "skip this edit"]
            )
            if not choice.lower().startswith("override"):
                return False
            kernel.override(refusal.result.gate, ctx.action, "user override in the TUI")
        return True

    def _h_verify(self, kernel: Kernel) -> StepOutcome:
        outcomes: dict[str, bool] = {}
        reports: list[str] = []
        checks = (
            ("type_checker", self.settings.typecheck_command),
            ("test_runner", self.settings.test_command),
            ("linter", self.settings.lint_command),
        )
        for capability, command in checks:
            if not command.strip():
                continue
            result = run_check(command_from_str(command), str(self.settings.project_root))
            outcomes[capability] = result.passed
            status = "passed" if result.passed else "FAILED"
            reports.append(f"{capability} {status}:\n{result.output[-2000:]}")
            self._record_tool(capability, status)
        if not outcomes:
            raise _Halt("no checks are configured; the harness cannot verify this edit")
        kernel.session.check_outcomes = outcomes
        self._repair_context = "\n\n".join(reports)[-4000:]
        if all(outcomes.values()):
            return StepOutcome(Step.REPORT, "all checks passed")
        return StepOutcome(Step.EDIT, "checks failed; repair loop")

    def _h_report(self, kernel: Kernel) -> StepOutcome | None:
        data = self._model_json(claims_prompt(list(kernel.session.tool_results)), CLAIMS_SCHEMA)
        grounded: list[str] = []
        for claim in data.get("claims", []):
            if not isinstance(claim, dict):
                continue
            text = str(claim.get("text", ""))
            evidence = [str(e) for e in claim.get("evidence", [])]
            ctx = GateContext(action="claim:report", evidence=evidence)
            try:
                kernel.guard_action(ctx.action, ctx)
            except GateRefusal as refusal:
                self.user.notify(refusal.reason)
            else:
                grounded.append(text)
        self.user.notify("done: " + ("; ".join(grounded) or "(no grounded claims)"))
        return None
