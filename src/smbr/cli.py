"""Command-line entry point.

``smbr preflight`` checks a capability manifest against the real tool
registry. ``smbr run`` drives one request through the kernel with a local
model. ``smbr eval`` runs the Phase 0 baseline. ``smbr import`` brings
MCP servers and skills in from other agents, disabled and inert.
``smbr skills`` lists what was imported. ``smbr tui`` launches the
interface.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from smbr import __version__
from smbr.config import Settings
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


def _cmd_import(args: argparse.Namespace) -> int:
    from smbr.imports import cli_entry

    return cli_entry.run_import(args)


def _cmd_skills(args: argparse.Namespace) -> int:
    from smbr.imports import cli_entry

    return cli_entry.run_skills(args)


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


def _cmd_run(args: argparse.Namespace) -> int:
    from smbr.agent import CliUser, SmbrAgent, build_completion_client, build_decision_router

    settings = Settings(project_root=Path.cwd())
    try:
        client = build_completion_client(settings)
    except ValueError as exc:  # e.g. openai backend without an API key
        print(f"smbr: {exc}", file=sys.stderr)
        return 2
    router = build_decision_router(settings, client)
    agent = SmbrAgent(settings=settings, client=client, user=CliUser(), router=router)
    result = agent.run(args.request)
    print(f"\nrun finished: {result.exit.value} - {result.reason}")
    if result.overrides:
        print(f"gate overrides this run: {len(result.overrides)}")
    return 0 if result.exit.value == "done" else 1


def _cmd_eval(args: argparse.Namespace) -> int:
    from smbr.evals.cli_entry import run_eval

    return run_eval(args.eval_args)


def _cmd_tui(args: argparse.Namespace) -> int:
    from smbr.tui import SmbrApp

    app = SmbrApp(request=args.request, demo=args.demo)
    app.run()
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

    run = sub.add_parser("run", help="run one coding request through the harness")
    run.add_argument("request", help="the coding request in plain language")
    run.set_defaults(func=_cmd_run)

    ev = sub.add_parser("eval", help="run the Phase 0 evaluation baseline")
    ev.add_argument("eval_args", nargs=argparse.REMAINDER, help="arguments for the eval runner")
    ev.set_defaults(func=_cmd_eval)

    imp = sub.add_parser("import", help="import MCP servers or skills from other agents")
    imp.add_argument(
        "what",
        choices=("scan", "mcp", "skills"),
        help="scan reports what is available; mcp and skills write it to disk",
    )
    imp.add_argument(
        "--from",
        dest="sources",
        action="append",
        default=[],
        help="source agent(s) to read (repeatable; default: every known source)",
    )
    imp.add_argument(
        "--path",
        dest="paths",
        action="append",
        default=[],
        help="explicit config or skill-root path (repeatable)",
    )
    imp.add_argument(
        "--force", action="store_true", help="replace existing entries on a name conflict"
    )
    imp.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would happen without writing anything",
    )
    imp.set_defaults(func=_cmd_import)

    skl = sub.add_parser("skills", help="list imported skills with their provenance")
    skl.set_defaults(func=_cmd_skills)

    tui = sub.add_parser("tui", help="launch the TUI")
    tui.add_argument(
        "--request",
        default=None,
        help="run this request as soon as the interface is up",
    )
    tui.add_argument(
        "--demo",
        action="store_true",
        help="drive the run with a canned model, so the flow needs no server",
    )
    tui.set_defaults(func=_cmd_tui)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "eval":
        # eval owns its own flags; the main parser would choke on them
        from smbr.evals.cli_entry import run_eval

        return run_eval(argv[1:])
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
