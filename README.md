# SMBR — Small Model, Big Results

A free, local-first TUI coding-agent harness that makes small models write
clean, grounded code by taking guessing and free-form output away from them.

Small models fail at coding mostly because they guess, try to do too much at
once, and get no feedback when they are wrong. SMBR moves reliability out of
the model and into the harness: the model fills in one small, checkable step
at a time, and the harness decides whether that step may happen.

> **Status: scaffolding.** The kernel, gates, preflight, clarification and
> decision-layer logic are implemented and tested (see `docs/roadmap.md`).
> Model backends and the Phase 0 evaluation baseline are not implemented yet.

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
   services are optional extras, never requirements.
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

## Quickstart (works today)

```bash
uv venv --python 3.11+
uv pip install -e ".[dev]"
```

Parse and check a capability manifest against the real tool registry:

```bash
cat > manifest.json <<'JSON'
{
  "task": "add input validation to signup form",
  "requires": [
    {"capability": "file_read", "why": "inspect current form code"},
    {"capability": "docs_lookup", "why": "ground the validation library usage"}
  ]
}
JSON
smbr preflight manifest.json
# → Preflight stopped: docs_lookup is not installed. …
```

Run the TUI skeleton:

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
├── tools/      # files, search, tree-sitter symbols, pytest/ruff runners
├── hygiene/    # tree-sitter comment checks on added comments
├── tui/        # Textual interface
└── model/      # optional model backends (smbr[ollama])
```

The `kernel/` package is the frozen kernel: gates, the evaluation suite and
the permission policy live there and can never be edited by the running
system. Everything else is the mutable layer.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — frozen kernel vs mutable layer
- [`docs/state-machine.md`](docs/state-machine.md) — 7 steps, 3 exits, 1 repair loop
- [`docs/gates.md`](docs/gates.md) — each gate, its condition, its override path
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
