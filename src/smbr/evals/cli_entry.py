"""``smbr eval``: run the baseline suite and print the raw scores.

Kept out of ``smbr/cli.py`` so the CLI stays importable while the model backend
is still landing — the import below is deliberately lazy.
"""

from __future__ import annotations

import argparse
import inspect
import sys
from pathlib import Path

from smbr.config import Settings
from smbr.decisions.provider import CompletionClient
from smbr.evals.runner import BaselineReport, run_baseline
from smbr.evals.suite import load_suite


def run_eval(argv: list[str]) -> int:
    """Score the suite with one small model and no harness. Returns an exit code."""
    parser = argparse.ArgumentParser(
        prog="smbr eval", description="run the Phase 0 baseline suite and print raw scores"
    )
    parser.add_argument("--suite", default="evals/tasks", help="directory of task JSON files")
    parser.add_argument("--model", default=_default_model(), help="model to score the suite with")
    parser.add_argument("--out", default=None, help="write a JSON report to this path")
    args = parser.parse_args(argv)

    try:
        tasks = load_suite(Path(args.suite))
    except ValueError as exc:
        print(f"smbr: {exc}", file=sys.stderr)
        return 2
    if not tasks:
        print(f"smbr: no tasks in {args.suite}", file=sys.stderr)
        return 2

    try:
        client = _build_client(args.model)
    except ValueError as exc:  # e.g. openai backend without an API key
        print(f"smbr: {exc}", file=sys.stderr)
        return 2
    report = run_baseline(tasks, client)
    _print_table(report)
    if args.out:
        report.to_json(args.out)
        print(f"report written to {args.out}")
    return 0


def _default_model() -> str:
    """The configured model, tolerating a Settings that has no model field yet."""
    try:
        return str(getattr(Settings(), "model", "") or "")
    except Exception:  # a broken .env must not take this command down
        return ""


def _build_client(model: str) -> CompletionClient:
    """Build the model backend. A missing backend fails loudly, not silently."""
    try:
        from smbr.agent.client import build_completion_client
    except ImportError as exc:
        raise SystemExit(
            "smbr eval: no model backend available (smbr.agent.client is missing); "
            "install the model extra first"
        ) from exc
    takes_settings = "settings" in inspect.signature(build_completion_client).parameters
    if takes_settings:
        settings = Settings()
        if model and "model" in Settings.model_fields:
            settings.model = model  # --model overrides the configured default
        return build_completion_client(settings)
    if model:
        return build_completion_client(model=model)
    return build_completion_client()


def _print_table(report: BaselineReport) -> None:
    for result in report.results:
        detail = result.error or ("ok" if result.score else _first_line(result.check_output))
        level = f"d{result.difficulty}"
        print(
            f"{result.task_id:<20} {level:<3} {result.score:.1f}"
            f"  {result.elapsed_s:>6.1f}s  {detail}"
        )
    per_level = "  ".join(
        f"d{level}: {score:.2f}" for level, score in report.by_difficulty().items()
    )
    print(f"mean score: {report.mean_score:.2f}  ({per_level})")
    print(f"mean time per task: {report.mean_elapsed_s:.1f}s")


def _first_line(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[0][:80] if lines else ""
