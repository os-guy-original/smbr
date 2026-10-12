"""Shared test scaffolding: a model scripted by schema shape.

The agent loop asks the model constrained-JSON questions; this
client answers them from a fixed script, so every test drives the
real loop with no model server behind it. Both agent-loop test
modules import it, so the scripted shapes stay in one place.
"""

from __future__ import annotations

import difflib

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
COMMENTED = "def add(a, b):\n    # return a plus b\n    return a + b\n"
MULTIPLY = "def add(a, b):\n    return a * b\n"

TEST_FILE = "def test_add():\n    from calc import add\n\n    assert add(1, 2) == 3\n"


def diff(path: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


class ScriptedClient:
    """Answers each constrained-JSON question by its schema shape."""

    def __init__(
        self,
        *,
        symbols=("add",),
        target=FIXED,
        with_comment=False,
        boom=False,
        tool_calls=None,
        mcp=False,
        requires=None,
        claims=None,
    ) -> None:
        self.symbols = symbols
        self.target = target
        self.with_comment = with_comment
        self.boom = boom
        self.tool_calls = tool_calls
        self.mcp = mcp
        self.requires = requires
        self.claims = claims
        self.patch_calls = 0

    def complete_json(self, prompt: str, schema: dict) -> dict:
        from smbr.agent.prompts import (
            CLAIMS_SCHEMA,
            INTAKE_SCHEMA,
            MANIFEST_SCHEMA,
            PATCH_SCHEMA,
            PLAN_SCHEMA,
        )

        if self.boom:
            raise ConnectionError("no model server")
        if schema == INTAKE_SCHEMA:
            return {
                "task_type": "modify_code",
                "slots": [
                    {"name": "objective", "value": "fix add", "evidence": "user said it"},
                    {"name": "location", "value": "calc.py", "evidence": "user said it"},
                    {"name": "scope", "value": "one function", "evidence": "user said it"},
                ],
            }
        if schema == MANIFEST_SCHEMA:
            if self.requires is not None:
                return {"task": "fix add", "requires": self.requires}
            requires = [
                {"capability": "file_read", "why": "read calc.py"},
                {"capability": "symbol_lookup", "why": "confirm add"},
                {"capability": "patch_apply", "why": "apply the fix"},
                {"capability": "test_runner", "why": "verify"},
                {"capability": "linter", "why": "lint"},
            ]
            if self.mcp:
                requires.append({"capability": "mcp", "why": "external tools"})
            return {"task": "fix add", "requires": requires}
        if schema == PLAN_SCHEMA:
            return {"steps": [{"what": "fix the subtraction bug", "files": ["calc.py"]}]}
        if schema == PATCH_SCHEMA:
            self.patch_calls += 1
            # the first patch optionally adds a restating comment for hygiene to catch
            target = COMMENTED if self.with_comment and self.patch_calls == 1 else self.target
            answer = {
                "path": "calc.py",
                "diff": diff("calc.py", BUGGY, target),
                "symbols_used": list(self.symbols),
            }
            if self.tool_calls is not None:
                answer["tool_calls"] = self.tool_calls
            return answer
        if schema == CLAIMS_SCHEMA:
            if self.claims is not None:
                return self.claims
            return {"claims": [{"text": "fixed add", "evidence": ["tool-3: patch_apply calc.py"]}]}
        msg = f"unexpected schema: {schema}"
        raise AssertionError(msg)
