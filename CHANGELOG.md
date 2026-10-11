# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to semantic versioning.

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

[0.1.0]: https://github.com/<owner>/smbr/releases/tag/v0.1.0
