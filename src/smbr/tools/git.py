"""Git tool: history, diffs, and a safe rollback path.

Read-only views (status, log, diff) for the model, plus the
rollback the harness uses when a run exhausts its repair budget:
the session snapshots every file before the first edit, so
rollback restores exact prior content and works outside a git
repository. `git checkout` is only the fallback when a snapshot
is missing but the tree is a repo.
"""

from __future__ import annotations

import shutil
import subprocess

from smbr.preflight.capabilities import Capability
from smbr.tools.registry import ToolHealth


class GitTool:
    name = "git"
    capability = Capability.GIT

    def __init__(self, cwd: str = ".") -> None:
        self.cwd = cwd

    def health(self) -> ToolHealth:
        if shutil.which("git") is None:
            return ToolHealth.broken(self.capability, "git not on PATH")
        return ToolHealth.ok(self.capability, f"git in {self.cwd}")

    def status(self) -> str:
        return self._git("status", "--short")

    def log(self, limit: int = 5) -> str:
        return self._git("log", f"-{limit}", "--oneline")

    def diff(self) -> str:
        return self._git("diff")

    def rollback(self, paths: list[str]) -> list[str]:
        """Revert uncommitted changes in the given paths. Returns
        the paths git actually restored (empty outside a repo)."""
        restored: list[str] = []
        for batch in _batches(paths):
            proc = self._run("checkout", "--", *batch)
            if proc.returncode == 0:
                restored.extend(batch)
        return restored

    def _git(self, *args: str) -> str:
        proc = self._run(*args)
        return (proc.stdout + proc.stderr).strip()

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ("git", *args),
            cwd=self.cwd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )


def _batches(paths: list[str], size: int = 50) -> list[list[str]]:
    return [paths[i : i + size] for i in range(0, len(paths), size)]
