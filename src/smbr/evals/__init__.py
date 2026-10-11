"""Evaluation baseline: the Phase 0 raw-score suite and its runner.

A frozen yardstick. The tasks and the scoring here never move to make a later
layer look good, so "the harness raised the score" means something.
"""

from smbr.evals.cli_entry import run_eval
from smbr.evals.runner import FILE_SCHEMA, BaselineReport, TaskResult, run_baseline
from smbr.evals.suite import Task, load_suite

__all__ = [
    "FILE_SCHEMA",
    "BaselineReport",
    "Task",
    "TaskResult",
    "load_suite",
    "run_baseline",
    "run_eval",
]
