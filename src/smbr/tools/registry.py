"""Tool registry: one registry for built-ins and MCP servers alike.

The registry answers the only question the preflight cares about — "does this
capability actually exist and work?" — with a deterministic health check, and
it decides which 3-5 tools the model is shown at each step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from smbr.config import Settings
from smbr.preflight.capabilities import Capability

if TYPE_CHECKING:
    from smbr.kernel.state import Step


@dataclass(frozen=True)
class ToolHealth:
    """What the registry knows about one capability."""

    capability: Capability
    installed: bool
    available: bool
    detail: str = ""

    @classmethod
    def ok(cls, capability: Capability, detail: str = "healthy") -> ToolHealth:
        return cls(capability, True, True, detail)

    @classmethod
    def broken(cls, capability: Capability, detail: str) -> ToolHealth:
        return cls(capability, True, False, detail)

    @classmethod
    def absent(cls, capability: Capability) -> ToolHealth:
        return cls(capability, False, False, "no tool provides this capability")


class Tool(Protocol):
    """A tool the harness can expose and health-check."""

    name: str
    capability: Capability

    def health(self) -> ToolHealth: ...


class ToolRegistry:
    """Capability-keyed registry with a single health-check entry point."""

    def __init__(self) -> None:
        self._tools: dict[Capability, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.capability] = tool

    def check(self, capability: Capability) -> ToolHealth:
        tool = self._tools.get(capability)
        if tool is None:
            return ToolHealth.absent(capability)
        return tool.health()

    def health(self) -> dict[Capability, ToolHealth]:
        return {cap: tool.health() for cap, tool in self._tools.items()}

    def expose(self, step: Step) -> list[str]:
        """Tool names relevant to the current step — never the full list."""
        wanted = STEP_TOOLS[step]
        return sorted(t.name for cap, t in self._tools.items() if cap in wanted)


# Per-step exposure. A long tool list makes small models pick the wrong tool,
# so the state machine decides what the model sees (3-5 per step). Keys are the
# plain step strings, so `Step.EDIT` (a str-enum) looks up "edit" directly and
# the registry never has to import the kernel at runtime.
STEP_TOOLS: dict[str, frozenset[Capability]] = {
    "intake": frozenset({Capability.FILE_READ, Capability.CODE_SEARCH, Capability.DOCS_LOOKUP}),
    "clarify": frozenset({Capability.FILE_READ, Capability.CODE_SEARCH}),
    "preflight": frozenset({Capability.FILE_READ}),
    "plan": frozenset({Capability.CODE_SEARCH, Capability.SYMBOL_LOOKUP, Capability.DOCS_LOOKUP}),
    "edit": frozenset({Capability.FILE_READ, Capability.SYMBOL_LOOKUP, Capability.PATCH_APPLY}),
    "verify": frozenset(
        {Capability.TEST_RUNNER, Capability.LINTER, Capability.TYPE_CHECKER, Capability.GIT}
    ),
    "report": frozenset({Capability.GIT, Capability.FILE_READ}),
}


def default_registry(*, cwd: str = ".") -> ToolRegistry:
    """The curated v1 core toolset, registered in one place."""
    from smbr.tools.checks import linter_tool, test_runner_tool, type_checker_tool
    from smbr.tools.files import CodeSearchTool, ReadFileTool
    from smbr.tools.patch import PatchApplyTool
    from smbr.tools.symbols import SymbolLookupTool

    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(CodeSearchTool(cwd=cwd))
    registry.register(SymbolLookupTool())
    registry.register(PatchApplyTool(cwd=cwd))
    registry.register(test_runner_tool(command=("pytest",), cwd=cwd))
    registry.register(linter_tool(command=("ruff", "check"), cwd=cwd))
    registry.register(type_checker_tool(command=(), cwd=cwd))
    return registry


def registry_from_settings(settings: Settings) -> ToolRegistry:
    """The registry for one project: check commands come from Settings."""
    from smbr.tools.checks import (
        LinterTool,
        TestRunnerTool,
        TypeCheckerTool,
        command_from_str,
    )
    from smbr.tools.files import CodeSearchTool, ReadFileTool
    from smbr.tools.patch import PatchApplyTool
    from smbr.tools.symbols import SymbolLookupTool

    cwd = str(settings.project_root)
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(CodeSearchTool(cwd=cwd))
    registry.register(SymbolLookupTool())
    registry.register(PatchApplyTool(cwd=cwd))
    registry.register(TestRunnerTool(command_from_str(settings.test_command), cwd))
    registry.register(LinterTool(command_from_str(settings.lint_command), cwd))
    if settings.typecheck_command.strip():
        registry.register(TypeCheckerTool(command_from_str(settings.typecheck_command), cwd))
    return registry
