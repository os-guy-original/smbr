"""File read and code search tools.

These are deliberately boring: real bytes from disk, real paths. The harness
records successful reads on the session so the read-before-edit gate has a
fact to check instead of a promise.
"""

from __future__ import annotations

from pathlib import Path

from smbr.preflight.capabilities import Capability
from smbr.tools.registry import ToolHealth

_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
}


def read_file(path: str | Path) -> str:
    """Read a file and return its contents. Raises on missing/unreadable."""
    p = Path(path)
    if not p.is_file():
        msg = f"cannot read {path}: not a file"
        raise FileNotFoundError(msg)
    return p.read_text(encoding="utf-8")


def search_files(root: str | Path, pattern: str, *, max_results: int = 200) -> list[str]:
    """Literal substring search over the tree, skipping VCS/cache dirs.

    Returns repo-relative POSIX paths that contain the pattern.
    """
    root_path = Path(root)
    hits: list[str] = []
    for path in sorted(root_path.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        try:
            if pattern in path.read_text(encoding="utf-8", errors="replace"):
                hits.append(path.relative_to(root_path).as_posix())
        except OSError:
            continue
        if len(hits) >= max_results:
            break
    return hits


class ReadFileTool:
    name = "file_read"
    capability = Capability.FILE_READ

    def health(self) -> ToolHealth:
        return ToolHealth.ok(self.capability)


class CodeSearchTool:
    name = "code_search"
    capability = Capability.CODE_SEARCH

    def __init__(self, cwd: str = ".") -> None:
        self.cwd = cwd

    def health(self) -> ToolHealth:
        if Path(self.cwd).is_dir():
            return ToolHealth.ok(self.capability, f"search root: {self.cwd}")
        return ToolHealth.broken(self.capability, f"search root missing: {self.cwd}")

    def search(self, pattern: str) -> list[str]:
        return search_files(self.cwd, pattern)
