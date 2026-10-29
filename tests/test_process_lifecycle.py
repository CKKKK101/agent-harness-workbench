"""Actual worker death while tests and a grandchild are running; no mock cleanup."""

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from filelock import FileLock
from test_reliability import task_with_extra_tests

from harness_workbench.fixtures import demo_files


def alive(pid):
    if os.name == "nt":
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = wintypes.DWORD()
        try:
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        stat = Path(f"/proc/{pid}/stat")
        if stat.exists() and stat.read_text().split(") ", 1)[1].startswith("Z"):
            return False
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


@pytest.mark.parametrize("phase", ["agent", "acceptance"])
def test_worker_death_cleans_live_test_tree_before_safe_resume(
    service, monkeypatch, tmp_path, phase, record_property
):
    ready, allow = tmp_path / "ready.json", tmp_path / "allow-retry"
    heartbeat, descendant_heartbeat = tmp_path / "heartbeat", tmp_path / "descendant-heartbeat"
    descendant = (
        "from pathlib import Path; import time\n"
        f"p=Path({str(descendant_heartbeat)!r})\n"
        "while True:\n p.write_text(str(time.time_ns()))\n time.sleep(0.02)\n"
    )
    slow = (
        "\nimport json, os, subprocess, sys, time\nfrom pathlib import Path\nimport unittest\n"
        "class Lifecycle(unittest.TestCase):\n"
        "    def test_live_child(self):\n"
        f"        if Path({str(allow)!r}).exists(): return\n"
        f"        child = subprocess.Popen([sys.executable, '-c', {descendant!r}])\n"
        f"        Path({str(ready)!r}).write_text(json.dumps([os.getpid(), child.pid]))\n"
        "        while True:\n"
        f"            Path({str(heartbeat)!r}).write_text(str(time.time_ns()))\n"
        "            time.sleep(0.02)\n"
    )
    extra = {"test_lifecycle.py": slow}
    if phase == "agent":
        extra = {"test_calculator.py": demo_files()["test_calculator.py"] + slow}
    task = task_with_extra_tests(service, monkeypatch, extra)
    script = (
        "import os, threading, time\nfrom pathlib import Path\n"
        "from harness_workbench.config import Settings\n"
        "from harness_workbench.service import TaskService\n"
        "def crash_when_test_is_live():\n"
        f"    while not Path({str(ready)!r}).exists(): time.sleep(0.01)\n"
        "    time.sleep(0.15)\n    os._exit(86)\n"
        "threading.Thread(target=crash_when_test_is_live, daemon=True).start()\n"
        f"s=TaskService(Settings(data_dir=Path({str(service.settings.data_dir)!r}), "
        "test_timeout=30))\n"
        f"s.run_sync({task['id']!r})\n"
    )
    worker = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    pids = []
    try:
        assert worker.wait(timeout=20) == 86
        pids = json.loads(ready.read_text())
        assert heartbeat.exists() and descendant_heartbeat.exists()
        # Resume immediately, without first waiting for cleanup in this test.
        blocked = service.run_sync(task["id"])
        assert blocked["status"] == "blocked"
        assert all(not alive(pid) for pid in pids)
        with FileLock(service.settings.data_dir / "locks" / f"{task['id']}.tests.lock").acquire(
            timeout=0
        ):
            pass
        saved = [path.read_text() for path in (heartbeat, descendant_heartbeat)]
        time.sleep(0.15)
        assert saved == [path.read_text() for path in (heartbeat, descendant_heartbeat)]
        rows = service.store.tools(task["id"])
        unknown = "run_tests" if phase == "agent" else "harness_acceptance"
        assert any(row["name"] == unknown and row["state"] == "started" for row in rows)
        allow.touch()
        final = service.run_sync(task["id"], retry_uncertain_tests=True)
        assert final["status"] == "succeeded"
        assert final["metrics"]["file_write_attempts"] == 1
        record_property("phase", phase)
        record_property("worker_exit", 86)
        record_property("live_test_and_descendant_stopped", True)
        record_property("unknown_result_blocked", True)
        record_property("authorized_resume_status", final["status"])
        record_property("file_write_attempts", final["metrics"]["file_write_attempts"])
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=10)
        if not pids and ready.exists():
            pids = json.loads(ready.read_text())
        for pid in pids:
            if alive(pid):
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
                else:
                    os.kill(pid, 9)


def test_owner_dies_before_authorization_never_starts_tests(tmp_path):
    marker = tmp_path / "must-not-exist"
    options = {
        "command": [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"],
        "workspace": str(tmp_path), "env": {}, "timeout": 5,
        "lease": str(tmp_path / "test.lock"),
    }
    child = subprocess.Popen(
        [sys.executable, "-m", "harness_workbench.execution", json.dumps(options)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
    )
    try:
        assert child.stdout.readline().strip() == "ready"
        child.stdin.close()  # EOF, no go authorization.
        assert child.wait(timeout=10) == 0
        assert not marker.exists()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        child.stdout.close()
        child.stderr.close()
