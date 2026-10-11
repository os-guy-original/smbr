"""Model backends for the constrained-JSON decision fallback.

Backends are optional: install with ``pip install smbr[ollama]``. The kernel
and gates never import a backend directly — they talk to the CompletionClient
protocol.
"""

from smbr.decisions.provider import CompletionClient

__all__ = ["CompletionClient"]
