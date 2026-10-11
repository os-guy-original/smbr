# SMBR: Small Model, Big Results — Design Document

Oct 11, 2026 · @OpenSourceGuy

## Vision and goals

SMBR (Small Model, Big Results) is a free, local-first TUI coding agent and harness that makes small models write clean, grounded code by taking guessing and free-form output away from them.

Small models fail at coding mostly because they guess, try to do too much at once, and get no feedback when they are wrong. Big models guess well enough to get away with it. SMBR moves reliability out of the model and into the harness, so the model only has to fill in one small, checkable step at a time.

**Goals**

- A small local model completes well-specified coding tasks with the tests passing (target model size is an open decision, see the last section).
- The agent never edits a file it has not read, never uses a symbol it has not confirmed, and never reports "done" without passing checks.
- When a request lacks detail, the agent asks instead of guessing.
- When a needed tool is missing, the user is warned by the harness, not by the model.
- It runs free, on the user's own hardware, with any model that Ollama or llama.cpp can serve.

**Non-goals**

- Not a new model, and not a competitor for frontier-model tasks.
- No dependency on a cloud service.

**How we know it works:** every claim of improvement is measured against the evaluation baseline described later in this document.

## Core principles

Six principles decide every design choice in SMBR; when two ideas conflict, the earlier principle wins.

1. **The harness drives the loop.** The model fills in one small step at a time and never controls the flow.
2. **Rules live in code, not in prompts.** A small model ignores an instruction by step four, so every rule is a gate it cannot pass.
3. **No guessing.** Every claim and every edit must be grounded in tool output. "I don't know, ask the user" is always a valid and cheap action.
4. **Bounded outputs.** The model answers in constrained JSON with fixed enums for actions and capabilities, so it cannot invent names or ramble.
5. **Free and local-first.** SMBR works with any locally served model, and closed or hosted services are optional extras, never requirements.
6. **A frozen kernel judges; only a mutable layer improves.** The things that decide whether work is acceptable can never be edited by the system itself.

## Architecture

&#91;embedded content: SMBR architecture · frozen kernel, mutable layer, 3 services\]

The frozen kernel runs the loop and calls the model, the decision provider and the tools; the mutable layer configures it and improves only when the evaluations say so.

## State machine

&#91;embedded content: State machine · 7 steps, 3 exits, 1 repair loop\]

The steps run in order, and the harness advances only when a step's gate passes. A missing tool or missing slot leaves the loop for the user, and failed checks return to the edit step until the step budget is spent.

## Gates

Gates are code-enforced rules that block a transition until their condition is met; the model cannot argue with them, skip them, or rephrase their messages.

| Gate | Condition to pass | On failure |
| --- | --- | --- |
| Read before edit | The file was read in this session | Edit refused; harness requests a read |
| Symbol check | Every function, class or import the edit uses was confirmed by symbol lookup | Edit refused; model must look it up or ask |
| Verify before done | Tests, linter and type checker ran and passed | State machine stays in verify; repair loop starts |
| Grounded claims | Each factual claim about the codebase cites a tool result | Claim rejected; model must run a tool or say it does not know |
| Clarification | No required slot of the task is missing (see Clarification gate) | Mandatory question phase |
| Comment hygiene | Newly added comments pass the comment check (see Code hygiene) | Patch returned for revision |
| Declared capabilities | Every tool call was declared in the preflight manifest or approved by the harness | Call blocked or run halted |

**User override.** Gates exist to prevent silent failure, not to trap the user. Any gate can be overridden by the user explicitly, and every override is logged and shown in the TUI.

**Gate messages are templates.** Warnings shown to the user are filled from templates by the harness, so the model cannot soften or skip them.

## Preflight and capability check

Before any work starts, the model declares which capabilities the task needs, and the harness verifies each one against its real tool registry; a missing tool halts the run and warns the user.

**Split of responsibility.** The model only declares needs, as JSON. The harness checks availability with deterministic code, because a model asked whether a tool exists can hallucinate the answer.

```json
{
  "task": "add input validation to signup form",
  "requires": [
    {"capability": "file_read", "why": "inspect current form code"},
    {"capability": "symbol_lookup", "why": "find validation helpers"},
    {"capability": "test_runner", "why": "verify the change"}
  ]
}
```

**Constrained names.** With grammar-constrained decoding, `capability` is an enum of the names the harness knows, plus an explicit `unknown_capability` value with a description. Needing something that does not exist is therefore a first-class output, not a hallucination.

**Three failure types**, each with its own user message:

1. **Not installed:** the tool does not exist, for example no test runner is configured.
2. **Unhealthy:** the tool exists but fails a quick health check, for example a server is down or a binary is not on the path.
3. **Not permitted:** the tool exists but policy blocks it.

**Harness-written warning.** The message to the user comes from a template filled with the failing capability, never from model-written prose.

**Runtime check.** Needs can appear mid-task, so any call to an undeclared tool is re-validated; the harness either approves it or halts the run.

**Default on missing tools:** stop and ask the user. Fallbacks (for example continuing with the linter only when no test runner exists) are offered only as an explicit user choice.

## Clarification gate

When a request lacks detail, such as "Build a productivity app", the harness forces a question phase by detecting missing information mechanically, instead of hoping the model chooses to ask.

**Slot filling.**

1. The harness holds a schema of required slots per task type. For a new app: purpose or domain, language, framework, platform, persistence and scope.
2. The model extracts slots from the user's message into JSON, using `null` for anything not stated.
3. To fill a slot the model must quote the user's words that support it, or cite a tool result. For example, a detected `package.json` fills language and framework without asking.
4. If any required slot is `null`, the harness enters a mandatory question phase and planning is blocked.

**Asking well.**

- The harness chooses which slot to ask about, most blocking first. The model only phrases the question and proposes options.
- Prefer multiple choice with a sensible default and a "you decide" option.
- Cap each round at 3 to 5 questions so it never becomes an interrogation.
- Scale the threshold to the task: "Fix the null check on line 40" needs no questions, "Build a productivity app" needs several. Over-asking is a failure as much as guessing.

**Confidence.** The decision layer (next sections) can score whether a slot is specified. Low confidence always routes to asking the user, never to a default guess.

**"You decide".** When the user delegates a choice, the decision profile is consulted (see Decision layer).

## Decision layer

SMBR routes bounded judgments (is this slot specified, which task type is this, does this comment restate the code) through a swappable decision provider, and the user can change it or turn it off.

**What a decision model is.** Models such as Jev and Laya do not generate text. They answer bounded questions: a choice, a score, or a yes/no probability that an application can act on directly ([Runware overview](https://runware.ai/blog/jev-laya-and-the-emerging-role-of-decision-models)). That fits the no-guessing principle, because the output is a value the harness can threshold.

| Model | What it is | Open weights |
| --- | --- | --- |
| Jev (TypeSafe AI) | The original "System One" decision model | No, architecture and weights are not public |
| Laya (Convai Innovations) | Non-autoregressive, built on ModernBERT-large, multilingual checkpoint available, installs as a Python package | Yes |
| Kev | Jev-inspired family built on Qwen3.5 in 0.8B, 4B and 9B sizes | Yes, with an open training pipeline |
| SemIf (formerly OpenJev) | Reads the logits of existing open models instead of training a new one | Uses open models |

Details above are from [DataCamp's comparison](https://www.datacamp.com/blog/top-open-source-jev-alternatives) and [Pinggy's roundup](https://pinggy.io/amp/blog/best_open_source_jev_alternatives_self_hosted_decision_models/); this field is new and changes quickly, so verify each repository before committing.

**DecisionProvider interface.** Three typed operations, `choice`, `score` and `boolean`, with swappable backends:

1. An open decision model (Laya, Kev or SemIf).
2. Hosted Jev, as an optional backend.
3. The main small model with constrained JSON, as the always-available fallback.

Laya's server mode exposes the same request protocol as Jev, so one client can talk to several backends.

**Decision profiles.** When the user says "you pick", choices come from an editable config file, for example "web backend: Python, FastAPI, SQLite". The user can edit it, replace the provider, or disable the layer entirely, in which case SMBR asks every time.

**Calibration.**

- Published scores are not proof for our tasks. Test every backend on our own labeled examples, such as underspecified versus complete requests and useless versus useful comments.
- Low confidence routes to asking the user, never to a default guess.

## Tools, MCP servers and skill import

SMBR ships a small curated core toolset and exposes only the tools relevant to the current step, because a long tool list makes small models pick the wrong ones.

**Core toolset**

| Tool | Purpose |
| --- | --- |
| File read | Read before edit (gate) |
| Code search | Find where things live |
| Symbol lookup | LSP or tree-sitter confirmation of every symbol |
| Patch apply | Small, reviewable diffs instead of whole-file rewrites |
| Test runner | Real pass or fail feedback |
| Linter and type checker | Targeted error feedback for repair prompts |
| Git | History, diffs, safe rollback |
| Docs lookup | Ground library usage in documentation |

**Per-step exposure.** The state machine knows which step it is in, so the harness decides which 3 to 5 tools the model sees at that step.

**Additional MCP servers** are optional and opt-in. Each one goes through the same registry and health check as a built-in tool.

**Importing from other tools.** SMBR should import MCP server configs and skills from tools such as OpenCode, taking inspiration from Oh My OpenCode. MCP configs share a fairly standard shape (command, arguments, environment), and skills are mostly folders of instructions, so an import adapter is feasible.

**Security of imports.**

- Imported skills are untrusted text and a prompt-injection path, so they run under the same gates and permissions as everything else.
- Imported tools are checked by the preflight like any other and are never exposed all at once.
- The user reviews what an import adds before it is enabled.

## Code hygiene

The harness strips useless comments after every edit with a mechanical check, instead of asking the model to write fewer of them.

**How it works.** After each patch, the harness parses the changed files with tree-sitter and inspects only the comments the patch added. Any added comment that fails the check sends the patch back for revision.

**What counts as useless (starting conservative).**

- Comments that merely restate the next line of code.
- Commented-out code left behind by the edit.

**What is always kept.**

- Docstrings and API documentation.
- License headers and tool directives such as type-checker or linter pragmas.
- Comments that explain why a decision was made, including TODOs that state a reason.

**Judging "restates the code."** This is a bounded yes/no question, so it goes to the decision layer, with a simple heuristic fallback when the layer is off.

**Configurable.** Strictness is set per project, because teams differ on comment style. Further post-edit checks, such as formatting and dead-code detection, plug into the same mechanism.

## TUI design

The TUI makes the harness visible: the user always sees which step the agent is in, what it was allowed to do, and what stopped it.

**Always on screen**

- The current state-machine step and the task plan.
- A live list of tool calls and their results.
- Gate results, shown as pass or fail with the reason.

**Interrupts that need the user**

- **Missing-tool warnings** from the preflight, shown prominently and using the harness template.
- **Clarification questions**, with multiple-choice options, a default and a "you decide" choice.
- **Diff approval** before a patch is applied, with the comment-hygiene result.
- **Gate overrides**, which are explicit and logged.

**Settings the user controls**

- Decision provider and decision profile, including turning the layer off.
- Imported skills and MCP servers, with a review step before enabling.
- Gate strictness per project.

The v1 interface plan (framework and layout) depends on the implementation language decision.

## Evaluation and self-improving harness

Every improvement claim is measured, and the system can only improve the parts of itself that sit outside the code that judges it.

**Evaluation baseline (Phase 0).** One small model, 20 to 30 coding tasks of rising difficulty, and raw scores with no harness. Each later layer (gates, preflight, clarification) is then measured against this baseline so we know which ones earn their keep.

**Held-out tasks.** A separate task set that the system never sees during tuning, so improvements are not overfitting to the benchmark.

**Frozen kernel versus mutable layer.**

| Frozen kernel (never self-edited) | Mutable layer (can improve) |
| --- | --- |
| Gates and their conditions | Prompts and decomposition strategies |
| Evaluation suite and scoring | Which tools are exposed at which step |
| Permission policy | Repair recipes and the skill library |
| Missing-tool warning path | Decision profiles |

**Why the split matters.** If the system could edit its own "don't guess" rules, the easiest way to raise its score would be to remove them. The thing that judges improvement must stay outside what the system can modify.

**Improvement loop (Phase 4).** An offline improver, a stronger model or the user, proposes a change to the mutable layer. The change is accepted only if it wins on the held-out evaluation. Small models are poor judges of what to change in their own harness, so the small model does the everyday work inside the improved harness and does not propose the changes.

This is a self-improving harness, not a model rewriting itself: the gains come from better scaffolding.

## Roadmap

&#91;embedded content: Roadmap · 5 phases, 4 exit gates\]

Each phase ends at a gate that must pass before the next begins. Phase 0 comes first so every later layer can be measured against raw scores, and the improvement loop waits until the evaluation is trustworthy.

## Risks and mitigations

The biggest risks are speed, over-constraint and benchmark overfitting, and each has a specific mitigation.

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Latency | A multi-step loop multiplies the cost of a slow small model | Use fast, non-generative decision models for gates; measure time per task in the evaluation |
| Over-constraint | Gates may block legitimate work | User override for every gate, logged and visible in the TUI |
| Tool overload | Too many tools make small models pick the wrong one | Curated core, per-step exposure, opt-in extras |
| Spiraling retries | Forced verification can loop forever | Step budgets, loop detection, a clean "stuck, here is what I tried" exit |
| Benchmark overfitting | The improvement loop learns the test set | Held-out tasks the system never tunes on |
| Reward hacking | A self-improving system removes its own rules | Frozen kernel outside the mutable layer |
| Imported skill injection | Imported skills are untrusted text | Same gates and permissions, review before enabling |
| Unproven decision models | Published scores may not transfer to our tasks | Test each backend on our own labeled examples; low confidence routes to asking the user |

## Open decisions

Three decisions are still open, and the first two shape almost everything else.

| Decision | Current default | Alternatives | Status |
| --- | --- | --- | --- |
| Implementation language | Python, for fast iteration and the best grammar-constrained decoding and tree-sitter libraries, with the TUI in Textual | Rust or Go for a single fast binary, slower to iterate on | Open |
| Hardware and target model size | Not yet chosen | A small model in the 7B to 14B range served by Ollama or llama.cpp | Open, needs the user's hardware |
| Language focus for v1 | One language first, so symbol lookup, tests and linting are well supported | Python or TypeScript | Open |

**Confirm next:** the user's hardware and which model size to design around, because that sets the latency budget for every gate.
