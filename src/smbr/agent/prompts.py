"""Constrained-JSON schemas and prompt builders for every model step.

Every schema here is fixed by the harness. The enums mirror the Capability
and TaskType vocabularies so grammar-constrained decoding can only produce
names the harness knows, and `null`/`unknown_capability` are always available
as explicit answers instead of hallucinations.
"""

from __future__ import annotations

from smbr.clarify.slots import TaskType
from smbr.preflight.capabilities import Capability

TASK_TYPES: list[str] = [t.value for t in TaskType]
CAPABILITIES: list[str] = [c.value for c in Capability]

INTAKE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "task_type": {"type": "string", "enum": TASK_TYPES},
        "slots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": ["string", "null"]},
                    "evidence": {"type": ["string", "null"]},
                },
                "required": ["name", "value", "evidence"],
            },
        },
    },
    "required": ["task_type", "slots"],
}

SLOT_QUESTION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["question", "options"],
}

MANIFEST_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "task": {"type": "string"},
        "requires": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "capability": {"type": "string", "enum": CAPABILITIES},
                    "why": {"type": "string"},
                },
                "required": ["capability", "why"],
            },
        },
    },
    "required": ["task", "requires"],
}

PLAN_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "what": {"type": "string"},
                    "files": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["what", "files"],
            },
        }
    },
    "required": ["steps"],
}

PATCH_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "diff": {"type": "string"},
        "symbols_used": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["path", "diff", "symbols_used"],
}

CLAIMS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "evidence"],
            },
        }
    },
    "required": ["claims"],
}


def intake_prompt(request: str) -> str:
    return (
        "Classify this coding request and extract the task slots. A slot value "
        "may only be set when you can quote the user's words or cite observed "
        "project state as evidence; otherwise use null.\n\n"
        f"Request: {request}"
    )


def slot_question_prompt(slot: str, task_type: str) -> str:
    return (
        f"Phrase one multiple-choice question that fills the '{slot}' slot of a "
        f"'{task_type}' task, and propose up to four sensible options."
    )


def manifest_prompt(request: str) -> str:
    return (
        "Declare every capability this task needs from the harness toolset. "
        "Use unknown_capability if you need something the enum lacks.\n\n"
        f"Request: {request}"
    )


def plan_prompt(request: str, slots: str) -> str:
    return (
        "Decompose this task into the smallest checkable steps, naming the "
        "files each step touches.\n\n"
        f"Request: {request}\nSlots: {slots}"
    )


def patch_prompt(path: str, before: str, step: str, repair: str = "") -> str:
    repair_block = f"\nRepair feedback from the last verification:\n{repair}\n" if repair else ""
    return (
        f"Produce a minimal unified diff for {path} that accomplishes: {step}. "
        "Never rewrite the whole file when a small diff suffices.\n"
        f"{repair_block}\nCurrent contents:\n{before}"
    )


def claims_prompt(evidence_ids: list[str]) -> str:
    ids = "\n".join(f"- {e}" for e in evidence_ids) or "- (none)"
    return (
        "Summarize what was done. Every claim must cite at least one of these "
        f"tool result ids:\n{ids}"
    )
