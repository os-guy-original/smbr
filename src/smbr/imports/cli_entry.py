"""The ``smbr import`` and ``smbr skills`` commands.

``smbr import scan`` is read-only and shows every other agent's
servers and skills this machine has. ``smbr import mcp`` writes them
into ``.smbr/mcp.json`` disabled — the user reviews and enables.
``smbr import skills`` copies them into ``.smbr/skills`` with a
provenance manifest. Nothing is enabled by an import.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from smbr.config import Settings


def _settings() -> Settings:
    return Settings(project_root=Path.cwd())


def _resolve_paths(args: argparse.Namespace, kind: str) -> tuple[list[Path], list[str]]:
    """Paths to read and the labels to attribute them to."""
    from smbr.imports.sources import named_sources, skill_roots, source_paths

    settings = _settings()
    root = settings.project_root
    explicit = [Path(p).expanduser() for p in args.paths]
    if args.sources:
        specs = named_sources(root)
        unknown = [s for s in args.sources if s not in specs]
        if unknown:
            print(
                f"smbr: unknown source(s): {', '.join(unknown)} "
                f"(known: {', '.join(sorted(specs))})",
                file=sys.stderr,
            )
            return [], [f"unknown source(s): {', '.join(unknown)}"]
        paths: list[Path] = []
        roots: list[Path] = []
        for name in args.sources:
            spec = specs[name]
            paths.extend(spec.paths)
            roots.extend(spec.skill_roots)
    else:
        paths = source_paths(root)
        roots = skill_roots(root)
    return (explicit + paths if kind == "mcp" else explicit + roots), []


def run_import(args: argparse.Namespace) -> int:
    from smbr.imports import discover_mcp, discover_skills, merge_servers

    settings = _settings()
    root = settings.project_root
    if args.what == "scan":
        return _scan(root, settings)
    if args.what == "mcp":
        paths, errors = _resolve_paths(args, "mcp")
        if errors:
            return 2
        results = discover_mcp(paths, root)
        servers = [server for result in results for server in result.servers]
        target = root / settings.mcp_config
        report = merge_servers(servers, target, force=args.force, dry_run=args.dry_run)
        if args.dry_run:
            print("dry run: nothing was written")
        _print_mcp_report(report, results, target)
        return 1 if report.conflicts and not args.force else 0
    # skills
    roots, errors = _resolve_paths(args, "skills")
    if errors:
        return 2
    found = discover_skills(roots)
    if not found:
        print("no skills found in the given locations")
        return 0
    skills_dir = root / settings.skills_dir
    manifest = root / ".smbr" / "skills.json"
    report = _import_found_skills(found, skills_dir, manifest, args)
    for name in report.imported:
        print(f"imported: {name} -> {skills_dir / name}")
    for name, reason in report.skipped:
        print(f"skipped: {name} ({reason})")
    if args.dry_run:
        print("dry run: nothing was written")
    return 0


def _import_found_skills(found, skills_dir, manifest, args):
    from smbr.imports import import_skills

    return import_skills(found, skills_dir, manifest, force=args.force, dry_run=args.dry_run)


def _print_mcp_report(report, results, target: Path) -> None:
    for name in report.added:
        print(f"added: {name} (disabled — review {target}, then set enabled: true)")
    for name in report.updated:
        print(f"updated: {name}")
    for name in report.conflicts:
        print(f"conflict: {name} already exists with a different shape (use --force)")
    for name in report.unchanged:
        print(f"unchanged: {name}")
    for result in results:
        for skipped in result.skipped:
            print(f"skipped: {skipped.name} from {result.origin} ({skipped.reason})")
        if result.error:
            print(f"note: {result.origin}: {result.error}")
    if not (report.added or report.updated or report.conflicts or report.unchanged):
        print("no importable MCP servers found")


def _scan(root: Path, settings: Settings) -> int:
    from smbr.imports.discovery import discover_mcp, discover_skills, skill_description
    from smbr.imports.sources import named_sources, skill_roots, source_paths

    specs = named_sources(root)
    print("MCP servers:")
    results = discover_mcp(source_paths(root), root)
    for spec in specs.values():
        for path in spec.paths:
            if not path.is_file():
                continue
            result = next((r for r in results if r.origin == str(path)), None)
            if result is None:
                continue
            print(f"  {spec.label} — {path}")
            if result.error:
                print(f"    (unreadable: {result.error})")
            for server in result.servers:
                command = " ".join([server.command, *server.args]).strip()
                extra = f" [env {', '.join(sorted(server.env))}]" if server.env else ""
                print(f"    {server.name}: {command}{extra}")
            for skipped in result.skipped:
                print(f"    {skipped.name}: skipped — {skipped.reason}")
    print("Skills:")
    for skill in discover_skills(skill_roots(root)):
        summary = skill_description(skill.path)
        print(f"  {skill.name} — {skill.path}" + (f": {summary[:90]}" if summary else ""))
    print("\nReview-then-enable: 'smbr import mcp' and 'smbr import skills' write these")
    print("disabled and inert; nothing runs until you enable it.")
    return 0


def run_skills(args: argparse.Namespace) -> int:
    from smbr.imports import load_manifest

    settings = _settings()
    manifest = settings.project_root / ".smbr" / "skills.json"
    entries = load_manifest(manifest)
    if not entries:
        print(f"no imported skills ({manifest} has none; run 'smbr import skills')")
        return 0
    for entry in entries:
        print(f"{entry.get('name')}: {entry.get('description') or '(no description)'}")
        print(f"    from {entry.get('source')}")
        print(f"    sha256 {str(entry.get('sha256'))[:12]}…")
    return 0
