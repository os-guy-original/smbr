"""Preflight: strict manifests, hallucination rejection, three failure types."""

from __future__ import annotations

import json

import pytest

from smbr.preflight import (
    Capability,
    CapabilityFailure,
    FailureType,
    ManifestParseError,
    check_manifest,
    parse_manifest,
)
from smbr.tools.registry import ToolHealth, ToolRegistry

MANIFEST = json.dumps(
    {
        "task": "add input validation to signup form",
        "requires": [
            {"capability": "file_read", "why": "inspect current form code"},
            {"capability": "symbol_lookup", "why": "find validation helpers"},
            {"capability": "test_runner", "why": "verify the change"},
        ],
    }
)


def test_parse_valid_manifest() -> None:
    manifest = parse_manifest(MANIFEST)
    assert manifest.task == "add input validation to signup form"
    assert [r.capability for r in manifest.requires] == [
        Capability.FILE_READ,
        Capability.SYMBOL_LOOKUP,
        Capability.TEST_RUNNER,
    ]


def test_rejects_non_json() -> None:
    with pytest.raises(ManifestParseError):
        parse_manifest("not json at all")


def test_rejects_hallucinated_capability() -> None:
    payload = json.dumps(
        {"task": "x", "requires": [{"capability": "quantum_validation", "why": "..."}]}
    )
    with pytest.raises(ManifestParseError):
        parse_manifest(payload)


def test_unknown_capability_is_a_first_class_declaration() -> None:
    payload = json.dumps(
        {
            "task": "x",
            "requires": [{"capability": "unknown_capability", "why": "need something else"}],
        }
    )
    manifest = parse_manifest(payload)
    failures = check_manifest(manifest, ToolRegistry())
    assert len(failures) == 1
    assert failures[0].failure is FailureType.NOT_INSTALLED


class _OkTool:
    capability = Capability.FILE_READ
    name = "file_read"

    def health(self) -> ToolHealth:
        return ToolHealth.ok(self.capability)


class _SickTool:
    capability = Capability.LINTER
    name = "linter"

    def health(self) -> ToolHealth:
        return ToolHealth.broken(self.capability, "ruff crashed on startup")


def test_three_failure_types_have_distinct_messages() -> None:
    registry = ToolRegistry()
    registry.register(_OkTool())
    registry.register(_SickTool())

    payload = json.dumps(
        {
            "task": "x",
            "requires": [
                {"capability": "file_read", "why": "read"},  # fine
                {"capability": "git", "why": "history"},  # not installed
                {"capability": "linter", "why": "lint"},  # unhealthy
            ],
        }
    )
    manifest = parse_manifest(payload)
    failures = check_manifest(manifest, registry)
    by_cap = {f.capability: f for f in failures}
    assert set(by_cap) == {Capability.GIT, Capability.LINTER}
    assert by_cap[Capability.GIT].failure is FailureType.NOT_INSTALLED
    assert by_cap[Capability.LINTER].failure is FailureType.UNHEALTHY

    # messages come from harness templates and name the capability
    assert "git" in by_cap[Capability.GIT].message()
    assert "health check" in by_cap[Capability.LINTER].message()


def test_not_permitted_when_policy_blocks() -> None:
    registry = ToolRegistry()
    registry.register(_OkTool())
    payload = json.dumps({"task": "x", "requires": [{"capability": "file_read", "why": "read"}]})
    manifest = parse_manifest(payload)
    failures = check_manifest(manifest, registry, permitted=frozenset({Capability.TEST_RUNNER}))
    assert len(failures) == 1
    assert failures[0].failure is FailureType.NOT_PERMITTED
    assert "policy" in failures[0].message()


def test_tool_protocol_accepts_registry() -> None:
    registry = ToolRegistry()
    tool = _OkTool()
    registry.register(tool)
    assert registry.check(Capability.FILE_READ).available
    assert not registry.check(Capability.GIT).installed


def test_capability_failure_is_capability_failure() -> None:
    failure = CapabilityFailure(Capability.GIT, FailureType.NOT_INSTALLED)
    assert failure.capability is Capability.GIT
