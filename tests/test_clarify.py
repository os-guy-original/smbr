"""Clarification gate: missing slots block planning, questions stay bounded."""

from __future__ import annotations

from smbr.clarify import (
    ExtractedSlot,
    SlotExtraction,
    TaskType,
    missing_slots,
    needs_clarification,
    plan_questions,
    ungrounded_slots,
)


def _extraction(task_type: TaskType, **slots) -> SlotExtraction:
    return SlotExtraction(
        task_type=task_type,
        slots=[ExtractedSlot(name=k, value=v, evidence=ev) for k, (v, ev) in slots.items()],
    )


def test_bare_app_request_is_missing_slots() -> None:
    extraction = _extraction(
        TaskType.NEW_APP,
        purpose=("build a productivity app", "user: 'build a productivity app'"),
    )
    missing = missing_slots(TaskType.NEW_APP, extraction)
    assert missing == ["language", "framework", "platform", "persistence", "scope"]
    assert needs_clarification(TaskType.NEW_APP, extraction)


def test_fully_specified_request_asks_nothing() -> None:
    extraction = _extraction(
        TaskType.NEW_APP,
        purpose=("todo app", "user said it"),
        language=("python", "package.json detected"),
        framework=("fastapi", "package.json detected"),
        platform=("cli", "user said it"),
        persistence=("sqlite", "user said it"),
        scope=("single user", "user said it"),
    )
    assert missing_slots(TaskType.NEW_APP, extraction) == []
    assert ungrounded_slots(extraction) == []
    assert not needs_clarification(TaskType.NEW_APP, extraction)
    assert plan_questions(TaskType.NEW_APP, extraction) == []


def test_filled_but_ungrounded_slot_still_asks() -> None:
    extraction = _extraction(
        TaskType.NEW_APP,
        purpose=("todo app", "user said it"),
        language=("python", ""),  # no evidence: treat as a guess
        framework=("fastapi", "package.json"),
        platform=("cli", "user said it"),
        persistence=("sqlite", "user said it"),
        scope=("single user", "user said it"),
    )
    assert missing_slots(TaskType.NEW_APP, extraction) == []
    assert ungrounded_slots(extraction) == ["language"]
    assert needs_clarification(TaskType.NEW_APP, extraction)  # grounded claims apply to slots too
    assert plan_questions(TaskType.NEW_APP, extraction) == ["language"]


def test_questions_capped_per_round() -> None:
    extraction = SlotExtraction(task_type=TaskType.NEW_APP, slots=[])
    questions = plan_questions(TaskType.NEW_APP, extraction)
    assert len(questions) == 3  # never an interrogation
    assert questions == ["purpose", "language", "framework"]


def test_tiny_request_needs_no_questions() -> None:
    extraction = _extraction(
        TaskType.FIX_BUG,
        symptom=("null check on line 40 fails", "user: 'Fix the null check on line 40'"),
        location=("src/app.py:40", "tool: read src/app.py"),
        expected=("no crash on empty input", "user: 'Fix the null check on line 40'"),
    )
    assert not needs_clarification(TaskType.FIX_BUG, extraction)
