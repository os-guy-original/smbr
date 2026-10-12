"""Runtime configuration.

User-editable settings: decision layer, budgets, check commands. Everything
here is mutable-layer configuration; the frozen kernel never reads policy
from the model.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """SMBR configuration. Environment prefix: ``SMBR_``."""

    model_config = SettingsConfigDict(env_prefix="SMBR_", env_file=".env", extra="ignore")

    # Decision layer
    decision_layer_enabled: bool = True
    decision_provider: str = "constrained_json"  # constrained_json | off | <external>
    decision_profile: dict[str, str] = Field(
        default_factory=lambda: {"web backend": "Python, FastAPI, SQLite"}
    )

    # Model backend (any Ollama/llama.cpp-served model; constrained JSON via
    # Ollama's structured outputs)
    model: str = "gemma4:e4b"
    model_host: str | None = None
    model_timeout: float = Field(default=300.0, gt=0)

    # Opt-in MCP servers: JSON config ({"mcpServers": {...}}), empty disables
    mcp_config: str = ".smbr/mcp.json"
    mcp_timeout: float = Field(default=30.0, gt=0)

    # Loop budgets
    max_edit_attempts: int = Field(default=3, ge=1, le=10)
    questions_per_round: int = Field(default=3, ge=1, le=5)

    # Checks (verify-before-done runs these; empty means not configured)
    project_root: Path = Path(".")
    test_command: str = "pytest"
    lint_command: str = "ruff check"
    typecheck_command: str = ""

    @property
    def required_checks(self) -> tuple[str, ...]:
        """Check names the verify gate insists on, based on configuration."""
        names = []
        if self.typecheck_command.strip():
            names.append("type_checker")
        names.append("test_runner")
        names.append("linter")
        return tuple(names)
