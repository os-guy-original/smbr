"""Clarification gate: mechanical slot filling instead of hopeful asking.

The harness holds the schema of what a task type needs. The model extracts
slots into JSON (``null`` for anything unstated) and must back every filled
slot with a quote of the user's words or a tool-result id. If any required
slot is still null, planning is blocked until the mandatory question phase
fills it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, field_validator


class TaskType(StrEnum):
    NEW_APP = "new_app"
    MODIFY_CODE = "modify_code"
    FIX_BUG = "fix_bug"
    EXPLAIN = "explain"


class SlotSchema(BaseModel):
    name: str
    description: str = ""


# Required slots per task type, from the design document.
TASK_SLOTS: dict[TaskType, tuple[str, ...]] = {
    TaskType.NEW_APP: ("purpose", "language", "framework", "platform", "persistence", "scope"),
    TaskType.MODIFY_CODE: ("objective", "location", "scope"),
    TaskType.FIX_BUG: ("symptom", "location", "expected"),
    TaskType.EXPLAIN: ("subject", "depth"),
}

# Never ask more than this per round; over-asking is a failure mode too.
MAX_QUESTIONS_PER_ROUND = 3


class ExtractedSlot(BaseModel):
    name: str
    value: str | None = None
    evidence: str | None = None

    @field_validator("name")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v.strip():
            msg = "slot name must not be empty"
            raise ValueError(msg)
        return v


class SlotExtraction(BaseModel):
    task_type: TaskType
    slots: list[ExtractedSlot]


def missing_slots(task_type: TaskType, extraction: SlotExtraction) -> list[str]:
    """Required slots that are null, in schema order (most blocking first)."""
    filled = {s.name for s in extraction.slots if s.value is not None}
    return [name for name in TASK_SLOTS[task_type] if name not in filled]


def ungrounded_slots(extraction: SlotExtraction) -> list[str]:
    """Filled slots with no supporting evidence (no user quote, no tool id).

    A filled-but-ungrounded slot is treated like an unfilled one: the harness
    would otherwise be trusting a guess.
    """
    return [
        s.name for s in extraction.slots if s.value is not None and not (s.evidence or "").strip()
    ]


def plan_questions(
    task_type: TaskType,
    extraction: SlotExtraction,
    *,
    cap: int = MAX_QUESTIONS_PER_ROUND,
) -> list[str]:
    """Which slots to ask about this round: missing first, then ungrounded."""
    blocking = missing_slots(task_type, extraction)
    soft = [n for n in ungrounded_slots(extraction) if n not in blocking]
    return (blocking + soft)[:cap]


def needs_clarification(task_type: TaskType, extraction: SlotExtraction) -> bool:
    """True when the mandatory question phase must run before planning.

    A filled-but-ungrounded slot blocks too: the harness would otherwise be
    trusting a guess.
    """
    return bool(missing_slots(task_type, extraction) or ungrounded_slots(extraction))
