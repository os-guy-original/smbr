# Roadmap

Each phase ends at a gate that must pass before the next begins. Phase 0 comes
first so every later layer can be measured against raw scores; the improvement
loop waits until the evaluation is trustworthy.

| Phase | Contents | Exit gate |
| --- | --- | --- |
| **0 — Baseline** | One small model, 20–30 coding tasks of rising difficulty, raw scores with no harness | Baseline numbers exist and are reproducible |
| **1 — Kernel** ✅ *scaffolded* | State machine, gates, preflight, clarification, per-step tool exposure | Gates demonstrably block the failures from Phase 0 |
| **2 — Decision layer** ✅ *interfaces* | `DecisionProvider` protocol, constrained-JSON fallback, decision profiles | Each backend beats the fallback on our own labeled examples |
| **3 — TUI** 🚧 *skeleton* | Step/plan display, gate results, tool-call log, clarification prompts, diff approval | A user can always see what the agent was allowed to do |
| **4 — Improvement loop** | Offline improver proposes mutable-layer changes; accepted only on held-out wins | No mutable change ships without a held-out eval win |

*Legend: ✅ interfaces/logic implemented and tested · 🚧 skeleton only · not yet started: Phase 0 baseline suite, model backend wiring, MCP import adapter, comment-hygiene decision-layer wiring.*

## Open decisions

| Decision | Current default | Alternatives | Status |
| --- | --- | --- | --- |
| Implementation language | Python + Textual | Rust or Go single binary | **Resolved for scaffold: Python** |
| Hardware and target model size | Not chosen | 7B–14B via Ollama or llama.cpp | **Open** — sets the latency budget for every gate |
| Language focus for v1 | Python (tree-sitter, pytest, ruff) | TypeScript | **Resolved for scaffold: Python** |

**Confirm next:** the user's hardware and target model size, because that sets
the latency budget for every gate.
