"""Regressions for review findings: scope, acceptance, concurrency, process lifetime."""

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from test_journal import edit_args, runner_for

import harness_workbench.service as service_module
import harness_workbench.tools as tools_module
from harness_workbench.faults import RecoveryConflict, UncertainExecution
from harness_workbench.fixtures import demo_files
from harness_workbench.tools import safe_path, workspace_digest


@pytest.mark.parametrize("relative", [".settings.py", ".custom/settings.py"])
def test_hidden_operable_file_changes_fingerprint(service, relative):
    task = service.create_demo()
    runner = runner_for(service, task)
    path = safe_path(runner.workspace, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("VALUE = 1\n", encoding="utf-8")
    first = workspace_digest(runner.workspace)
    read = runner.execute("hidden-read", "inspect_file", {"path": relative})
    runner.execute("hidden-edit", "replace_text", {
        "path": relative, "expected_sha256": read["sha256"],
        "old": "VALUE = 1", "new": "VALUE = 2",
    })
    assert workspace_digest(runner.workspace) != first
    assert relative in service.files(task["id"])


@pytest.mark.parametrize("relative", [
    "__pycache__/x.py", ".pytest_cache/x.py", ".ruff_cache/x.py", ".harness-write-abandoned"
])
def test_excluded_generated_files_cannot_be_tool_inputs(tmp_path, relative):
    with pytest.raises(ValueError):
        safe_path(tmp_path, relative)


def task_with_extra_tests(service, monkeypatch, extra):
    files = demo_files() | extra
    monkeypatch.setattr(service_module, "demo_files", lambda: files)
    return service.create_task(
        "Repair calculator and verify all original tests", files, mode="demo"
    )


@pytest.mark.parametrize("relative", ["test_other.py", ".checks/test_other.py"])
@pytest.mark.parametrize("passes", [True, False])
def test_final_acceptance_runs_all_original_files(service, monkeypatch, relative, passes):
    task = task_with_extra_tests(service, monkeypatch, {relative:
        "import unittest\nclass Other(unittest.TestCase):\n"
        f"    def test_other(self): self.assertTrue({passes})\n"
    })
    final = service.run_sync(task["id"])
    rows = service.store.tools(task["id"])
    partial = next(row for row in rows if row["name"] == "run_tests")
    acceptance = next(row for row in rows if row["name"] == "harness_acceptance")
    assert json.loads(partial["result"])["verified"]  # Agent's selected subset passed.
    evidence = json.loads(acceptance["result"])
    assert evidence["tests_run"] == 4
    assert evidence["targets"] == sorted(["test_calculator.py", relative])
    assert evidence["verified"] == passes
    assert final["status"] == ("succeeded" if passes else "failed")


def test_hidden_change_invalidates_cached_final_evidence(service):
    task = service.create_demo()
    runner = runner_for(service, task)
    runner.execute("edit", "replace_text", edit_args(runner))
    hidden = runner.workspace / ".settings.py"
    hidden.write_text("VALUE = 1\n", encoding="utf-8")
    evidence = runner.acceptance(service.store.source_files(task["id"]))
    assert evidence["verified"]
    hidden.write_text("VALUE = 2\n", encoding="utf-8")
    service._finalize(task["id"], runner.workspace, {
        "messages": [AIMessage(content="Done")]
    }, runner=runner)
    assert service.get(task["id"])["status"] == "failed"


@pytest.mark.parametrize("delete", [False, True])
def test_original_acceptance_tests_cannot_be_changed_or_removed(service, delete):
    task = service.create_demo()
    runner = runner_for(service, task)
    path = runner.workspace / "test_calculator.py"
    if delete:
        path.unlink()
    else:
        path.write_text("# replaced test\n", encoding="utf-8")
    with pytest.raises(RecoveryConflict):
        runner.acceptance(service.store.source_files(task["id"]))


def test_unconfirmed_supervisor_cleanup_blocks_even_authorized_retry(service):
    task = service.create_demo()
    runner = runner_for(service, task, retry_uncertain_tests=True)
    runner.test_lease.with_suffix(".uncertain").write_text("unconfirmed cleanup")
    with pytest.raises(UncertainExecution, match="cleanup was not confirmed"):
        runner.execute("read", "inspect_file", {"path": "calculator.py"})
    assert not service.store.tools(task["id"])


def test_acceptance_preserves_original_crlf_bytes(service, monkeypatch):
    task = task_with_extra_tests(service, monkeypatch, {
        "test_crlf.py": "import unittest\r\nclass CRLF(unittest.TestCase):\r\n"
        "    def test_ok(self): self.assertTrue(True)\r\n"
    })
    assert service.run_sync(task["id"])["status"] == "succeeded"


def test_change_during_temp_write_is_detected_before_replacement(service, monkeypatch):
    task = service.create_demo()
    runner = runner_for(service, task)
    args = edit_args(runner)
    path = runner.workspace / "calculator.py"
    real_fsync = tools_module.os.fsync

    def concurrent_edit(fd):
        real_fsync(fd)
        path.write_text("# external edit during temp write\n", encoding="utf-8")

    monkeypatch.setattr(tools_module.os, "fsync", concurrent_edit)
    with pytest.raises(RecoveryConflict):
        runner.execute("edit", "replace_text", args)
    assert path.read_text(encoding="utf-8").startswith("# external edit")


def test_uncoordinated_write_after_last_check_is_outside_contract(service, monkeypatch):
    """Explicitly demonstrate residual TOCTOU; atomic rename is not filesystem CAS."""
    task = service.create_demo()
    runner = runner_for(service, task)
    args = edit_args(runner)
    real_replace = tools_module.os.replace
    overwritten = []

    def concurrent_edit(source, destination):
        Path(destination).write_text("# unsupported external writer\n", encoding="utf-8")
        overwritten.append(True)
        real_replace(source, destination)

    monkeypatch.setattr(tools_module.os, "replace", concurrent_edit)
    runner.execute("edit", "replace_text", args)
    assert overwritten and "return a + b" in (runner.workspace / "calculator.py").read_text()
