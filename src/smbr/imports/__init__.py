"""Importing MCP servers and skills from other agents.

Every reader normalises a foreign config into SMBR's shapes; the
wrapper key is auto-detected, so an agent we have never seen still
imports when its file is passed with ``--path``. Imports land
disabled and inert: the user reviews what an import adds before
anything runs, which is the design doc's security rule for
untrusted content.
"""

from smbr.imports.discovery import (
    DiscoveredServer,
    SkillFound,
    SkippedServer,
    SourceResult,
    discover_mcp,
    discover_skills,
    parse_server,
    read_json_tolerant,
    server_map,
    skill_description,
)
from smbr.imports.mcp_config import WriteReport, merge_servers, write_json_atomic
from smbr.imports.skills import SkillImportReport, import_skills, load_manifest
from smbr.imports.sources import named_sources, skill_roots, source_paths

__all__ = [
    "DiscoveredServer",
    "SkillFound",
    "SkillImportReport",
    "SkippedServer",
    "SourceResult",
    "WriteReport",
    "discover_mcp",
    "discover_skills",
    "import_skills",
    "load_manifest",
    "merge_servers",
    "named_sources",
    "parse_server",
    "read_json_tolerant",
    "server_map",
    "skill_description",
    "skill_roots",
    "source_paths",
    "write_json_atomic",
]
