# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to semantic versioning.

## [Unreleased]

### Added

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

- The verify step now runs the checks configured in Settings and feeds the real
  output into the repair prompt; with nothing configured, preflight reports
  the tools as unhealthy instead of silently passing.
- The Phase 0 baseline now measures wall-clock time per task and reports the
  mean time per task: the latency budget is a per-installation property of the
  chosen model, so it is measured, never assumed.

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
