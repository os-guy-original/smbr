"""The task suite: what a baseline run measures, loaded from JSON on disk.

Tasks are data, not code, so the suite stays frozen while everything around it
(prompts, tools, gates) is free to change.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class Task(BaseModel):
    """One coding task: a fixture directory, a prompt, and one check."""

    model_config = ConfigDict(extra="forbid")

    id: str
    difficulty: int = Field(ge=1, le=5)
    prompt: str
    setup: dict[str, str]
    run: str
    expect_files: list[str] = []

    @field_validator("id", "prompt", "run")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            msg = "must not be blank"
            raise ValueError(msg)
        return value


def load_suite(directory: Path) -> list[Task]:
    """Every ``*.json`` task in ``directory``, sorted by id.

    A broken file raises with its name so a suite edit is diagnosable without
    bisecting the whole run.
    """
    root = Path(directory)
    if not root.is_dir():
        msg = f"{root}: suite directory not found"
        raise ValueError(msg)
    tasks: list[Task] = []
    for path in sorted(root.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            msg = f"{path.name}: unreadable task JSON: {exc}"
            raise ValueError(msg) from exc
        try:
            tasks.append(Task.model_validate(raw))
        except ValidationError as exc:
            msg = f"{path.name}: invalid task: {exc}"
            raise ValueError(msg) from exc
    return sorted(tasks, key=lambda task: task.id)
