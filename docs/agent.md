# The agent loop

`smbr.agent` is where the frozen kernel meets a local model. It contains no
kernel logic — only step handlers that ask the model one constrained-JSON
question at a time and feed the answers (and the tool results) back into the
state machine.

## The model contract

Every question is answered in constrained JSON with a fixed schema
(`smbr/agent/prompts.py`). The enums in those schemas mirror the harness
vocabularies (`Capability`, `TaskType`), so the model can only name tools and
task types that exist; `unknown_capability` and `null` are first-class
answers. A malformed answer, a failed backend, or a non-object response is
"no answer": the run halts with a harness message instead of guessing.

| Step | Model question | Schema |
| --- | --- | --- |
| intake | classify the request, extract slots with evidence | `INTAKE_SCHEMA` |
| clarify | phrase the question for one missing slot | `SLOT_QUESTION_SCHEMA` |
| preflight | declare the capabilities the task needs | `MANIFEST_SCHEMA` |
| plan | decompose into the smallest checkable steps | `PLAN_SCHEMA` |
| edit | produce a minimal unified diff for one file | `PATCH_SCHEMA` |
| report | summarize with claims citing tool-result ids | `CLAIMS_SCHEMA` |

## What happens on an edit

1. The file is read through the tool (recorded on the session — this is what
   the read-before-edit gate checks).
2. The model proposes a diff plus the symbols it uses. The diff is applied to
   a throwaway sandbox copy first (`git apply`, verified to work outside a
   git repo); the tree is untouched until the user approves.
3. The comment-hygiene check runs on the sandbox result. A restating comment
   or commented-out code sends the patch back for exactly one bounded
   revision; a still-dirty patch is shown to the user with its findings.
4. The action gates run (read-before-edit, symbol check, comment hygiene,
   declared capabilities). A refusal surfaces the harness message and offers
   override-or-skip; an override is logged.
5. The user approves the diff, and only then does it touch the working tree.

## User port

The loop never touches a terminal directly. Interrupts go through
`UserPort` (`ask` / `notify` / `approve_patch`), implemented by:

- `CliUser` — stdin prompts, used by `smbr run`.
- `TuiUser` — Textual modal screens (`QuestionScreen`, `ApprovalScreen`),
  crossing to the UI thread via `call_from_thread`.
- `RecordingUser` — scripted answers for tests.

## Backends

`build_completion_client(settings)` returns a `CompletionClient`:

- Ollama (`smbr[ollama]`), using `format=<json-schema>` for constrained
  decoding. Default model: `gemma4:e4b` (real tag, verified in the Ollama
  library); override with `SMBR_MODEL` or the `--model` flag where offered.
- llama.cpp server (OpenAI-compatible endpoint). **UNVERIFIED against a
  running server** — no server is available in CI; treat the first real run
  as verification.

The kernel and gates import no backend. With `SMBR_DECISION_PROVIDER=off`,
the decision layer is the disabled provider and SMBR asks the user every
time.

## Failure policy

| Failure | Behavior |
| --- | --- |
| Model backend unreachable | Run halts: "model unavailable: ..." |
| Non-JSON or schema-invalid answer | Halts, or (intake) all slots go missing → clarification |
| Diff does not apply | Step skipped with a harness message; verify decides |
| Unconfirmed symbol | Edit refused; override or skip, user's choice |
| Checks fail | Repair loop: failing output is fed back into the next patch prompt |
| Budget spent | Exit `stuck` with the history intact |
