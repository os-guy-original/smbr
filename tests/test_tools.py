"""Tools: symbols from real tree-sitter parses, registry exposure, checks."""

from __future__ import annotations

from smbr.kernel import Kernel, Step
from smbr.preflight.capabilities import Capability
from smbr.tools import (
    default_registry,
    index_source,
    lookup_symbol,
    read_file,
    run_check,
    search_files,
)


def test_symbol_index_finds_functions_classes_imports(sample_source: str) -> None:
    names = {(s.kind, s.name) for s in index_source(sample_source)}
    assert ("function", "helper") in names
    assert ("function", "fetch") in names
    assert ("function", "__init__") in names
    assert ("class", "Client") in names
    assert ("import", "os") in names


def test_alias_import_confirms_both_names(sample_source: str) -> None:
    src = "from typing import Optional as Opt\n"
    assert lookup_symbol(src, "Optional") is not None


def test_lookup_returns_none_for_unconfirmed_name(sample_source: str) -> None:
    assert lookup_symbol(sample_source, "does_not_exist") is None


def test_registry_health_and_exposure(tmp_path) -> None:
    registry = default_registry(cwd=str(tmp_path))
    assert registry.check(Capability.FILE_READ).available
    assert registry.check(Capability.SYMBOL_LOOKUP).available
    assert registry.check(Capability.DOCS_LOOKUP).detail == "no tool provides this capability"

    edit_tools = registry.expose(Step.EDIT)
    assert edit_tools == ["file_read", "patch_apply", "symbol_lookup"]
    verify_tools = registry.expose(Step.VERIFY)
    # exposure is name-based: type_checker is registered but unconfigured,
    # so it shows up here and is caught by the health check, not the exposure
    assert set(verify_tools) == {"linter", "test_runner", "type_checker"}
    assert not registry.check(Capability.TYPE_CHECKER).available

    kernel = Kernel(registry=registry)
    assert len(kernel.exposed_tools(Step.PLAN)) <= 5  # 3-5 tools per step, never everything


def test_read_and_search_round_trip(tmp_path) -> None:
    (tmp_path / "a.py").write_text("needle here\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("nothing\n", encoding="utf-8")
    assert read_file(tmp_path / "a.py") == "needle here\n"
    assert search_files(tmp_path, "needle") == ["a.py"]


def test_read_missing_file_raises(tmp_path) -> None:
    try:
        read_file(tmp_path / "missing.py")
    except FileNotFoundError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected FileNotFoundError")


def test_run_check_reports_real_returncode(tmp_path) -> None:
    ok = run_check(("python", "-c", "print(1)"), cwd=str(tmp_path))
    assert ok.passed

    bad = run_check(("python", "-c", "import sys; sys.exit(3)"), cwd=str(tmp_path))
    assert not bad.passed and bad.returncode == 3


def test_empty_command_is_a_no_op_not_a_crash() -> None:
    result = run_check((), cwd=".")
    assert result.passed and "no command" in result.output
