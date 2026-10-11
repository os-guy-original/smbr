"""The ports the agent uses to reach the user.

The kernel never talks to a human directly; interrupts that need the user go
through this port, so the same loop runs under the TUI, the terminal, or a
recording stub in tests.
"""

from __future__ import annotations

from typing import Protocol


class UserPort(Protocol):
    """Everything the agent may ask of the user."""

    def ask(self, question: str, options: list[str]) -> str:
        """Multiple choice with a default; returns the chosen option or free text."""

    def notify(self, message: str) -> None:
        """A harness-authored message (gate result, warning, tool log)."""

    def approve_patch(self, path: str, diff: str, findings: list[str]) -> bool:
        """Diff approval before anything is applied to the working tree."""


class CliUser:
    """Terminal port: prompts on stdin, harness messages on stdout."""

    def ask(self, question: str, options: list[str]) -> str:
        print(f"\n[ask] {question}")
        for i, option in enumerate(options, start=1):
            print(f"  {i}. {option}")
        try:
            raw = input("> ").strip()
        except EOFError:
            return options[0] if options else ""
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        return raw or (options[0] if options else "")

    def notify(self, message: str) -> None:
        print(f"[harness] {message}")

    def approve_patch(self, path: str, diff: str, findings: list[str]) -> bool:
        print(f"\n[diff] {path}")
        print(diff)
        for finding in findings:
            print(f"[comment hygiene] {finding}")
        try:
            return input("apply? [y/N] ").strip().lower() in {"y", "yes"}
        except EOFError:
            return False


class RecordingUser:
    """Scripted port for tests: answers pop from a queue; messages are kept."""

    def __init__(self, answers: list[str] | None = None, approve: bool = True) -> None:
        self.answers = list(answers or [])
        self.approve = approve
        self.messages: list[str] = []
        self.asked: list[tuple[str, list[str]]] = []
        self.approved: list[tuple[str, str]] = []

    def ask(self, question: str, options: list[str]) -> str:
        self.asked.append((question, options))
        if self.answers:
            return self.answers.pop(0)
        return options[0] if options else ""

    def notify(self, message: str) -> None:
        self.messages.append(message)

    def approve_patch(self, path: str, diff: str, findings: list[str]) -> bool:
        self.approved.append((path, diff))
        return self.approve
