"""Patch apply: small, reviewable diffs, never whole-file rewrites.

Applies unified diffs with ``git apply`` (verified to work outside a git
repository) and offers a sandboxed preview that produces the patched content
without touching the working tree — the hygiene gate needs the *after* text
before the user approves anything.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from smbr.preflight.capabilities import Capability
from smbr.tools.registry import ToolHealth


class PatchError(RuntimeError):
    """The diff did not apply. The message is shown to the user verbatim."""


def _safe_target(cwd: str, path: str) -> Path:
    """Resolve a diff path inside the project, refusing traversal."""
    if not path or path.startswith("/") or ".." in Path(path).parts:
        msg = f"patch path escapes the project: {path}"
        raise PatchError(msg)
    resolved = (Path(cwd) / path).resolve()
    root = Path(cwd).resolve()
    if root not in resolved.parents:
        msg = f"patch path escapes the project: {path}"
        raise PatchError(msg)
    return resolved


class PatchApplyTool:
    name = "patch_apply"
    capability = Capability.PATCH_APPLY

    def __init__(self, cwd: str = ".") -> None:
        self.cwd = cwd

    def health(self) -> ToolHealth:
        if shutil.which("git") is None:
            return ToolHealth.broken(self.capability, "git not on PATH")
        if not Path(self.cwd).is_dir():
            return ToolHealth.broken(self.capability, f"project root missing: {self.cwd}")
        return ToolHealth.ok(self.capability, f"git apply in {self.cwd}")

    def preview(self, path: str, diff: str) -> str | None:
        """Apply the diff to a throwaway copy and return the new content.

        None means the diff did not apply — the caller reports that instead of
        applying anything to the working tree.
        """
        with tempfile.TemporaryDirectory(prefix="smbr-preview-") as tmp:
            sandbox = Path(tmp)
            try:
                target = _safe_target(str(sandbox), path)
            except PatchError:
                return None
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.write_text(
                    Path(self.cwd, path).read_text(encoding="utf-8"), encoding="utf-8"
                )
            except OSError:
                target.write_text("", encoding="utf-8")
            if not self._git_apply(sandbox, diff):
                return None
            try:
                return target.read_text(encoding="utf-8")
            except OSError:
                return None

    def apply(self, path: str, diff: str) -> str:
        """Apply the diff to the real working tree; returns the new content."""
        target = _safe_target(self.cwd, path)
        if not self._git_apply(Path(self.cwd), diff):
            msg = f"patch for {path} did not apply"
            raise PatchError(msg)
        return target.read_text(encoding="utf-8")

    @staticmethod
    def _git_apply(workdir: Path, diff: str) -> bool:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".diff", encoding="utf-8", delete=False
        ) as handle:
            handle.write(diff)
            diff_file = handle.name
        try:
            proc = subprocess.run(
                ("git", "apply", "--whitespace=nowarn", diff_file),
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            return proc.returncode == 0
        finally:
            Path(diff_file).unlink(missing_ok=True)
