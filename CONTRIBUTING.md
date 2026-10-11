# Contributing to SMBR

Thanks for helping make small models reliable. This project has one unusual
rule, and it is the point of the whole thing:

> **Rules live in code, not in prompts.** If a behavior must hold for every
> run, it is a gate in `src/smbr/kernel/gates.py` (or a check the gate calls),
> never an instruction in a prompt.

## The frozen kernel

The following can **never** be modified by the running system itself, and
changes to them require a conscious human PR:

- gates and their conditions
- the evaluation suite and its scoring
- the permission policy
- the missing-tool warning path

Everything else is the mutable layer (prompts, decomposition strategies,
tool exposure, repair recipes, decision profiles) and may improve — but only
when the held-out evaluation says the change earns its keep.

## Development setup

```bash
uv venv --python 3.11+   # 3.11 through 3.14 are supported
uv pip install -e ".[dev]"
```

## Checks

Every PR must pass:

```bash
ruff check .           # lint
ruff format --check .  # format (config in pyproject.toml)
pytest                 # test suite
```

Optional: `pre-commit install` for the same checks on commit.

## Adding a gate

1. Implement the `Gate` protocol in `src/smbr/kernel/gates.py`.
2. Its refusal message comes from the harness templates — never let the model
   write or soften it.
3. Wire it into the transitions it guards in `runner.py`.
4. Add a test proving it blocks the transition, and that a logged user
   override lets it through.
5. A gate with no override path will be rejected: gates exist to prevent
   silent failure, not to trap the user.

## Adding a tool

1. Implement the `Tool` protocol in `src/smbr/tools/` with a real
   `health()`.
2. Register its capability in `preflight.capabilities.Capability` so
   grammar-constrained decoding can never invent a new name.
3. Add it to `STEP_TOOLS` for the steps where it belongs — per-step exposure
   keeps the tool list at 3–5 items.
4. MCP servers go through the same registry and health check as built-ins.

## Commit style

Conventional-commit subjects (`feat:`, `fix:`, `chore:`), imperative mood,
one concern per commit.
