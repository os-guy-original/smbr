"""Model backends for the constrained-JSON decision fallback.

Two local servers (Ollama, llama.cpp) and any OpenAI-compatible API — the
API client needs no extra install, the Ollama one is
``pip install smbr[ollama]``. The kernel and gates never import a backend
directly — they talk to the CompletionClient protocol.
"""

from smbr.decisions.provider import CompletionClient

__all__ = ["CompletionClient"]
