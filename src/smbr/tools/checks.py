"""Test runner, linter and type checker wrappers.

Real pass/fail feedback, captured as returncodes — the verify-before-done
gate reads these outcomes and the model never gets to interpret them.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from smbr.preflight.capabilities import Capability
from smbr.tools.registry import ToolHealth


@dataclass(frozen=True)
class CheckResult:
    runner: str
    command: tuple[str, ...]
    returncode: int
    output: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0


def run_check(command: tuple[str, ...] | list[str], cwd: str = ".") -> CheckResult:
    """Run a check command and capture its result. Never raises on failure."""
    cmd = tuple(command)
    if not cmd:
        return CheckResult("", cmd, 0, "no command configured")
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    output = (proc.stdout + "\n" + proc.stderr).strip()
    return CheckResult(cmd[0], cmd, proc.returncode, output[-4000:])


class _CommandTool:
    """Base for subprocess-backed tools with an availability health check."""

    name = ""
    capability: Capability

    def __init__(self, command: tuple[str, ...], cwd: str = ".") -> None:
        self.command = tuple(command)
        self.cwd = cwd

    def health(self) -> ToolHealth:
        if not self.command:
            return ToolHealth.broken(self.capability, "no command configured")
        binary = shutil.which(self.command[0])
        if binary is None:
            return ToolHealth.broken(self.capability, f"{self.command[0]} not on PATH")
        return ToolHealth.ok(self.capability, f"{binary}")

    def run(self) -> CheckResult:
        return run_check(self.command, self.cwd)


class TestRunnerTool(_CommandTool):
    name = "test_runner"
    capability = Capability.TEST_RUNNER


class LinterTool(_CommandTool):
    name = "linter"
    capability = Capability.LINTER


class TypeCheckerTool(_CommandTool):
    name = "type_checker"
    capability = Capability.TYPE_CHECKER


def test_runner_tool(*, command: tuple[str, ...] = ("pytest",), cwd: str = ".") -> TestRunnerTool:
    return TestRunnerTool(command, cwd)


def linter_tool(*, command: tuple[str, ...] = ("ruff", "check"), cwd: str = ".") -> LinterTool:
    return LinterTool(command, cwd)


def type_checker_tool(*, command: tuple[str, ...] = (), cwd: str = ".") -> TypeCheckerTool:
    return TypeCheckerTool(command, cwd)
