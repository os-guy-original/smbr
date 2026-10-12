# Architecture

Two layers with a hard boundary between them.

## Frozen kernel (never self-edited)

Owns everything that decides whether work is acceptable:

- **Gates** (`src/smbr/kernel/gates.py`) and their conditions.
- **The evaluation suite** and its scoring (Phase 0; not yet implemented).
- **The permission policy** — what tools exist, what may run, what the user
  must approve.
- **The missing-tool warning path** — harness-written messages only.

If the system could edit its own "don't guess" rules, the easiest way to raise
its score would be to remove them. The thing that judges improvement stays
outside what the system can modify.

## Mutable layer (can improve, when the eval says so)

- Prompts and decomposition strategies.
- Which tools are exposed at which step.
- Repair recipes and the skill library.
- Decision profiles.

A change to the mutable layer is accepted only if it wins on the **held-out**
evaluation — tasks the system never sees during tuning.

## Three services inside the kernel

1. **The loop** (`kernel/runner.py`) — ordering, budgets, transitions.
2. **The decision provider** (`decisions/`) — bounded judgments (choice /
   score / boolean) with swappable backends.
3. **The tools** (`tools/`) — the curated core, behind one registry with a
   single health-check entry point.
4. **Opt-in MCP servers** (`mcp/`) — a stdio JSON-RPC client, the config
   loader, and one registry tool per enabled server. Remote tools ride the
   same registry, health check, per-step exposure and gates as built-ins.

## Model backends

The kernel talks to a `CompletionClient` protocol, never to a server
directly. The always-available fallback provider is the main small model
answering in constrained JSON; the local Ollama client lives in `smbr/model/`
behind the `smbr[ollama]` extra. Decision models (Laya, Kev, SemIf, hosted
Jev) implement the same `DecisionProvider` protocol — one client shape,
several backends.
