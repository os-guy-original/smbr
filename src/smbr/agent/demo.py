"""A canned model for trying (and testing) the harness without a backend.

Every answer is a fixed, valid constrained-JSON document, shaped like a
real run: one required slot is left missing so the clarification question
appears, the manifest declares the built-in capabilities, the plan names
one disposable note file, and the patch creates that file. The claims
step cites a real tool-result id parsed out of its own prompt, so the
grounded-claims gate is exercised honestly rather than bypassed.

It exists so ``smbr tui --demo`` and the TUI tests can drive the whole
gated flow — clarification, preflight, approval, verification, report —
on a machine with no model server.
"""

from __future__ import annotations

import re

from smbr.agent.prompts import (
    CLAIMS_SCHEMA,
    INTAKE_SCHEMA,
    MANIFEST_SCHEMA,
    PATCH_SCHEMA,
    PLAN_SCHEMA,
    SLOT_QUESTION_SCHEMA,
)

#: The file the demo run leaves behind; obviously disposable.
DEMO_FILE = "smbr-demo-note.txt"

DEMO_DIFF = (
    "--- /dev/null\n"
    f"+++ b/{DEMO_FILE}\n"
    "@@ -0,0 +1,2 @@\n"
    '+"Written by an SMBR demo run - safe to delete."\n'
    '+"https://github.com/os-guy-original/smbr"\n'
)

_TOOL_ID = re.compile(r"- (tool-\d+: [^\s]+)")


class DemoClient:
    """CompletionClient with scripted answers; no network, no model."""

    def complete_json(self, prompt: str, schema: dict) -> dict:
        if schema == INTAKE_SCHEMA:
            # objective and location are grounded; scope is deliberately
            # missing so the clarification question has something to ask
            return {
                "task_type": "modify_code",
                "slots": [
                    {
                        "name": "objective",
                        "value": "leave a note file as a demo",
                        "evidence": "the user said: demo",
                    },
                    {
                        "name": "location",
                        "value": "the project root",
                        "evidence": "the user said: demo",
                    },
                ],
            }
        if schema == SLOT_QUESTION_SCHEMA:
            return {
                "question": "What should the demo's scope be?",
                "options": ["one file", "the whole repo"],
            }
        if schema == MANIFEST_SCHEMA:
            return {
                "task": "leave a demo note file",
                "requires": [
                    {"capability": "file_read", "why": "read the target path"},
                    {"capability": "patch_apply", "why": "create the note file"},
                    {"capability": "test_runner", "why": "verify nothing broke"},
                    {"capability": "linter", "why": "lint"},
                ],
            }
        if schema == PLAN_SCHEMA:
            return {
                "steps": [{"what": f"create {DEMO_FILE} with the demo note", "files": [DEMO_FILE]}]
            }
        if schema == PATCH_SCHEMA:
            return {"path": DEMO_FILE, "diff": DEMO_DIFF, "symbols_used": []}
        if schema == CLAIMS_SCHEMA:
            # cite a real tool result so the gate can check the citation
            found = _TOOL_ID.search(prompt)
            evidence = [found.group(1)] if found else []
            return {
                "claims": [
                    {
                        "text": f"created {DEMO_FILE} and ran the configured checks",
                        "evidence": evidence,
                    }
                ]
            }
        msg = f"demo client has no scripted answer for this schema: {schema}"
        raise AssertionError(msg)
