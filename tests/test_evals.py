"""The baseline: a suite no task passes without the model, and a runner that
never crashes on bad output."""

from __future__ import annotations

import json
import os
import shlex
import sys
import types
from pathlib import Path

import pytest

from smbr.decisions.provider import CompletionClient
from smbr.evals import BaselineReport, Task, TaskResult, load_suite, run_baseline, run_eval
from smbr.evals.runner import FILE_SCHEMA
from smbr.tools.checks import run_check

SUITE_DIR = Path(__file__).resolve().parents[1] / "evals" / "tasks"

PYTEST_RUN = "python -m pytest -q"

CLAMP_TEST = """\
from clamp import clamp


def test_clamp_bounds():
    assert clamp(5, 0, 3) == 3
    assert clamp(-5, 0, 3) == 0


def test_clamp_passes_through():
    assert clamp(2, 0, 3) == 2
"""

CLAMP_SOLUTION = "def clamp(value, lo, hi):\n    return max(lo, min(hi, value))\n"

# --------------------------------------------------------------------------- #
# stubs and helpers
# --------------------------------------------------------------------------- #


class StubClient:
    """A CompletionClient that answers once, with one scripted shape."""

    def __init__(self, answer: object = None, *, boom: bool = False) -> None:
        self.answer = answer
        self.boom = boom
        self.calls: list[tuple[str, dict]] = []

    def complete_json(self, prompt: str, schema: dict) -> dict:
        self.calls.append((prompt, schema))
        if self.boom:
            msg = "stub backend is down"
            raise RuntimeError(msg)
        return self.answer


class QueueClient:
    """A CompletionClient that answers from a scripted queue of shapes."""

    def __init__(self, answers: list[object]) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, dict]] = []

    def complete_json(self, prompt: str, schema: dict) -> dict:
        self.calls.append((prompt, schema))
        return self.answers.pop(0)


@pytest.fixture(autouse=True)
def _interpreter_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tasks run `python -m pytest`; make that the interpreter running these tests."""
    monkeypatch.setenv(
        "PATH", f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"
    )


def make_task(
    setup: dict[str, str],
    expect_files: list[str] | None = None,
    *,
    task_id: str = "inline",
    difficulty: int = 1,
    prompt: str = "Write the module the tests import.",
    run: str = PYTEST_RUN,
) -> Task:
    return Task.model_validate(
        {
            "id": task_id,
            "difficulty": difficulty,
            "prompt": prompt,
            "setup": setup,
            "run": run,
            "expect_files": expect_files or [],
        }
    )


def materialise(workdir: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        target = workdir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def write_json(directory: Path, name: str, payload: object) -> None:
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


# --------------------------------------------------------------------------- #
# the shipped suite
# --------------------------------------------------------------------------- #


def test_shipped_suite_loads_and_spans_the_difficulty_scale() -> None:
    tasks = load_suite(SUITE_DIR)
    assert len(tasks) >= 10
    assert [task.id for task in tasks] == sorted(task.id for task in tasks)
    assert len({task.id for task in tasks}) == len(tasks)
    assert {task.difficulty for task in tasks} == {1, 2, 3, 4, 5}
    for task in tasks:
        assert task.prompt.strip()
        assert task.setup, "a task with no fixture cannot fail before the model runs"
        assert task.run.strip()


def test_no_shipped_task_passes_without_the_model(tmp_path: Path) -> None:
    """A task that passes on its own fixture measures nothing."""
    for task in load_suite(SUITE_DIR):
        workdir = tmp_path / task.id
        materialise(workdir, task.setup)
        result = run_check(shlex.split(task.run), cwd=str(workdir))
        assert not result.passed, f"{task.id} already passes on the bare fixture"


# Reference solutions: the guard that a shipped task stays solvable. They also
# have to write exactly the paths the task expects.
SOLUTIONS: dict[str, dict[str, str]] = {
    "d1-clamp": {
        "clamp.py": "def clamp(value, lo, hi):\n    return max(lo, min(hi, value))\n",
    },
    "d1-slugify": {
        "slugify.py": (
            "import re\n\n\n"
            "def slugify(text):\n"
            '    return re.sub(r"[^a-z0-9_]+", "-", text.lower()).strip("-")\n'
        ),
    },
    "d2-flatten": {
        "flatten_lists.py": (
            "def flatten(items):\n"
            "    flat = []\n"
            "    for item in items:\n"
            "        if isinstance(item, list):\n"
            "            flat.extend(flatten(item))\n"
            "        else:\n"
            "            flat.append(item)\n"
            "    return flat\n"
        ),
    },
    "d2-parse-kv": {
        "kvparse.py": (
            "def parse_kv(text):\n"
            "    parsed = {}\n"
            '    for segment in text.split(";"):\n'
            "        segment = segment.strip()\n"
            "        if not segment:\n"
            "            continue\n"
            '        key, _, value = segment.partition("=")\n'
            "        parsed[key.strip()] = _coerce(value.strip())\n"
            "    return parsed\n"
            "\n\n"
            "def _coerce(raw):\n"
            "    lowered = raw.lower()\n"
            '    if lowered == "true":\n'
            "        return True\n"
            '    if lowered == "false":\n'
            "        return False\n"
            "    for cast in (int, float):\n"
            "        try:\n"
            "            return cast(raw)\n"
            "        except ValueError:\n"
            "            continue\n"
            "    return raw\n"
        ),
    },
    "d3-stack": {
        "stack.py": (
            "class Stack:\n"
            "    def __init__(self):\n"
            "        self._items = []\n"
            "\n"
            "    def push(self, item):\n"
            "        self._items.append(item)\n"
            "\n"
            "    def pop(self):\n"
            "        if not self._items:\n"
            '            raise IndexError("pop from an empty stack")\n'
            "        return self._items.pop()\n"
            "\n"
            "    def peek(self):\n"
            "        if not self._items:\n"
            '            raise IndexError("peek at an empty stack")\n'
            "        return self._items[-1]\n"
            "\n"
            "    def __len__(self):\n"
            "        return len(self._items)\n"
        ),
    },
    "d3-csvstats": {
        "csvstats.py": (
            "def parse_rows(text):\n"
            "    return [line.split(',') for line in text.strip().splitlines()[1:]]\n"
            "\n\n"
            "def column_means(text, columns):\n"
            "    lines = text.strip().splitlines()\n"
            "    if len(lines) < 2:\n"
            "        return {}\n"
            "    header = lines[0].split(',')\n"
            "    rows = parse_rows(text)\n"
            "    means = {}\n"
            "    for column in columns:\n"
            "        values = []\n"
            "        for row in rows:\n"
            "            try:\n"
            "                values.append(float(row[header.index(column)]))\n"
            "            except ValueError:\n"
            "                continue\n"
            "        if values:\n"
            "            means[column] = sum(values) / len(values)\n"
            "    return means\n"
        ),
    },
    "d4-merge-intervals": {
        "intervals.py": (
            "def merge(intervals):\n"
            "    if not intervals:\n"
            "        return []\n"
            "    ordered = sorted(intervals)\n"
            "    merged = [ordered[0]]\n"
            "    for start, end in ordered[1:]:\n"
            "        last_start, last_end = merged[-1]\n"
            "        if start <= last_end:\n"
            "            merged[-1] = (last_start, max(last_end, end))\n"
            "        else:\n"
            "            merged.append((start, end))\n"
            "    return merged\n"
        ),
    },
    "d4-lru": {
        "lru.py": (
            "from collections import OrderedDict\n"
            "\n\n"
            "class LRUCache:\n"
            "    def __init__(self, capacity):\n"
            "        if capacity <= 0:\n"
            '            raise ValueError("capacity must be positive")\n'
            "        self._capacity = capacity\n"
            "        self._items = OrderedDict()\n"
            "\n"
            "    def get(self, key):\n"
            "        if key not in self._items:\n"
            "            return None\n"
            "        self._items.move_to_end(key)\n"
            "        return self._items[key]\n"
            "\n"
            "    def put(self, key, value):\n"
            "        if key in self._items:\n"
            "            self._items.move_to_end(key)\n"
            "        self._items[key] = value\n"
            "        if len(self._items) > self._capacity:\n"
            "            self._items.popitem(last=False)\n"
        ),
    },
    "d5-tinycalc": {
        "tinycalc/__init__.py": (
            'from tinycalc.parser import evaluate\n\n__all__ = ["evaluate"]\n'
        ),
        "tinycalc/lexer.py": (
            "import re\n"
            "\n"
            'TOKEN = re.compile(r"\\d+(?:\\.\\d+)?|[+\\-*/()]")\n'
            "\n\n"
            "def tokenize(text):\n"
            "    tokens = []\n"
            "    index = 0\n"
            "    while index < len(text):\n"
            "        char = text[index]\n"
            "        if char.isspace():\n"
            "            index += 1\n"
            "            continue\n"
            "        match = TOKEN.match(text, index)\n"
            "        if match is None:\n"
            '            raise ValueError(f"unexpected character: {char}")\n'
            "        token = match.group()\n"
            "        tokens.append(float(token) if token not in '+-*/()' else token)\n"
            "        index = match.end()\n"
            "    return tokens\n"
        ),
        "tinycalc/parser.py": (
            "from tinycalc.lexer import tokenize\n"
            "\n\n"
            "def evaluate(expression):\n"
            "    tokens = tokenize(expression)\n"
            "    value, index = _expression(tokens, 0)\n"
            "    if index != len(tokens):\n"
            '        raise ValueError("trailing input")\n'
            "    return value\n"
            "\n\n"
            "def _expression(tokens, index):\n"
            "    value, index = _term(tokens, index)\n"
            "    while index < len(tokens) and tokens[index] in ('+', '-'):\n"
            "        operator = tokens[index]\n"
            "        right, index = _term(tokens, index + 1)\n"
            "        value = value + right if operator == '+' else value - right\n"
            "    return value, index\n"
            "\n\n"
            "def _term(tokens, index):\n"
            "    value, index = _atom(tokens, index)\n"
            "    while index < len(tokens) and tokens[index] in ('*', '/'):\n"
            "        operator = tokens[index]\n"
            "        right, index = _atom(tokens, index + 1)\n"
            "        if operator == '*':\n"
            "            value = value * right\n"
            "        else:\n"
            "            if right == 0:\n"
            '                raise ValueError("division by zero")\n'
            "            value = value / right\n"
            "    return value, index\n"
            "\n\n"
            "def _atom(tokens, index):\n"
            "    if index >= len(tokens):\n"
            '        raise ValueError("unexpected end of input")\n'
            "    token = tokens[index]\n"
            "    if token == '(':\n"
            "        value, index = _expression(tokens, index + 1)\n"
            '        if index >= len(tokens) or tokens[index] != ")":\n'
            '            raise ValueError("missing closing parenthesis")\n'
            "        return value, index + 1\n"
            "    if token in ('+', '-'):\n"
            "        value, index = _atom(tokens, index + 1)\n"
            "        return (value if token == '+' else -value), index\n"
            "    if isinstance(token, float):\n"
            "        return token, index + 1\n"
            '    raise ValueError(f"unexpected token: {token}")\n'
        ),
    },
    "d5-textstat": {
        "textstat/__init__.py": (
            "from textstat.words import reading_level, top_words\n"
            '\n__all__ = ["reading_level", "top_words"]\n'
        ),
        "textstat/stopwords.py": (
            "STOPWORDS = frozenset(\n"
            "    {'the', 'a', 'an', 'and', 'or', 'of', 'to', 'in', 'on', 'did', 'not'}\n"
            ")\n"
        ),
        "textstat/words.py": (
            "import re\n"
            "\n"
            "from textstat.stopwords import STOPWORDS\n"
            "\n\n"
            "def top_words(text, limit):\n"
            "    counts = {}\n"
            '    for word in re.findall(r"[a-z]+", text.lower()):\n'
            "        if word not in STOPWORDS:\n"
            "            counts[word] = counts.get(word, 0) + 1\n"
            "    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))\n"
            "    return ranked[:limit]\n"
            "\n\n"
            "def reading_level(text):\n"
            '    sentences = [part for part in re.split(r"[.!?]+", text) if part.strip()]\n'
            "    if not sentences:\n"
            '        return "simple"\n'
            "    mean = len(top_words_and_all(text)) / len(sentences)\n"
            "    if mean < 4:\n"
            '        return "simple"\n'
            "    if mean < 10:\n"
            '        return "medium"\n'
            '    return "complex"\n'
            "\n\n"
            "def top_words_and_all(text):\n"
            '    return re.findall(r"[a-z]+", text.lower())\n'
        ),
    },
}


def test_every_shipped_task_is_solvable(tmp_path: Path) -> None:
    for task in load_suite(SUITE_DIR):
        workdir = tmp_path / task.id
        materialise(workdir, task.setup)
        files = SOLUTIONS[task.id]
        assert sorted(files) == sorted(task.expect_files)
        materialise(workdir, files)
        result = run_check(shlex.split(task.run), cwd=str(workdir))
        assert result.passed, f"{task.id} is not solvable: {result.output}"


# --------------------------------------------------------------------------- #
# the runner
# --------------------------------------------------------------------------- #


def test_solved_task_scores_one_with_a_single_model_call(tmp_path: Path) -> None:
    task = make_task({"test_clamp.py": CLAMP_TEST}, ["clamp.py"])
    client = StubClient({"files": [{"path": "clamp.py", "content": CLAMP_SOLUTION}]})
    report = run_baseline([task], client, workdir_root=tmp_path / "work")

    (result,) = report.results
    assert result.score == 1.0
    assert result.error is None
    assert result.files_written == 1
    assert "passed" in result.check_output

    assert len(client.calls) == 1  # one shot, no repair loop
    prompt, schema = client.calls[0]
    assert schema == FILE_SCHEMA
    assert "Write the module the tests import." in prompt
    assert "test_clamp.py" in prompt


def test_garbage_answer_scores_zero_with_an_error_recorded(tmp_path: Path) -> None:
    task = make_task({"test_clamp.py": CLAMP_TEST}, ["clamp.py"])
    client = StubClient({"garbage": True})
    report = run_baseline([task], client, workdir_root=tmp_path / "work")

    (result,) = report.results
    assert result.score == 0.0
    assert result.files_written == 0
    assert result.error is not None
    assert "files" in result.error


@pytest.mark.parametrize(
    "answer",
    [
        {"files": "clamp.py"},
        {"files": [{"path": "clamp.py"}]},
        {"files": [{"path": 7, "content": "x"}]},
    ],
)
def test_malformed_file_entries_score_zero(tmp_path: Path, answer: object) -> None:
    task = make_task({"test_clamp.py": CLAMP_TEST}, ["clamp.py"])
    report = run_baseline([task], StubClient(answer), workdir_root=tmp_path / "work")

    (result,) = report.results
    assert result.score == 0.0
    assert result.error is not None
    assert result.files_written == 0


def test_non_object_answer_scores_zero(tmp_path: Path) -> None:
    task = make_task({"test_clamp.py": CLAMP_TEST}, ["clamp.py"])
    report = run_baseline(
        [task], StubClient(["not", "an", "object"]), workdir_root=tmp_path / "work"
    )

    (result,) = report.results
    assert result.score == 0.0
    assert "object" in (result.error or "")


def test_client_exception_scores_zero_without_crashing(tmp_path: Path) -> None:
    task = make_task({"test_clamp.py": CLAMP_TEST}, ["clamp.py"])
    report = run_baseline([task], StubClient(boom=True), workdir_root=tmp_path / "work")

    (result,) = report.results
    assert result.score == 0.0
    assert "stub backend is down" in (result.error or "")


def test_a_check_command_that_cannot_run_scores_zero(tmp_path: Path) -> None:
    task = make_task({"test_clamp.py": CLAMP_TEST}, ["clamp.py"], run="definitely-not-a-binary -q")
    report = run_baseline(
        [task],
        StubClient({"files": [{"path": "clamp.py", "content": CLAMP_SOLUTION}]}),
        workdir_root=tmp_path / "work",
    )

    (result,) = report.results
    assert result.score == 0.0
    assert "check could not run" in (result.error or "")


def test_missing_expected_file_scores_zero(tmp_path: Path) -> None:
    task = make_task({"test_clamp.py": CLAMP_TEST}, ["clamp.py", "extras.py"])
    report = run_baseline(
        [task],
        StubClient({"files": [{"path": "clamp.py", "content": CLAMP_SOLUTION}]}),
        workdir_root=tmp_path / "work",
    )

    (result,) = report.results
    assert result.score == 0.0
    assert "extras.py" in (result.error or "")


def test_path_escapes_are_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    task = make_task({"test_clamp.py": CLAMP_TEST}, ["../clamp.py"])
    client = StubClient(
        {
            "files": [
                {"path": "../clamp.py", "content": CLAMP_SOLUTION},
                {"path": str(outside), "content": CLAMP_SOLUTION},
            ]
        }
    )
    report = run_baseline([task], client, workdir_root=tmp_path / "work")

    (result,) = report.results
    assert result.score == 0.0
    assert result.files_written == 0
    assert not (tmp_path / "work" / "clamp.py").exists()
    assert not outside.exists()
    assert "refused" in (result.error or "")


def test_a_refused_file_does_not_sink_the_good_one(tmp_path: Path) -> None:
    task = make_task({"test_clamp.py": CLAMP_TEST}, ["clamp.py"])
    client = StubClient(
        {
            "files": [
                {"path": "../clamp.py", "content": "junk"},
                {"path": "clamp.py", "content": CLAMP_SOLUTION},
            ]
        }
    )
    report = run_baseline([task], client, workdir_root=tmp_path / "work")

    (result,) = report.results
    (workdir,) = (tmp_path / "work").iterdir()
    assert (workdir / "clamp.py").read_text(encoding="utf-8") == CLAMP_SOLUTION
    assert result.files_written == 1
    assert result.score == 1.0
    assert "refused" in (result.error or "")


def test_multiple_files_and_nested_paths(tmp_path: Path) -> None:
    test_file = "from pkg import thing\n\n\ndef test_thing():\n    assert thing() == 7\n"
    task = make_task({"test_pkg.py": test_file}, ["pkg/__init__.py", "pkg/core.py"])
    client = StubClient(
        {
            "files": [
                {"path": "pkg/__init__.py", "content": "from pkg.core import thing\n"},
                {"path": "pkg/core.py", "content": "def thing():\n    return 7\n"},
            ]
        }
    )
    report = run_baseline([task], client, workdir_root=tmp_path / "work")

    (result,) = report.results
    assert result.score == 1.0
    assert result.files_written == 2
    (workdir,) = (tmp_path / "work").iterdir()
    assert (workdir / "pkg" / "core.py").exists()


def test_keep_going_false_stops_at_the_first_failure(tmp_path: Path) -> None:
    tasks = [
        make_task({"test_clamp.py": CLAMP_TEST}, ["clamp.py"], task_id="first"),
        make_task({"test_clamp.py": CLAMP_TEST}, ["clamp.py"], task_id="second"),
    ]
    answers = [
        {"garbage": True},
        {"files": [{"path": "clamp.py", "content": CLAMP_SOLUTION}]},
    ]
    stopped = run_baseline(
        tasks, QueueClient(answers), keep_going=False, workdir_root=tmp_path / "stop"
    )
    assert [result.task_id for result in stopped.results] == ["first"]

    full = run_baseline(tasks, QueueClient(answers), workdir_root=tmp_path / "go")
    assert [result.task_id for result in full.results] == ["first", "second"]
    assert full.mean_score == 0.5


def test_setup_files_land_before_the_model_runs(tmp_path: Path) -> None:
    root = tmp_path / "work"
    seen: list[bool] = []

    class Watcher(StubClient):
        def complete_json(self, prompt: str, schema: dict) -> dict:
            seen.append(any((entry / "test_clamp.py").exists() for entry in root.iterdir()))
            return {"files": [{"path": "clamp.py", "content": CLAMP_SOLUTION}]}

    run_baseline(
        [make_task({"test_clamp.py": CLAMP_TEST}, ["clamp.py"])], Watcher(), workdir_root=root
    )
    assert seen == [True]  # the fixture is on disk before the one model call


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #


def test_report_aggregates_mean_and_per_difficulty() -> None:
    report = BaselineReport(
        [
            TaskResult("a", 1, 1.0, "", 1, None),
            TaskResult("b", 1, 0.0, "", 0, "boom"),
            TaskResult("c", 3, 1.0, "", 2, None),
        ]
    )
    assert report.mean_score == pytest.approx(2 / 3)
    assert report.by_difficulty() == {1: 0.5, 3: 1.0}


def test_empty_report_scores_zero() -> None:
    assert BaselineReport([]).mean_score == 0.0
    assert BaselineReport([]).by_difficulty() == {}


def test_report_to_json_writes_a_readable_report(tmp_path: Path) -> None:
    report = BaselineReport([TaskResult("a", 2, 1.0, "1 passed", 1, None)])
    written = report.to_json(tmp_path / "reports" / "baseline.json")

    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["mean_score"] == 1.0
    assert payload["by_difficulty"] == {"2": 1.0}
    assert payload["results"] == [
        {
            "task_id": "a",
            "difficulty": 2,
            "score": 1.0,
            "check_output": "1 passed",
            "files_written": 1,
            "error": None,
        }
    ]


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #


def test_load_suite_names_the_broken_file(tmp_path: Path) -> None:
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError, match=r"broken\.json"):
        load_suite(tmp_path)


def test_load_suite_rejects_schema_violations(tmp_path: Path) -> None:
    bad_difficulty = tmp_path / "bad-difficulty"
    bad_difficulty.mkdir()
    write_json(
        bad_difficulty,
        "cheat.json",
        {
            "id": "cheat",
            "difficulty": 9,
            "prompt": "be impossible",
            "setup": {},
            "run": "true",
        },
    )
    bad_field = tmp_path / "bad-field"
    bad_field.mkdir()
    write_json(
        bad_field,
        "typo.json",
        {
            "id": "typo",
            "difficulty": 1,
            "prompt": "wrong key name",
            "setup": {},
            "run": "true",
            "expects": [],
        },
    )
    with pytest.raises(ValueError, match=r"cheat\.json"):
        load_suite(bad_difficulty)
    with pytest.raises(ValueError, match=r"typo\.json"):
        load_suite(bad_field)


def test_load_suite_rejects_blank_commands(tmp_path: Path) -> None:
    write_json(
        tmp_path,
        "silent.json",
        {"id": "silent", "difficulty": 1, "prompt": "do nothing", "setup": {}, "run": "  "},
    )
    with pytest.raises(ValueError, match=r"silent\.json"):
        load_suite(tmp_path)


def test_load_suite_reports_a_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="nope"):
        load_suite(tmp_path / "nope")


# --------------------------------------------------------------------------- #
# the CLI entry point
# --------------------------------------------------------------------------- #


def install_fake_backend(monkeypatch: pytest.MonkeyPatch, client: CompletionClient) -> None:
    """Stand in for smbr.agent.client, which is still landing."""
    package = types.ModuleType("smbr.agent")
    package.__path__ = []  # marks the stub as a package
    module = types.ModuleType("smbr.agent.client")

    def build_completion_client(*, model: str = "") -> CompletionClient:
        return client

    module.build_completion_client = build_completion_client
    monkeypatch.setitem(sys.modules, "smbr.agent", package)
    monkeypatch.setitem(sys.modules, "smbr.agent.client", module)


def test_run_eval_scores_a_suite_and_writes_a_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "inline.json").write_text(
        json.dumps(make_task({"test_clamp.py": CLAMP_TEST}, ["clamp.py"]).model_dump()),
        encoding="utf-8",
    )
    install_fake_backend(
        monkeypatch, StubClient({"files": [{"path": "clamp.py", "content": CLAMP_SOLUTION}]})
    )
    report = tmp_path / "out" / "baseline.json"

    code = run_eval(["--suite", str(suite), "--out", str(report)])

    assert code == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["mean_score"] == 1.0
    assert payload["results"][0]["score"] == 1.0
    printed = capsys.readouterr().out
    assert "inline" in printed
    assert "mean score" in printed


def test_run_eval_stops_clearly_without_a_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    # both entries, because a sibling test module may already have imported it
    monkeypatch.setitem(sys.modules, "smbr.agent", None)
    monkeypatch.setitem(sys.modules, "smbr.agent.client", None)
    with pytest.raises(SystemExit, match="no model backend"):
        run_eval(["--suite", str(SUITE_DIR)])


def test_run_eval_returns_two_for_an_unusable_suite(tmp_path: Path) -> None:
    assert run_eval(["--suite", str(tmp_path / "missing")]) == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run_eval(["--suite", str(empty)]) == 2
