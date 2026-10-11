"""The baseline runner: one small model, one shot per task, raw score.

No gates, no repair loop, no decision layer — that is the point. Every later
layer is measured against the number this produces, so the runner stays dumb on
purpose and never lets a failure raise.
"""

from __future__ import annotations

import json
import shlex
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from smbr.decisions.provider import CompletionClient
from smbr.evals.suite import Task
from smbr.tools.checks import run_check

# The one shape the model may answer in: the files to write. Anything else is a
# failed task, never a partially credited one.
FILE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    "required": ["files"],
}


@dataclass
class TaskResult:
    """Raw outcome of one task. No interpretation, no partial credit."""

    task_id: str
    difficulty: int
    score: float
    check_output: str
    files_written: int
    error: str | None
    # Wall-clock seconds for the whole task (model call plus check).
    # The latency budget is per installation, so it is measured here,
    # never assumed.
    elapsed_s: float = 0.0


@dataclass
class BaselineReport:
    """The suite's scores, aggregated. This is the number later layers beat."""

    results: list[TaskResult]

    @property
    def mean_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(result.score for result in self.results) / len(self.results)

    @property
    def mean_elapsed_s(self) -> float:
        if not self.results:
            return 0.0
        return sum(result.elapsed_s for result in self.results) / len(self.results)

    def by_difficulty(self) -> dict[int, float]:
        buckets: dict[int, list[float]] = {}
        for result in self.results:
            buckets.setdefault(result.difficulty, []).append(result.score)
        return {level: sum(v) / len(v) for level, v in sorted(buckets.items())}

    def to_json(self, path: Path | str) -> Path:
        """Write the report next to its results, creating parent dirs."""
        payload = {
            "mean_score": round(self.mean_score, 4),
            "mean_elapsed_s": round(self.mean_elapsed_s, 3),
            "by_difficulty": {str(k): round(v, 4) for k, v in self.by_difficulty().items()},
            "results": [asdict(result) for result in self.results],
        }
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return target


def run_baseline(
    tasks: list[Task],
    client: CompletionClient,
    *,
    keep_going: bool = True,
    workdir_root: Path | str | None = None,
) -> BaselineReport:
    """Score every task with exactly one model call each.

    ``keep_going=False`` stops at the first failure, which is what you want when
    triaging a suite edit. Work directories survive the run so a failure can be
    inspected; pass ``workdir_root`` to keep them inside a chosen tree.
    """
    root = Path(workdir_root) if workdir_root is not None else None
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
    results: list[TaskResult] = []
    for task in tasks:
        result = _run_task(task, client, root)
        results.append(result)
        if not keep_going and result.score < 1.0:
            break
    return BaselineReport(results)


def _run_task(task: Task, client: CompletionClient, root: Path | None) -> TaskResult:
    started = time.perf_counter()
    workdir = Path(
        tempfile.mkdtemp(prefix=f"{task.id}-", dir=str(root) if root is not None else None)
    )
    for rel, content in task.setup.items():
        _write(workdir, rel, content)

    try:
        answer = client.complete_json(_prompt(task), FILE_SCHEMA)
    except Exception as exc:  # a dead backend is a zero, never a crashed run
        return _result(task, 0.0, "", 0, f"client error: {exc}", started)
    try:
        files = _files_from(answer)
    except ValueError as exc:
        return _result(task, 0.0, "", 0, f"malformed answer: {exc}", started)

    problems: list[str] = []
    written = 0
    for rel, content in files:
        if _safe_target(workdir, rel) is None:
            problems.append(f"refused path outside the workdir: {rel}")
            continue
        _write(workdir, rel, content)
        written += 1

    check_output, passed, unavailable = _run_check(task, workdir)
    # expect_files are fixture input, so they are resolved against the workdir
    # without the sanitising that model output gets.
    missing = [rel for rel in task.expect_files if not (workdir / rel).exists()]
    if missing:
        problems.append("missing expected files: " + ", ".join(missing))
    if unavailable:
        problems.append(unavailable)
    score = 1.0 if passed and not missing else 0.0
    error = "; ".join(problems) if problems else None
    return _result(task, score, check_output, written, error, started)


def _elapsed(started: float) -> float:
    return round(time.perf_counter() - started, 3)


def _result(
    task: Task,
    score: float,
    check_output: str,
    written: int,
    error: str | None,
    started: float,
) -> TaskResult:
    return TaskResult(
        task.id, task.difficulty, score, check_output, written, error, _elapsed(started)
    )


def _run_check(task: Task, workdir: Path) -> tuple[str, bool, str | None]:
    """Run the task's command. Returns (output, passed, problem); never raises."""
    try:
        check = run_check(_argv(task.run), cwd=str(workdir))
    except Exception as exc:  # a missing binary or a timeout is a zero, not a crash
        message = f"check could not run: {exc}"
        return message, False, message
    return check.output, check.passed, None


def _prompt(task: Task) -> str:
    listed = "\n".join(f"- {path}" for path in sorted(task.setup)) or "- (none)"
    return (
        f"{task.prompt}\n\n"
        f"These files already exist in the working directory:\n{listed}\n\n"
        "Return every file the task needs as a whole file, in one answer."
    )


def _files_from(answer: object) -> list[tuple[str, str]]:
    """Pull (path, content) pairs out of the model's answer, or fail loudly."""
    if not isinstance(answer, dict):
        msg = f"expected a JSON object, got {type(answer).__name__}"
        raise ValueError(msg)
    files = answer.get("files")
    if not isinstance(files, list):
        msg = "'files' must be an array"
        raise ValueError(msg)
    pairs: list[tuple[str, str]] = []
    for entry in files:
        path = entry.get("path") if isinstance(entry, dict) else None
        content = entry.get("content") if isinstance(entry, dict) else None
        if not isinstance(path, str) or not isinstance(content, str):
            msg = f"each file needs a 'path' and 'content' string, got {entry!r}"
            raise ValueError(msg)
        pairs.append((path, content))
    return pairs


def _safe_target(workdir: Path, rel: str) -> Path | None:
    """Resolve a model-supplied path inside the workdir, or None if it escapes."""
    candidate = Path(rel)
    if candidate.is_absolute() or ".." in candidate.parts or not rel.strip():
        return None
    return workdir / candidate


def _write(workdir: Path, rel: str, content: str) -> None:
    target = workdir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _argv(command: str) -> tuple[str, ...]:
    """The task's shell string as argv, which is what run_check takes."""
    try:
        parts = shlex.split(command)
    except ValueError:  # unbalanced quotes: let a shell sort it out
        return ("bash", "-c", command)
    return tuple(parts)
