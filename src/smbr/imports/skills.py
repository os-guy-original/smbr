"""Importing skills from other agents — with the guardrails on.

A skill is untrusted text (a prompt-injection path, per the design
doc), so the import is deliberately conservative: it copies a known
shape (a folder with SKILL.md), refuses to follow anything that
escapes the source root, caps size, records provenance in a manifest,
and never enables anything. Same gates, same permissions as everything
else — the manifest is the audit trail, the files are inert data until
the harness uses them under the kernel.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from smbr.imports.discovery import SKILL_FILE, SkillFound, skill_description

#: Safety caps for the copy: skills are instructions, not data dumps.
MAX_SKILL_BYTES = 8 * 1024 * 1024
MAX_SKILL_FILES = 500


@dataclass
class SkillImportReport:
    """What one skill import did."""

    imported: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (name, reason)
    dry_run: bool = False


def load_manifest(path: Path) -> list[dict]:
    """The provenance manifest, or an empty one."""
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = doc.get("skills") if isinstance(doc, dict) else doc
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_skills(
    skills: list[SkillFound],
    target_root: Path,
    manifest_path: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> SkillImportReport:
    """Copy skills into the SMBR skill store with provenance recorded."""
    report = SkillImportReport(dry_run=dry_run)
    manifest = load_manifest(manifest_path)
    by_name = {str(entry.get("name")): entry for entry in manifest}
    for skill in skills:
        source_file = skill.path / SKILL_FILE
        try:
            digest = sha256_of(source_file)
        except OSError as exc:
            report.skipped.append((skill.name, f"cannot read SKILL.md: {exc}"))
            continue
        previous = by_name.get(skill.name)
        if previous and previous.get("sha256") == digest and not force:
            report.skipped.append((skill.name, "already imported, unchanged"))
            continue
        destination = target_root / skill.name
        if destination.exists() and not force:
            report.skipped.append((skill.name, "a skill with that name exists (use --force)"))
            continue
        try:
            _copy_skill(skill.path, destination, dry_run=dry_run)
        except (OSError, ValueError) as exc:
            report.skipped.append((skill.name, str(exc)))
            continue
        report.imported.append(skill.name)
        entry = {
            "name": skill.name,
            "source": str(skill.path),
            "origin": skill.origin,
            "sha256": digest,
            "description": skill_description(skill.path),
            "imported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        by_name[skill.name] = entry
    if not dry_run and report.imported:
        _write_manifest(manifest_path, list(by_name.values()))
    return report


def _copy_skill(source: Path, destination: Path, *, dry_run: bool) -> None:
    """Copy a skill folder, refusing escapes, symlinks and oversize trees."""
    source_root = source.resolve()
    files: list[Path] = []
    total = 0
    for path in sorted(source.rglob("*")):
        if source_root not in path.resolve().parents:
            msg = f"{path} escapes the skill folder"
            raise ValueError(msg)
        if path.is_symlink() or not path.is_file():
            continue
        total += path.stat().st_size
        if total > MAX_SKILL_BYTES:
            msg = f"skill exceeds the {MAX_SKILL_BYTES // (1024 * 1024)} MiB import cap"
            raise ValueError(msg)
        files.append(path)
        if len(files) > MAX_SKILL_FILES:
            msg = f"skill exceeds the {MAX_SKILL_FILES}-file import cap"
            raise ValueError(msg)
    if dry_run:
        return
    if destination.exists():
        shutil.rmtree(destination)
    for path in files:
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def _write_manifest(path: Path, entries: list[dict]) -> None:
    from smbr.imports.mcp_config import write_json_atomic

    write_json_atomic(path, {"skills": sorted(entries, key=lambda e: str(e.get("name")))})
