# Gates

A gate is code-enforced: it blocks a transition (or an action) until its
condition is met. The model cannot argue with a gate, skip it, or rephrase
its message. Messages are filled from the templates in
`kernel/gates.py::TEMPLATES` by the harness.

| Gate | Condition to pass | On failure |
| --- | --- | --- |
| `read_before_edit` | The file was read in this session | Edit refused; harness requests a read |
| `symbol_check` | Every function/class/import the edit uses was confirmed by lookup | Edit refused; model must look it up or ask |
| `verify_before_done` | Test runner, linter (and type checker, if configured) ran and passed | Stays in verify; repair loop starts |
| `grounded_claims` | Each factual claim cites a tool result | Claim rejected; run a tool or say you don't know |
| `comment_hygiene` | Added comments restate nothing and include no commented-out code | Patch returned for revision |
| `declared_capabilities` | The tool call was declared in preflight or approved by the harness | Call blocked or run halted |

## Action gates vs transition gates

- **Action gates** run when the model asks for something mid-step
  (`Kernel.guard_action`): read-before-edit, symbol check, grounded claims,
  declared capabilities.
- **Transition gates** run when the machine wants to move
  (`runner.py::TRANSITION_GATES`): comment hygiene on `edit → verify`,
  verify-before-done on `verify → report`.

## User override

Gates exist to prevent *silent failure*, not to trap the user. Any gate can be
overridden explicitly:

```python
kernel.override("read_before_edit", "edit:app.py", "user reviewed the file externally")
```

Overrides are logged on the session and surfaced in the TUI. A gate with no
override path is a bug by definition — see CONTRIBUTING.

## Adding a gate

1. Implement the `Gate` protocol in `kernel/gates.py`.
2. Add a message template to `TEMPLATES`.
3. Wire it into the transitions or actions it guards.
4. Tests: prove it blocks, and prove the override lets it through.
