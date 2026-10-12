"""Discovery: find MCP servers and skills in other agents' configs.

Every adapter reads a file the agent already has and normalises it to
SMBR's shapes. The wrapper key is auto-detected (``mcpServers``,
``servers``, ``mcp``), so a config we have never seen still imports as
long as it follows the common conventions — and anything that does not
fit is reported, never silently dropped or guessed at.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

#: Keys that hold a server map in other agents' configs, in probe order.
WRAPPER_KEYS = ("mcpServers", "servers", "mcp")

#: Entry markers that mean "this server is remote", per provider docs.
REMOTE_TYPES = {"http", "streamable-http", "sse", "ws", "remote"}


@dataclass(frozen=True)
class DiscoveredServer:
    """A stdio server found in a foreign config, ready to import."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0
    origin: str = ""  # human-readable source, e.g. "claude: /path/.mcp.json"


@dataclass(frozen=True)
class SkippedServer:
    """A config entry we did not import, and why — never silently."""

    name: str
    origin: str
    reason: str


@dataclass
class SourceResult:
    """What one config file offered: importable servers and skips."""

    origin: str
    servers: list[DiscoveredServer] = field(default_factory=list)
    skipped: list[SkippedServer] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class SkillFound:
    """A skill folder found in a foreign agent's skill directory."""

    name: str
    path: Path  # the directory holding SKILL.md
    origin: str


def read_json_tolerant(path: Path) -> dict | None:
    """Parse JSON or JSONC (comments, trailing commas), or None.

    OpenCode and VS Code both accept comments in their MCP configs, so
    the readers strip them rather than fail on a valid file.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_json_tolerant(text)


def parse_json_tolerant(text: str) -> dict | None:
    """JSONC-tolerant parse; returns None when the text is not an object."""
    stripped = strip_jsonc(text)
    try:
        doc = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return doc if isinstance(doc, dict) else None


def strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments and trailing commas outside strings."""
    out: list[str] = []
    i = 0
    in_string = False
    escaped = False
    while i < len(text):
        char = text[i]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            i += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            i += 1
            continue
        if char == "/" and i + 1 < len(text) and text[i + 1] == "/":
            i += 2
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        if char == "/" and i + 1 < len(text) and text[i + 1] == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(char)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def server_map(doc: dict, project_root: Path | None = None) -> tuple[dict, str]:
    """The server map in a foreign config, and which key held it.

    Handles the three wrapper conventions plus Claude's user scope,
    which nests servers under ``projects.<cwd>``.
    """
    for key in WRAPPER_KEYS:
        value = doc.get(key)
        if isinstance(value, dict) and _looks_like_servers(value):
            return value, key
    projects = doc.get("projects")
    if isinstance(projects, dict):
        # Claude's user scope: projects keyed by absolute project path.
        if project_root is not None:
            scoped = projects.get(str(project_root))
            if isinstance(scoped, dict):
                found = _wrapper_in(scoped)
                if found is not None:
                    return found, "projects.mcpServers"
        # Fall back to a project scope holding exactly one path.
        for scoped in projects.values():
            if isinstance(scoped, dict):
                found = _wrapper_in(scoped)
                if found is not None:
                    return found, "projects.mcpServers"
    return {}, ""


def _wrapper_in(scoped: dict) -> dict | None:
    for key in WRAPPER_KEYS:
        value = scoped.get(key)
        if isinstance(value, dict) and _looks_like_servers(value):
            return value
    return None


def _looks_like_servers(value: dict) -> bool:
    """True when the map holds server entries, not unrelated settings."""
    return bool(value) and all(isinstance(v, dict) for v in value.values())


def parse_server(
    name: str, spec: object, origin: str
) -> tuple[DiscoveredServer | None, SkippedServer | None]:
    """Normalise one foreign entry to SMBR's stdio server shape."""
    if not isinstance(spec, dict):
        return None, SkippedServer(name, origin, "entry is not an object")
    if spec.get("enabled") is False:
        return None, SkippedServer(name, origin, "disabled in the source config")
    kind = spec.get("type")
    is_remote_kind = isinstance(kind, str) and kind.lower() in REMOTE_TYPES
    if is_remote_kind or "url" in spec:
        return None, SkippedServer(
            name, origin, "remote transport (http/sse/ws); SMBR's MCP client is stdio-only"
        )
    command = spec.get("command")
    args: list[str] = []
    if isinstance(command, list):  # OpenCode's local servers use an argv array
        argv = [str(part) for part in command]
        if not argv:
            return None, SkippedServer(name, origin, "empty command array")
        command, args = argv[0], argv[1:]
    elif isinstance(command, str):
        if not command.strip():
            return None, SkippedServer(name, origin, "blank command")
        raw_args = spec.get("args", [])
        if not isinstance(raw_args, list):
            return None, SkippedServer(name, origin, "'args' is not a list")
        args = [str(a) for a in raw_args]
    else:
        return None, SkippedServer(name, origin, "no 'command'")
    raw_env = spec.get("env") or spec.get("environment") or {}
    if not isinstance(raw_env, dict):
        return None, SkippedServer(name, origin, "'env' is not an object")
    env = {str(k): _env_value(v) for k, v in raw_env.items() if _env_value(v) is not None}
    timeout = _entry_timeout(spec)
    server = DiscoveredServer(
        name=name,
        command=command,
        args=tuple(args),
        env=env,
        timeout=timeout,
        origin=origin,
    )
    return server, None


def _env_value(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _entry_timeout(spec: dict) -> float:
    raw = spec.get("timeout")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
        return float(raw) / 1000.0 if raw >= 1000 else float(raw)
    return 30.0


def discover_mcp(paths: list[Path], project_root: Path | None = None) -> list[SourceResult]:
    """Read every path and report what each one offers."""
    results: list[SourceResult] = []
    for path in paths:
        origin = str(path)
        if not path.is_file():
            continue
        doc = read_json_tolerant(path)
        if doc is None:
            results.append(SourceResult(origin=origin, error="not JSON/JSONC (or unreadable)"))
            continue
        servers, _wrapper = server_map(doc, project_root)
        if not servers:
            results.append(
                SourceResult(origin=origin, error="no known MCP server map in this file")
            )
            continue
        result = SourceResult(origin=origin)
        for name, spec in servers.items():
            server, skipped = parse_server(str(name), spec, origin)
            if server is not None:
                result.servers.append(server)
            elif skipped is not None:
                result.skipped.append(skipped)
        results.append(result)
    return results


SKILL_FILE = "SKILL.md"


def discover_skills(roots: list[Path]) -> list[SkillFound]:
    """Every skill (a folder holding SKILL.md) under the given roots."""
    found: list[SkillFound] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for candidate in sorted(root.iterdir()):
            skill_file = candidate / SKILL_FILE
            if not candidate.is_dir() or not skill_file.is_file():
                continue
            name = candidate.name
            if name in seen:
                continue
            seen.add(name)
            found.append(SkillFound(name=name, path=candidate, origin=str(root)))
    return found


def skill_description(skill_dir: Path) -> str:
    """The ``description`` from a SKILL.md frontmatter, if it has one.

    Frontmatter is YAML-ish; this handles the shapes real skill files
    use — single-line, quoted, and folded (``>``) or literal (``|``)
    block scalars — without pulling in a YAML dependency.
    """
    try:
        text = (skill_dir / SKILL_FILE).read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return ""
    lines = match.group(1).splitlines()
    for index, line in enumerate(lines):
        found = re.match(r"^description:\s*(.*)$", line.strip())
        if not found:
            continue
        value = found.group(1).strip()
        if value in {">", "|-", "|", ">-"}:
            value = " ".join(
                part.strip() for part in lines[index + 1 :] if part.strip() and ":" not in part
            ).strip()
        return value.strip("\"'")
    return ""


def home() -> Path:
    return Path(os.path.expanduser("~"))
