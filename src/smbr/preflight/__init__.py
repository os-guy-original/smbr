"""Preflight: capability vocabulary, manifest parsing, registry checking."""

from smbr.preflight.capabilities import (
    FAILURE_TEMPLATES,
    Capability,
    CapabilityFailure,
    FailureType,
)
from smbr.preflight.manifest import (
    ManifestParseError,
    PreflightManifest,
    Requirement,
    check_manifest,
    parse_manifest,
)

__all__ = [
    "FAILURE_TEMPLATES",
    "Capability",
    "CapabilityFailure",
    "FailureType",
    "ManifestParseError",
    "PreflightManifest",
    "Requirement",
    "check_manifest",
    "parse_manifest",
]
