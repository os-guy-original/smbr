# State machine

Seven ordered steps, three exits, one repair loop. The harness advances only
when a step's gate passes.

```
INTAKE ──needs clarification──▶ CLARIFY ─┐
   │                                    │
   └── fully specified ─────────────────┴─▶ PREFLIGHT ──failures──▶ HALTED
                                              │ pass
                                              ▼
                                            PLAN ──▶ EDIT ──▶ VERIFY ──pass──▶ REPORT ──▶ DONE
                                                         ▲        │
                                                         └─ fail ─┘   (budget left)
                                                                  │
                                                             budget spent
                                                                  ▼
                                                               STUCK
```

| Step | What happens | Gate on the way out |
| --- | --- | --- |
| `intake` | Parse the request; detect the task type | — |
| `clarify` | Fill required slots; mandatory question phase if any are missing | planning blocked while slots are missing |
| `preflight` | Model declares capabilities; harness verifies each against the registry | failures halt the run for the user |
| `plan` | Decompose into small, checkable steps | — |
| `edit` | Read → confirm symbols → patch | read-before-edit, symbol-check, comment-hygiene |
| `verify` | Tests, linter, type checker — real pass/fail | verify-before-done |
| `report` | Summarize with grounded claims | grounded-claims |

**Exits**

| Exit | Meaning |
| --- | --- |
| `done` | All checks passed; claims are grounded. |
| `stuck` | Verify kept failing until the edit budget was spent; the run reports what it tried. |
| `halted` | A required tool is missing/unhealthy/blocked, or a transition gate refused. The run stops for the user, with the harness's message. |

**The repair loop** is the only cycle: verify failing returns to `edit` until
`max_edit_attempts` (default 3) is spent, then the run exits `stuck` with its
history intact — it never loops forever.

The transition code is `src/smbr/kernel/state.py::decide_next`; the loop that
walks it is `src/smbr/kernel/runner.py::Kernel.run`.
