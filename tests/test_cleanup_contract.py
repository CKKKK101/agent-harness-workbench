"""Review regressions: cleanup must confirm all members, failures remain blocked."""

import io
import signal
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import harness_workbench.execution as execution
from harness_workbench.faults import UncertainExecution


def test_posix_cleanup_waits_for_remaining_group_members(monkeypatch):
    monkeypatch.setattr(execution.signal, "SIGKILL", 9, raising=False)
    kill = Mock()
    monkeypatch.setattr(execution.os, "killpg", kill, raising=False)
    remaining = iter([True, True, False])
    monkeypatch.setattr(execution, "posix_group_running", lambda pid: next(remaining))
    pause = Mock()
    monkeypatch.setattr(execution.time, "sleep", pause)
    child = SimpleNamespace(pid=12345, wait=Mock())
    execution.stop_posix_group(child)
    kill.assert_called_once_with(12345, signal.SIGKILL if hasattr(signal, "SIGKILL") else 9)
    assert pause.call_count == 2


def test_posix_cleanup_failure_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(execution.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(execution.os, "killpg", Mock(), raising=False)
    monkeypatch.setattr(execution, "posix_group_running", lambda pid: True)
    times = iter([0, 11])
    monkeypatch.setattr(execution.time, "monotonic", lambda: next(times))
    with pytest.raises(RuntimeError, match="did not drain"):
        execution.stop_posix_group(SimpleNamespace(pid=12345, wait=Mock()))


@pytest.mark.parametrize("protocol", ["", "ready\n", "ready\nnot-json\n"])
def test_supervisor_failure_blocks_instead_of_marking_task_failed(monkeypatch, tmp_path, protocol):
    child = SimpleNamespace(
        stdin=io.StringIO(), stdout=io.StringIO(protocol), stderr=io.StringIO(),
        returncode=0, wait=Mock(),
    )
    monkeypatch.setattr(execution.subprocess, "Popen", lambda *a, **kw: child)
    with pytest.raises(UncertainExecution):
        execution.run_supervised([], tmp_path, {}, 1, tmp_path / "test.lock")


def test_cleanup_failure_leaves_marker_and_blocks_service_resume(service, monkeypatch):
    """Execute real tests, then inject cleanup-confirmation failure in a real supervisor."""
    real_popen = execution.subprocess.Popen
    script = (
        "import json, sys\n"
        "from harness_workbench.execution import ProcessTree, supervise\n"
        "original = ProcessTree.stop\n"
        "def fail_after_stop(self, child):\n"
        "    original(self, child)\n"
        "    raise RuntimeError('injected cleanup confirmation failure')\n"
        "ProcessTree.stop = fail_after_stop\n"
        "supervise(json.loads(sys.argv[1]))\n"
    )

    def inject(command, **kwargs):
        if command[1:3] == ["-m", "harness_workbench.execution"]:
            command = [sys.executable, "-c", script, command[3]]
        return real_popen(command, **kwargs)

    monkeypatch.setattr(execution.subprocess, "Popen", inject)
    task = service.create_demo()
    assert service.run_sync(task["id"])["status"] == "blocked"
    marker = service.settings.data_dir / "locks" / f"{task['id']}.tests.uncertain"
    assert marker.exists()
    assert service.run_sync(task["id"], retry_uncertain_tests=True)["status"] == "blocked"
