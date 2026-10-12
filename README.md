# SMBR — Small Model, Big Results

A free, local-first TUI coding-agent harness that makes small models write
clean, grounded code by taking guessing and free-form output away from them.

Small models fail at coding mostly because they guess, try to do too much at
once, and get no feedback when they are wrong. SMBR moves reliability out of
the model and into the harness: the model fills in one small, checkable step
at a time, and the harness decides whether that step may happen.

> **Status: working loop.** Kernel, gates, preflight, clarification, decision
> layer, the wired agent loop and the Phase 0 baseline are implemented and
> tested. Real-model runs need a model — a local server (`ollama pull
> gemma4:e4b`) or an OpenAI-compatible API key; the test suite exercises the
> loop with scripted model stubs. See [`docs/roadmap.md`](docs/roadmap.md).

## The six principles

Every design choice follows from these; when two ideas conflict, the earlier
principle wins:

1. **The harness drives the loop.** The model fills in one small step at a
   time and never controls the flow.
2. **Rules live in code, not in prompts.** A small model ignores an
   instruction by step four, so every rule is a gate it cannot pass.
3. **No guessing.** Every claim and every edit must be grounded in tool
   output. "I don't know, ask the user" is always valid and cheap.
4. **Bounded outputs.** The model answers in constrained JSON with fixed
   enums, so it cannot invent names or ramble.
5. **Free and local-first.** Works with any locally served model; hosted
   APIs are an opt-in backend for machines that can't serve one — never a
   requirement.
6. **A frozen kernel judges; only a mutable layer improves.** The things that
   decide whether work is acceptable can never be edited by the system itself.

## What the harness enforces

| Gate | Blocks until |
| --- | --- |
| Read before edit | The file was read in this session |
| Symbol check | Every symbol the edit uses was confirmed by lookup |
| Verify before done | Tests, linter and type checker ran and passed |
| Grounded claims | Each factual claim cites a tool result |
| Clarification | No required slot of the task is missing |
| Comment hygiene | Added comments restate nothing and include no dead code |
| Declared capabilities | Every tool call was declared in preflight |

Every gate is user-overridable, and every override is logged and shown in the
TUI. Gate messages are harness templates — the model never writes them.

## Quickstart

```bash
uv venv --python 3.11+
uv pip install -e ".[dev]"
ollama pull gemma4:e4b   # or point SMBR_MODEL at any locally served model
```

The project is hardware-agnostic: any model Ollama or llama.cpp can
serve works. Pick one to match your RAM (see
[`docs/roadmap.md`](docs/roadmap.md)) — the baseline measures
time-per-task, so the latency budget is measured, not assumed.

### No hardware for a local model?

Point SMBR at any OpenAI-compatible API instead (OpenRouter, OpenAI,
Groq, Together, a self-hosted vLLM — no extra dependency, just an API key):

```bash
export SMBR_MODEL_BACKEND=openai
export SMBR_API_BASE_URL=https://openrouter.ai/api/v1   # default; swap per provider
export SMBR_API_KEY=sk-or-...
export SMBR_MODEL=qwen/qwen3-coder                       # any model the provider serves
```

Everything downstream is unchanged — same gates, same kernel, same
constrained-JSON questions.

Run one coding request through the harness — clarification, preflight, plan,
gated edits, verification, grounded report:

```bash
smbr run "fix the add function in calc.py"
```
Measure a model with the Phase 0 baseline (no harness, raw scores):

```bash
smbr eval --suite evals/tasks --out results/baseline.json
```

Or check a capability manifest against the real tool registry:

```bash
smbr preflight manifest.json
```

### Opt-in MCP servers

MCP servers are optional extras. Write `.smbr/mcp.json` in the project root —
the same shape other MCP hosts use — and only servers you explicitly enable
are started:

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "..."},
      "enabled": true
    }
  }
}
```

A server's tools are registered under the `mcp` capability, so preflight
health-checks them like any built-in and the model must declare `mcp` in its
manifest to call them. The model reaches them through the same tool-call
channel as built-ins (see [`docs/agent.md`](docs/agent.md)) — nothing is
exposed all at once.

Run the TUI:

```bash
smbr tui
```

## Layout

```
src/smbr/
├── kernel/     # FROZEN: state machine, gates, runner (the loop)
├── preflight/  # capability enum, manifest parsing, failure types
├── clarify/    # slot schemas, extraction validation, question planning
├── decisions/  # DecisionProvider protocol, constrained-JSON fallback, router
├── tools/      # files, search, tree-sitter symbols, patch apply, pytest/ruff, git
├── mcp/        # opt-in MCP servers: stdio client, config, registry tool
├── hygiene/    # tree-sitter comment checks on added comments
├── agent/      # the wired loop: model schemas, user port, backends
├── evals/      # Phase 0 baseline: task suite, runner, scoring
├── tui/        # Textual interface + modal screens for asks and approvals
└── model/      # optional backends (ollama, llamacpp, openai api)
```

The `kernel/` package is the frozen kernel: gates, the evaluation suite and
the permission policy live there and can never be edited by the running
system. Everything else is the mutable layer.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — frozen kernel vs mutable layer
- [`docs/state-machine.md`](docs/state-machine.md) — 7 steps, 3 exits, 1 repair loop
- [`docs/gates.md`](docs/gates.md) — each gate, its condition, its override path
- [`docs/agent.md`](docs/agent.md) — the wired loop and the model contract
- [`docs/roadmap.md`](docs/roadmap.md) — the five phases, the open decisions

## Development

```bash
uv pip install -e ".[dev]"
ruff check . && ruff format --check . && pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) — the short version is: new rules are
gates in code, never prose in prompts.

## License

[MIT](LICENSE)
