"""Writing an import to disk: review-first and atomic.

Everything lands in SMBR's own config shapes with ``enabled: false``,
because the user reviews what an import adds before it runs. Writes go
through a temp file and a rename, so a crash or a bad path can never
leave a half-written config behind.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from smbr.imports.discovery import DiscoveredServer


@dataclass
class WriteReport:
    """What an import write did, for the CLI to print."""

    target: Path
    added: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def wrote(self) -> bool:
        return bool(self.added or self.updated) and not self.dry_run


def load_smbr_mcp(path: Path) -> dict:
    """The existing SMBR MCP config, or an empty one."""
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def merge_servers(
    servers: list[DiscoveredServer],
    target: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> WriteReport:
    """Merge foreign servers into SMBR's config as disabled entries.

    An existing entry is never silently replaced: same command/args is
    "unchanged", a different shape is a conflict the user resolves with
    --force, and everything imported new starts disabled.
    """
    report = WriteReport(target=target, dry_run=dry_run)
    doc = load_smbr_mcp(target)
    existing = doc.get("mcpServers")
    merged: dict = dict(existing) if isinstance(existing, dict) else {}
    for server in servers:
        entry = _entry_for(server)
        current = merged.get(server.name)
        if current is None:
            merged[server.name] = entry
            report.added.append(server.name)
        elif _same_server(current, entry):
            report.unchanged.append(server.name)
        elif force:
            merged[server.name] = entry
            report.updated.append(server.name)
        else:
            report.conflicts.append(server.name)
    if (report.added or report.updated) and not dry_run:
        doc["mcpServers"] = merged
        write_json_atomic(target, doc)
    return report


def _entry_for(server: DiscoveredServer) -> dict:
    return {
        "command": server.command,
        "args": list(server.args),
        "env": dict(server.env),
        "timeout": int(server.timeout),
        "enabled": False,  # the user reviews and enables, per the design doc
    }


def _same_server(current: object, entry: dict) -> bool:
    if not isinstance(current, dict):
        return False
    return all(current.get(key) == value for key, value in entry.items() if key != "enabled")


def write_json_atomic(path: Path, payload: dict) -> None:
    """Write JSON via a temp file in the same directory, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=path.name, suffix=".tmp", delete=False
    ) as handle:
        name = handle.name
        try:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            os.replace(name, path)
        except BaseException:
            Path(name).unlink(missing_ok=True)
            raise
