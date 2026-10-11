"""The decision layer: bounded judgments from a swappable provider.

Decision models (Jev, Laya, Kev, SemIf) don't generate text — they answer a
choice, a score, or a yes/no probability that the harness can threshold. That
fits the no-guessing principle: the output is a value, never prose. The
always-available fallback is the main small model answering in constrained
JSON, and the layer can be turned off entirely, in which case SMBR asks the
user every time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Protocol

# Below this, the router routes to the user — never to a default guess.
LOW_CONFIDENCE = 0.5


@dataclass(frozen=True)
class Decision:
    """One bounded judgment with its confidence."""

    value: str | float | bool
    confidence: float
    provider: str

    @property
    def trustworthy(self) -> bool:
        return self.confidence >= LOW_CONFIDENCE


class CompletionClient(Protocol):
    """A small model that can answer one constrained-JSON question."""

    def complete_json(self, prompt: str, schema: dict) -> dict: ...


class DecisionProvider(Protocol):
    name: str

    def choice(self, question: str, options: tuple[str, ...]) -> Decision: ...

    def score(self, subject: str, question: str) -> Decision: ...

    def boolean(self, question: str) -> Decision: ...


@dataclass(frozen=True)
class DecisionProfile:
    """Editable config consulted when the user says 'you decide'."""

    defaults: dict[str, str]  # e.g. {"web backend": "Python, FastAPI, SQLite"}

    def lookup(self, key: str) -> str | None:
        return self.defaults.get(key)


class DisabledDecisionProvider:
    """The layer turned off: every judgment is explicitly low-confidence."""

    name = "disabled"

    def choice(self, question: str, options: tuple[str, ...]) -> Decision:
        return Decision(options[0] if options else "", 0.0, self.name)

    def score(self, subject: str, question: str) -> Decision:
        return Decision(0.0, 0.0, self.name)

    def boolean(self, question: str) -> Decision:
        return Decision(False, 0.0, self.name)


class ConstrainedJsonProvider:
    """The fallback provider: the main small model in constrained JSON.

    The model answers with exactly the fields the schema allows; anything that
    fails validation is treated as 'no answer' (confidence 0.0), not as a
    best-effort guess.
    """

    name = "constrained_json"

    _BOOL_SCHEMA: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "answer": {"type": "boolean"},
            "confidence": {"type": "number"},
        },
        "required": ["answer", "confidence"],
    }

    def __init__(self, client: CompletionClient) -> None:
        self.client = client

    def choice(self, question: str, options: tuple[str, ...]) -> Decision:
        schema = {
            "type": "object",
            "properties": {
                "choice": {"type": "string", "enum": list(options)},
                "confidence": {"type": "number"},
            },
            "required": ["choice", "confidence"],
        }
        try:
            data = self.client.complete_json(question, schema)
            choice = str(data["choice"])
            confidence = float(data["confidence"])
        except Exception:  # a failed backend means 'no answer', never a guess
            return Decision(options[0] if options else "", 0.0, self.name)
        if choice not in options:
            return Decision(options[0] if options else "", 0.0, self.name)
        return Decision(choice, min(max(confidence, 0.0), 1.0), self.name)

    def score(self, subject: str, question: str) -> Decision:
        schema = {
            "type": "object",
            "properties": {"score": {"type": "number"}, "confidence": {"type": "number"}},
            "required": ["score", "confidence"],
        }
        try:
            data = self.client.complete_json(f"{question}\nSubject: {subject}", schema)
            score = float(data["score"])
            confidence = float(data["confidence"])
        except Exception:  # a failed backend means 'no answer', never a guess
            return Decision(0.0, 0.0, self.name)
        return Decision(min(max(score, 0.0), 1.0), min(max(confidence, 0.0), 1.0), self.name)

    def boolean(self, question: str) -> Decision:
        try:
            data = self.client.complete_json(question, self._BOOL_SCHEMA)
            answer = bool(data["answer"])
            confidence = float(data["confidence"])
        except Exception:  # a failed backend means 'no answer', never a guess
            return Decision(False, 0.0, self.name)
        return Decision(answer, min(max(confidence, 0.0), 1.0), self.name)


class DecisionRouter:
    """Routes bounded judgments and flags when the user must be asked."""

    def __init__(self, provider: DecisionProvider, profile: DecisionProfile | None = None) -> None:
        self.provider = provider
        self.profile = profile

    def boolean(self, question: str) -> Decision:
        return self.provider.boolean(question)

    def needs_user(self, decision: Decision) -> bool:
        """Low confidence always routes to asking the user."""
        return not decision.trustworthy

    def decide_for_user(self, key: str) -> str | None:
        """Consult the profile when the user delegated ('you decide')."""
        return self.profile.lookup(key) if self.profile else None
