import json
from pathlib import Path

import pytest

from harness_workbench.faults import (
    FaultInjector,
    InjectedCrash,
    RecoveryConflict,
    UncertainExecution,
)
from harness_workbench.tools import ToolRunner, safe_path


def runner_for(service, task, **kwargs):
    raw = service.store.task(task["id"])
    return ToolRunner(
        service.store,
        task["id"],
        Path(raw["workspace"]),
        FaultInjector(service.store, task["id"]),
        **kwargs,
    )


def edit_args(runner):
    read = runner.execute("read", "inspect_file", {"path": "calculator.py"})
    return {
        "path": "calculator.py",
        "expected_sha256": read["sha256"],
        "old": "return a - b",
        "new": "return a + b",
    }


@pytest.mark.parametrize("fault", ["after_prepare", "after_effect", "after_journal"])
def test_recovery_writes_once_at_each_boundary(service, fault):
    task = service.create_demo(fault=fault)
    runner = runner_for(service, task)
    args = edit_args(runner)
    with pytest.raises(InjectedCrash):
        runner.execute("edit", "replace_text", args)
    # A new runner has no in-memory knowledge from the interrupted execution.
    result = runner_for(service, task).execute("edit", "replace_text", args)
    assert result["changed"]
    assert "return a + b" in service.files(task["id"])["calculator.py"]
    assert service.store.tool(task["id"], "edit")["executions"] == 1


def test_recovery_preserves_external_edits(service):
    task = service.create_demo(fault="after_effect")
    runner = runner_for(service, task)
    args = edit_args(runner)
    with pytest.raises(InjectedCrash):
        runner.execute("edit", "replace_text", args)
    path = Path(service.store.task(task["id"])["workspace"]) / "calculator.py"
    path.write_text("# manually changed\ndef add(a, b):\n    return 100\n", encoding="utf-8")
    with pytest.raises(RecoveryConflict):
        runner_for(service, task).execute("edit", "replace_text", args)
    assert "return 100" in path.read_text(encoding="utf-8")


def test_reused_call_id_cannot_execute_different_arguments(service):
    task = service.create_demo()
    runner = runner_for(service, task)
    runner.execute("same", "inspect_file", {"path": "calculator.py"})
    with pytest.raises(RecoveryConflict):
        runner.execute("same", "inspect_file", {"path": "test_calculator.py"})


@pytest.mark.parametrize("path", ["../secret", "C:/secret", "a\\b", ".env", ".git/config"])
def test_tool_paths_cannot_escape_or_read_credentials(tmp_path, path):
    with pytest.raises(ValueError):
        safe_path(tmp_path, path)


def test_model_cannot_rewrite_tests(service):
    task = service.create_demo()
    runner = runner_for(service, task)
    read = runner.execute("read_test", "inspect_file", {"path": "test_calculator.py"})
    with pytest.raises(ValueError, match="read-only"):
        runner.execute(
            "edit_test",
            "replace_text",
            {
                "path": "test_calculator.py",
                "expected_sha256": read["sha256"],
                "old": "add(2, 3), 5",
                "new": "add(2, 3), -1",
            },
        )


def test_unknown_test_execution_requires_explicit_retry(service):
    task = service.create_demo(fault="after_test_started")
    runner = runner_for(service, task)
    runner.execute("edit", "replace_text", edit_args(runner))
    with pytest.raises(InjectedCrash):
        runner.execute("test", "run_tests", {"target": "test_calculator.py"})
    with pytest.raises(UncertainExecution):
        runner_for(service, task).execute("test", "run_tests", {"target": "test_calculator.py"})
    result = runner_for(service, task, retry_uncertain_tests=True).execute(
        "test", "run_tests", {"target": "test_calculator.py"}
    )
    assert result["verified"] and result["tests_run"] == 3


def test_zero_discovered_tests_do_not_count_as_verification(service):
    task = service.create_demo()
    root = Path(service.store.task(task["id"])["workspace"])
    (root / "test_empty.py").write_text("# intentionally no tests\n", encoding="utf-8")
    result = runner_for(service, task).execute("empty", "run_tests", {"target": "test_empty.py"})
    # Python 3.14 returns 5 for no tests; older versions may return 0.
    assert result["tests_run"] == 0
    assert not result["verified"]


def test_test_timeout_is_reported_and_process_stops(service):
    task = service.create_demo()
    root = Path(service.store.task(task["id"])["workspace"])
    (root / "test_slow.py").write_text(
        "import unittest, time\nclass Slow(unittest.TestCase):\n"
        "    def test_wait(self):\n        time.sleep(30)\n",
        encoding="utf-8",
    )
    result = runner_for(service, task, timeout=1).execute(
        "slow", "run_tests", {"target": "test_slow.py"}
    )
    assert result["timed_out"] and not result["verified"]


def test_cached_result_is_durable(service):
    task = service.create_demo()
    first = runner_for(service, task).execute("read", "inspect_file", {"path": "calculator.py"})
    second = runner_for(service, task).execute("read", "inspect_file", {"path": "calculator.py"})
    assert first == second
    row = service.store.tool(task["id"], "read")
    assert row["executions"] == 1 and row["reuses"] == 1
    assert json.loads(row["result"])["sha256"] == first["sha256"]
