# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to semantic versioning.

## [Unreleased]

### Added

- **Imports from other agents** (`smbr/imports/`) — `smbr import scan` reports
  the MCP servers and skills other agents already have on this machine;
  `smbr import mcp` writes them to `.smbr/mcp.json` disabled, and
  `smbr import skills` copies skills with a sha256 provenance manifest.
  Readers cover OpenCode (`mcp` key, argv arrays, JSONC, per-server
  timeouts, `~/.claude.json`-style project scoping), Claude Code (`.mcp.json`,
  user scope), VS Code/Copilot (`servers` key), and any file passed with
  `--path` — the wrapper is auto-detected, so an unknown agent still imports.
  Anything unimportable (remote transports, disabled entries) is reported,
  never silently dropped.
- **Per-step exposure budget** — `MAX_EXPOSED_TOOLS` caps the tool names a
  step exposes, so one verbose MCP server cannot blow the 3-5 guidance that
  per-step exposure exists to enforce.
- **A runnable TUI** — `smbr tui` now takes a request (bottom input, or
  `--request`) and drives a real agent run: clarification questions and patch
  approvals are modal screens, harness messages stream into the event log,
  and every question and answer is recorded for audit. `smbr tui --demo`
  runs the whole flow on a canned model, so the interface is testable with no
  model server. The Textual Pilot test suite drives the same path in CI.
- **OpenAI-compatible API backend** (`smbr/model/openai_client.py`) — the same
  constrained-JSON model calls against any hosted chat-completions endpoint
  (OpenRouter, OpenAI, Groq, Together, a self-hosted vLLM), so a machine
  without the RAM to serve a local model is not locked out. Selected with
  `SMBR_MODEL_BACKEND=openai` plus `SMBR_API_KEY` (`OPENAI_API_KEY` is the
  fallback) and `SMBR_API_BASE_URL`; no SDK dependency, a missing key fails
  loudly, the schema goes out in strict `json_schema` form so providers with
  a native strict mode enforce it, and a provider that rejects that gets a
  `json_object` retry with the schema moved into the prompt. Same gates,
  same kernel.
- **Opt-in MCP servers** (`smbr/mcp/`) — a stdio JSON-RPC client (initialize
  handshake, `tools/list`, `tools/call`, no SDK dependency), the standard
  `mcpServers` config format (`.smbr/mcp.json`), and one registry tool per
  enabled server. Remote tools health-check like built-ins, are exposed
  per step, and are covered by the declared-capabilities gate through a new
  `mcp` capability. Servers are spawned per call — no process outlives a
  call.
- **A model tool-call channel** — a patch answer may carry up to three
  `tool_calls` to read-only built-ins or declared MCP tools; each is checked
  for step exposure and declared capability, and its result is recorded like
  any tool result. No write path through the channel.
- **Git tool** — status/log/diff views for the model, plus registry health
  for the `git` capability.
- **Safe rollback** — every file is snapshotted before its first edit; a
  `stuck` exit reports what was tried and offers to restore the run's files
  to their snapshotted content.
- Phase 0 eval suite grown from 10 to 20 tasks (four per difficulty level),
  each verified solvable by a reference solution run in CI.
- **Agent loop (`smbr run`)** — the kernel wired to a local model: all seven
  steps driven by constrained-JSON questions with fixed schemas, tool results
  recorded on the session, action and transition gates enforced on every edit,
  the repair loop feeding failing check output back into patch prompts, and a
  grounded-claims report.
- **Patch apply tool** — `git apply`-based unified-diff application (works
  outside a git repo) with a sandboxed preview; paths escaping the project
  root are refused.
- **Model backends** — Ollama client using structured outputs
  (`format=<json-schema>`, default model `gemma4:e4b`) and an
  OpenAI-compatible llama.cpp client; both behind the existing
  `CompletionClient` protocol, selected through Settings.
- **User ports** — CLI prompts, Textual modal screens for clarification
  questions and diff approval, and a recording port for tests.
- **Phase 0 evaluation baseline (`smbr eval`)** — task suite format, runner
  and scoring: one model call per task, no harness, per-difficulty reporting.
- Settings for model, host, and timeout (`SMBR_MODEL`, `SMBR_MODEL_HOST`,
  `SMBR_MODEL_TIMEOUT`).

### Changed

- **The TUI was rebuilt around what a user needs to see.** Every message now
  carries its kind — tools dim, gate passes green, gate failures and refusals
  red, questions yellow, overrides magenta, the final line bold — instead of
  one undifferentiated log where a refusal looked like a tool result. A status
  line shows the step, plan progress, running state, elapsed time and model;
  step transitions are reported live by the agent (including `edit 1/2`), not
  only at the end. The approval and question screens are keyboard-first
  (`a`/`r`, number keys) and the diff scrolls, colourises and reports
  `+added -removed`.

- The verify step now runs the checks configured in Settings and feeds the real
  output into the repair prompt; with nothing configured, preflight reports
  the tools as unhealthy instead of silently passing.
- The Phase 0 baseline now measures wall-clock time per task and reports the
  mean time per task: the latency budget is a per-installation property of the
  chosen model, so it is measured, never assumed.

### Fixed

- **TUI layout overlapped itself.** The request input was docked to the
  bottom, so it sat on top of the footer, and the plan/log surfaces spilled
  long lines past their panes. The layout is now a single stacked column
  (header, the two panes, the request input, footer) with the panes taking
  the remaining height, the plan and event surfaces wrapping instead of
  spilling, and a geometry test at three terminal sizes that fails on any
  partial overlap.
- The patch tool's preview rejected every diff that **creates a file** (it
  pre-created an empty sandbox copy, so `git apply` refused), which made the
  agent loop silently skip new-file patches while `apply` accepted them. New
  files now preview and apply identically, and `apply` creates missing parent
  directories.
- `SmbrApp.run_agent` referenced `Exit` without importing it — unreachable
  before, because nothing ever started a run from the interface.

## [0.1.0] - 2026-10-11

Initial scaffold, built directly from the design document
(`SMBR Small Model, Big Results — Design Document.md`).

### Added

- **Frozen kernel skeleton** — 7-step state machine (intake, clarify, preflight,
  plan, edit, verify, report), 3 exits (done, stuck, halted), edit-attempt
  budget driving the single repair loop, and gate evaluation on every
  transition and action.
- **Gates as code** — read-before-edit, symbol-check, verify-before-done,
  grounded-claims, comment-hygiene and declared-capabilities gates, with
  harness-filled message templates and logged user overrides.
- **Preflight capability check** — constrained capability enum, strict JSON
  manifest parsing, three failure types (not installed / unhealthy / not
  permitted), and the tool registry with per-step tool exposure.
- **Clarification slot filling** — per-task-type required-slot schemas,
  evidence-backed extraction, mandatory question phase (capped at 3 per
  round) that blocks planning while slots are missing.
- **Decision layer** — `DecisionProvider` protocol (`choice` / `score` /
  `boolean`), constrained-JSON fallback provider, decision profiles, and a
  router where low confidence always routes to the user.
- **Tools** — file read, code search, tree-sitter symbol lookup for Python,
  pytest / ruff / type-check runners, all behind one registry with health
  checks.
- **Code hygiene** — tree-sitter comment inspection for added comments,
  detecting comments that restate the next line and commented-out code.
- **TUI skeleton** — Textual app showing the current step, gate results, and
  the live tool-call log.
- Tooling — `uv`-installable packaging, ruff + pytest configuration,
  pre-commit, GitHub Actions CI (Python 3.11 and 3.14).

### Status

Kernel, gates, preflight and clarification logic are implemented and tested.
Model backends and the evaluation baseline (Phase 0 of the roadmap) are not
implemented yet — see `docs/roadmap.md`.

[0.1.0]: https://github.com/os-guy-original/smbr/releases/tag/v0.1.0
