"""Code hygiene: tree-sitter comment checks on added comments."""

from smbr.hygiene.comments import (
    Finding,
    added_comments,
    classify,
    comment_findings,
)

__all__ = [
    "Finding",
    "added_comments",
    "classify",
    "comment_findings",
]
