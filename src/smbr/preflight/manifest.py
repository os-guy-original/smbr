"""Preflight manifest parsing and capability checking.

Split of responsibility, exactly as the design document demands: the model
only *declares* what it needs, as JSON. Whether the tool actually exists is
decided by this deterministic code, because a model asked whether a tool
exists can hallucinate the answer.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from smbr.preflight.capabilities import Capability, CapabilityFailure, FailureType

if TYPE_CHECKING:
    from smbr.tools.registry import ToolHealth, ToolRegistry


class Requirement(BaseModel):
    """One declared need: the capability and the model's reason for it."""

    capability: Capability
    why: str = ""


class PreflightManifest(BaseModel):
    """The model's declaration of what the task requires."""

    task: str
    requires: list[Requirement]


class ManifestParseError(ValueError):
    """The declaration was not valid constrained JSON."""


def parse_manifest(payload: str | bytes) -> PreflightManifest:
    """Parse a strict-JSON manifest. Raises ManifestParseError on garbage.

    ``capability`` values are validated against the Capability enum, so a
    hallucinated tool name cannot enter the system.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ManifestParseError(f"manifest is not valid JSON: {exc}") from exc
    try:
        return PreflightManifest.model_validate(data)
    except ValidationError as exc:
        raise ManifestParseError(f"manifest failed schema validation: {exc}") from exc


def check_manifest(
    manifest: PreflightManifest,
    registry: ToolRegistry,
    *,
    permitted: frozenset[Capability] | None = None,
) -> list[CapabilityFailure]:
    """Verify every declared capability against the real tool registry.

    ``permitted`` overrides the policy check: capabilities outside the set fail
    with NOT_PERMITTED (the "tool exists but policy blocks it" case).
    """
    failures: list[CapabilityFailure] = []
    for req in manifest.requires:
        if req.capability is Capability.UNKNOWN_CAPABILITY:
            failures.append(
                CapabilityFailure(
                    req.capability,
                    FailureType.NOT_INSTALLED,
                    "model declared a capability that does not exist",
                )
            )
            continue
        if permitted is not None and req.capability not in permitted:
            failures.append(
                CapabilityFailure(req.capability, FailureType.NOT_PERMITTED, "blocked by policy")
            )
            continue
        failures.extend(_health_failures(registry.check(req.capability)))
    return failures


def _health_failures(health: ToolHealth) -> list[CapabilityFailure]:
    if health.available:
        return []
    failure = FailureType.NOT_INSTALLED if not health.installed else FailureType.UNHEALTHY
    return [CapabilityFailure(health.capability, failure, health.detail)]
