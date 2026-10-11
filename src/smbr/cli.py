"""Command-line entry point.

``smbr preflight`` is genuinely useful today: it parses a capability manifest
and checks it against the real tool registry, printing harness-written
warnings for anything missing, unhealthy or blocked.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from smbr import __version__
from smbr.preflight import (
    Capability,
    ManifestParseError,
    check_manifest,
    parse_manifest,
)
from smbr.tools.registry import default_registry


def _cmd_version(_: argparse.Namespace) -> int:
    print(f"smbr {__version__}")
    return 0


def _cmd_preflight(args: argparse.Namespace) -> int:
    try:
        manifest = parse_manifest(Path(args.manifest).read_text(encoding="utf-8"))
    except (OSError, ManifestParseError) as exc:
        print(f"smbr: cannot read manifest: {exc}", file=sys.stderr)
        return 2
    registry = default_registry(cwd=str(Path(args.manifest).resolve().parent))
    permitted = (
        frozenset(Capability(c.strip()) for c in args.permit.split(",") if c.strip())
        if args.permit
        else None
    )
    failures = check_manifest(manifest, registry, permitted=permitted)
    if failures:
        for failure in failures:
            print(failure.message())  # harness template, never model prose
        return 1
    print(f"preflight ok: {len(manifest.requires)} capability(ies) available")
    return 0


def _cmd_tui(_: argparse.Namespace) -> int:
    from smbr.tui import SmbrApp

    SmbrApp().run()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="smbr", description=__doc__)
    parser.add_argument("--version", action="version", version=f"smbr {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="print the version").set_defaults(func=_cmd_version)

    pre = sub.add_parser("preflight", help="check a capability manifest")
    pre.add_argument("manifest", help="path to the JSON manifest")
    pre.add_argument(
        "--permit",
        default="",
        help="comma-separated capability allow-list (policy check)",
    )
    pre.set_defaults(func=_cmd_preflight)

    sub.add_parser("tui", help="launch the TUI").set_defaults(func=_cmd_tui)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
