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
(`smbr eval`); the task set is being grown toward the 20–30 target and the
baseline run itself is pending a local model server. Phase 3's TUI has the
live surfaces and modal screens; layout polish remains.

## Open decisions

| Decision | Current default | Alternatives | Status |
| --- | --- | --- | --- |
| Implementation language | Python + Textual | Rust or Go single binary | **Resolved: Python** |
| Hardware and target model size | `gemma4:e4b` via Ollama (override with `SMBR_MODEL`) | qwen2.5-coder 7b/14b, qwen3-coder:30b-a3b | **Default set; hardware still unconfirmed** — it sets the latency budget for every gate |
| Language focus for v1 | Python (tree-sitter, pytest, ruff) | TypeScript | **Resolved: Python** |

**Confirm next:** the user's hardware, because it sets the latency budget for
every gate — especially which decision backend is fast enough to sit in the
hot path.
