"""Comment hygiene: a mechanical check, not a plea to the model.

After each patch the harness parses the changed files with tree-sitter and
inspects only the comments the patch *added*. Docstrings are string nodes, not
comment nodes, so they are never touched. Anything that merely restates the
next line, or is commented-out code, sends the patch back for revision.

Judging "does this restate the code" is a bounded yes/no question, so it can
go to the decision layer; with the layer off (or at low confidence) the
heuristic below stands on its own.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

import tree_sitter_python
from tree_sitter import Language, Node, Parser

_PY = Language(tree_sitter_python.language())

_STOPWORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "to",
        "of",
        "for",
        "and",
        "or",
        "in",
        "on",
        "at",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "we",
        "you",
        "they",
        "he",
        "she",
        "i",
        "if",
        "then",
        "else",
        "so",
        "as",
        "by",
        "with",
        "from",
        "into",
        "out",
        "up",
        "down",
    ]
)

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class Finding:
    line: int  # 1-based, in the new file
    text: str
    kind: str  # "restates_code" | "commented_out_code"
    detail: str


def _comments(source: str) -> list[tuple[int, str]]:
    parser = Parser(_PY)
    tree = parser.parse(source.encode("utf-8"))
    found: list[tuple[int, str]] = []
    _collect_comments(tree.root_node, source.encode("utf-8"), found)
    return found


def _collect_comments(node: Node, source: bytes, out: list[tuple[int, str]]) -> None:
    if node.type == "comment":
        text = source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
        out.append((node.start_point[0] + 1, text))
    for child in node.children:
        _collect_comments(child, source, out)


def added_comments(before: str, after: str) -> list[tuple[int, str]]:
    """Comments present in `after` but not in `before` (multiset diff)."""
    remaining: dict[str, int] = {}
    for _, text in _comments(before):
        remaining[text] = remaining.get(text, 0) + 1
    added = []
    for line, text in _comments(after):
        if remaining.get(text, 0) > 0:
            remaining[text] -= 1
        else:
            added.append((line, text))
    return added


def _code_line_after(source_lines: list[str], line_no: int) -> str:
    """The next non-empty, non-comment line after the comment."""
    for raw in source_lines[line_no:]:
        stripped = raw.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def _restates(comment: str, code: str) -> bool:
    comment_words = {w.lower() for w in _WORD_RE.findall(comment)} - _STOPWORDS
    code_words = set(_IDENT_RE.findall(code))
    if len(comment_words) < 2:
        return False
    overlap = len(comment_words & code_words)
    return overlap / len(comment_words) >= 0.5


def _commented_out_code(comment: str) -> bool:
    body = comment.lstrip("#").strip()
    if not body:
        return False
    try:
        tree = ast.parse(body)
    except (SyntaxError, ValueError):
        return False
    return bool(tree.body) and not all(
        isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) for stmt in tree.body
    )


def classify(comment: str, code: str) -> str:
    """'keep' | 'restates_code' | 'commented_out_code'."""
    if _commented_out_code(comment):
        return "commented_out_code"
    if _restates(comment, code):
        return "restates_code"
    return "keep"


def comment_findings(before: str, after: str) -> list[Finding]:
    """Hygiene findings for the comments this patch added."""
    lines = after.splitlines()
    findings: list[Finding] = []
    for line_no, text in added_comments(before, after):
        code = _code_line_after(lines, line_no - 1)
        kind = classify(text, code)
        if kind != "keep":
            detail = f"next code line: {code}" if code else "no code follows"
            findings.append(Finding(line_no, text, kind, detail))
    return findings
