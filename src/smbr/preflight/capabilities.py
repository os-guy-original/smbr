"""Capability vocabulary and the three preflight failure types.

The capability names are a fixed enum so that grammar-constrained decoding can
only ever produce names the harness knows — plus one explicit
``unknown_capability`` value, which makes "I need something that does not
exist" a first-class output instead of a hallucination.
"""

from __future__ import annotations

from enum import StrEnum


class Capability(StrEnum):
    FILE_READ = "file_read"
    CODE_SEARCH = "code_search"
    SYMBOL_LOOKUP = "symbol_lookup"
    PATCH_APPLY = "patch_apply"
    TEST_RUNNER = "test_runner"
    LINTER = "linter"
    TYPE_CHECKER = "type_checker"
    GIT = "git"
    DOCS_LOOKUP = "docs_lookup"
    UNKNOWN_CAPABILITY = "unknown_capability"


class FailureType(StrEnum):
    NOT_INSTALLED = "not_installed"
    UNHEALTHY = "unhealthy"
    NOT_PERMITTED = "not_permitted"


# Harness-owned warning templates, one per failure type.
FAILURE_TEMPLATES: dict[FailureType, str] = {
    FailureType.NOT_INSTALLED: (
        "Preflight stopped: {capability} is not installed. "
        "Install or configure it, or choose a fallback explicitly."
    ),
    FailureType.UNHEALTHY: (
        "Preflight stopped: {capability} exists but failed its health check ({detail})."
    ),
    FailureType.NOT_PERMITTED: (
        "Preflight stopped: {capability} exists but policy blocks it ({detail})."
    ),
}


class CapabilityFailure:
    """A capability the harness verified and found unusable."""

    def __init__(self, capability: Capability, failure: FailureType, detail: str = "") -> None:
        self.capability = capability
        self.failure = failure
        self.detail = detail

    def message(self) -> str:
        """The harness-written warning shown to the user in the TUI."""
        return FAILURE_TEMPLATES[self.failure].format(
            capability=self.capability.value, detail=self.detail or "no detail"
        )

    def __repr__(self) -> str:
        return f"CapabilityFailure({self.capability.value}, {self.failure.value})"
