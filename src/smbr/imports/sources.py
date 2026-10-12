"""The agents SMBR knows how to read, and where they keep their configs.

Paths are conventional locations for each tool's configuration; the
reader auto-detects the wrapper (``mcpServers`` / ``servers`` /
``mcp``), so a file from an agent not named here still imports when
passed with ``--path``. Nothing here assumes a vendor's schema — the
origin in every report is the file path itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from smbr.imports.discovery import home


@dataclass(frozen=True)
class SourceSpec:
    """One agent's config locations."""

    label: str
    paths: tuple[Path, ...] = ()
    skill_roots: tuple[Path, ...] = ()
    mcp_key: str = ""  # the wrapper key this agent uses, when known


def named_sources(project_root: Path | None = None) -> dict[str, SourceSpec]:
    """Every known source, resolved against a project root and $HOME."""
    root = Path(project_root) if project_root is not None else Path.cwd()
    config_home = Path(os_environ("XDG_CONFIG_HOME", str(home() / ".config")))
    return {
        "opencode": SourceSpec(
            label="OpenCode",
            paths=(
                config_home / "opencode" / "opencode.json",
                config_home / "opencode" / "opencode.jsonc",
                root / "opencode.json",
                root / "opencode.jsonc",
                root / ".opencode" / "opencode.json",
                root / ".opencode" / "opencode.jsonc",
            ),
            skill_roots=(
                config_home / "opencode" / "skills",
                root / ".opencode" / "skills",
            ),
            mcp_key="mcp",
        ),
        "claude": SourceSpec(
            label="Claude Code",
            paths=(
                root / ".mcp.json",
                home() / ".claude.json",
            ),
            skill_roots=(
                root / ".claude" / "skills",
                home() / ".claude" / "skills",
            ),
            mcp_key="mcpServers",
        ),
        "vscode": SourceSpec(
            label="VS Code / Copilot",
            paths=(
                root / ".vscode" / "mcp.json",
                home() / ".copilot" / "mcp-config.json",
            ),
            mcp_key="servers",
        ),
        # Conventional homes of the portable mcpServers format. These are
        # probed because the shape is shared; the reader does not depend on
        # any particular agent following it.
        "portable": SourceSpec(
            label="portable mcpServers configs",
            paths=(
                root / ".cursor" / "mcp.json",
                home() / ".codeium" / "windsurf" / "mcp_config.json",
            ),
        ),
    }


def os_environ(name: str, default: str) -> str:
    import os

    return os.environ.get(name) or default


def source_paths(project_root: Path | None = None) -> list[Path]:
    """Every known config path, for a blind scan."""
    paths: list[Path] = []
    for spec in named_sources(project_root).values():
        paths.extend(p for p in spec.paths if p not in paths)
    return paths


def skill_roots(project_root: Path | None = None) -> list[Path]:
    """Every known skill root, for a blind scan."""
    roots: list[Path] = []
    for spec in named_sources(project_root).values():
        roots.extend(r for r in spec.skill_roots if r not in roots)
    return roots
