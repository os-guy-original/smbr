"""Runtime configuration.

User-editable settings: decision layer, budgets, check commands. Everything
here is mutable-layer configuration; the frozen kernel never reads policy
from the model.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Model backends: two local servers plus any OpenAI-compatible API.
BACKENDS = ("ollama", "llamacpp", "openai")


class Settings(BaseSettings):
    """SMBR configuration. Environment prefix: ``SMBR_``."""

    model_config = SettingsConfigDict(
        env_prefix="SMBR_", env_file=".env", extra="ignore", populate_by_name=True
    )

    # Decision layer
    decision_layer_enabled: bool = True
    decision_provider: str = "constrained_json"  # constrained_json | off | <external>
    decision_profile: dict[str, str] = Field(
        default_factory=lambda: {"web backend": "Python, FastAPI, SQLite"}
    )

    # Model backend (any Ollama/llama.cpp-served local model, or any
    # OpenAI-compatible API for machines without the RAM to serve one)
    model_backend: str = "ollama"  # ollama | llamacpp | openai
    model: str = "gemma4:e4b"
    model_host: str | None = None
    model_timeout: float = Field(default=300.0, gt=0)
    api_key: str | None = Field(
        default=None, description="API key for the openai backend (SMBR_API_KEY)"
    )
    api_base_url: str = "https://openrouter.ai/api/v1"  # must include the version prefix

    # Opt-in MCP servers: JSON config ({"mcpServers": {...}}), empty disables
    mcp_config: str = ".smbr/mcp.json"
    mcp_timeout: float = Field(default=30.0, gt=0)

    # Imported skills: inert data under .smbr/, with a provenance manifest.
    # Imported skills are untrusted text, so nothing is enabled by import.
    skills_dir: str = ".smbr/skills"

    # Loop budgets
    max_edit_attempts: int = Field(default=3, ge=1, le=10)
    questions_per_round: int = Field(default=3, ge=1, le=5)

    # Checks (verify-before-done runs these; empty means not configured)
    project_root: Path = Path(".")
    test_command: str = "pytest"
    lint_command: str = "ruff check"
    typecheck_command: str = ""

    @field_validator("model_backend")
    @classmethod
    def _known_backend(cls, value: str) -> str:
        """An unknown backend fails loudly, not by silently falling back."""
        backend = value.strip().lower()
        if backend not in BACKENDS:
            msg = f"unknown model_backend {value!r}; expected one of {', '.join(BACKENDS)}"
            raise ValueError(msg)
        return backend

    @model_validator(mode="after")
    def _fill_api_key(self) -> Settings:
        """OPENAI_API_KEY is the fallback when SMBR_API_KEY is unset."""
        if not self.api_key:
            self.api_key = os.environ.get("OPENAI_API_KEY") or None
        return self

    @property
    def required_checks(self) -> tuple[str, ...]:
        """Check names the verify gate insists on, based on configuration."""
        names = []
        if self.typecheck_command.strip():
            names.append("type_checker")
        names.append("test_runner")
        names.append("linter")
        return tuple(names)
