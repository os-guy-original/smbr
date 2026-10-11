"""Tree-sitter symbol lookup for Python files.

Every function, class and import the model wants to use must be confirmed
here first — the symbol-check gate refuses edits built on unconfirmed names.
Verified against tree-sitter 0.26 / tree-sitter-python 0.25.
"""

from __future__ import annotations

from dataclasses import dataclass

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from smbr.preflight.capabilities import Capability
from smbr.tools.registry import ToolHealth

_PY = Language(tree_sitter_python.language())


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str  # "function" | "class" | "import"
    line: int  # 1-based
    end_line: int  # 1-based, inclusive

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.name}"


def _walk(node: Node, source: bytes, out: list[Symbol]) -> None:
    if node.type == "function_definition":
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            text = _text(name_node, source)
            out.append(Symbol(text, "function", node.start_point[0] + 1, node.end_point[0] + 1))
    elif node.type == "class_definition":
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            text = _text(name_node, source)
            out.append(Symbol(text, "class", node.start_point[0] + 1, node.end_point[0] + 1))
    elif node.type == "import_statement":
        for child in node.children:
            if child.type == "dotted_name":
                out.append(
                    Symbol(
                        _text(child, source),
                        "import",
                        node.start_point[0] + 1,
                        node.end_point[0] + 1,
                    )
                )
    elif node.type == "import_from_statement":
        for child in node.children:
            if child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                if name_node is not None:
                    out.append(
                        Symbol(
                            _text(name_node, source),
                            "import",
                            node.start_point[0] + 1,
                            node.end_point[0] + 1,
                        )
                    )
            elif child.type == "dotted_name":
                # `from x import y` — y is a plain dotted_name identifier here.
                parent_text = _text(node, source)
                if " import " in parent_text:
                    out.append(
                        Symbol(
                            _text(child, source),
                            "import",
                            node.start_point[0] + 1,
                            node.end_point[0] + 1,
                        )
                    )
    for child in node.children:
        _walk(child, source, out)


def _text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def index_source(source: str) -> list[Symbol]:
    """All symbols in a Python source string, in source order."""
    parser = Parser(_PY)
    tree = parser.parse(source.encode("utf-8"))
    symbols: list[Symbol] = []
    _walk(tree.root_node, source.encode("utf-8"), symbols)
    return symbols


def lookup_symbol(source: str, name: str) -> Symbol | None:
    """Confirm a single symbol exists in the source. None means unconfirmed."""
    for symbol in index_source(source):
        if symbol.name == name:
            return symbol
    return None


class SymbolLookupTool:
    name = "symbol_lookup"
    capability = Capability.SYMBOL_LOOKUP

    def health(self) -> ToolHealth:
        try:
            index_source("def _healthcheck(): pass")
        except Exception as exc:  # a health check must never raise
            return ToolHealth.broken(self.capability, f"tree-sitter failed: {exc}")
        return ToolHealth.ok(self.capability, "tree-sitter parser loaded")

    def lookup(self, source: str, name: str) -> Symbol | None:
        return lookup_symbol(source, name)
