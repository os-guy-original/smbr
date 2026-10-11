# Roadmap

Each phase ends at a gate that must pass before the next begins. Phase 0 comes
first so every later layer can be measured against raw scores; the improvement
loop waits until the evaluation is trustworthy.

| Phase | Contents | Exit gate |
| --- | --- | --- |
| **0 — Baseline** | One small model, 20–30 coding tasks of rising difficulty, raw scores with no harness | Baseline numbers exist and are reproducible |
| **1 — Kernel** | State machine, gates, preflight, clarification, per-step tool exposure | Gates demonstrably block the failures from Phase 0 |
| **2 — Decision layer** ✅ | `DecisionProvider` protocol, constrained-JSON fallback, decision profiles | Each backend beats the fallback on our own labeled examples |
| **3 — TUI** | Step/plan display, gate results, tool-call log, clarification prompts, diff approval | A user can always see what the agent was allowed to do |
| **4 — Improvement loop** | Offline improver proposes mutable-layer changes; accepted only on held-out wins | No mutable change ships without a held-out eval win |

**Landed so far (0.1.0):** Phases 1 and 2 wired end to end — the agent loop
(`smbr run`) drives all seven steps with constrained-JSON model calls, real
tools, action and transition gates, the repair loop, patch approval, and a
CLI/TUI user port. Phase 0's suite format, runner and scoring exist
(`smbr eval`, reporting score and time per task); the task set is being
grown toward the 20–30 target and the baseline run itself is pending a
local model server. Phase 3's TUI has the live surfaces and modal screens;
layout polish remains.

## Hardware and model choice

SMBR is hardware-agnostic by design: it runs on whatever the user's
machine can serve through Ollama or llama.cpp. The latency budget is a
per-installation property, so the baseline measures time-per-task instead
of assuming one. Guidance for picking `SMBR_MODEL`:

| RAM class | Model class | Why |
| --- | --- | --- |
| 4–8 GB | 1.5–3B (e.g. `qwen2.5-coder:1.5b`) | Gates stay interactive |
| 8–16 GB | 7B (e.g. `qwen2.5-coder:7b`) | Default sweet spot |
| 16–32 GB | 14B–30B MoE (e.g. `qwen3-coder:30b-a3b`) | Higher quality, still fast |
| 32 GB+ | 32B+ (e.g. `qwen2.5-coder:32b`) | Quality-first |

Slow models multiply the cost of the multi-step loop, so a model that
answers in seconds is worth more than one that answers in minutes.

## Open decisions

| Decision | Current default | Alternatives | Status |
| --- | --- | --- | --- |
| Implementation language | Python + Textual | Rust or Go single binary | **Resolved: Python** |
| Target model size | `gemma4:e4b` (any served model via `SMBR_MODEL`) | the RAM-class table above | **Resolved: any local model; default is a placeholder** |
| Language focus for v1 | Python (tree-sitter, pytest, ruff) | TypeScript | **Resolved: Python** |
