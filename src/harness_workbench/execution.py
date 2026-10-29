"""Test supervision: owner pipe lifetime + cleanup lease, not a security sandbox."""

from __future__ import annotations

import ctypes
import json
import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from filelock import FileLock, Timeout

from .faults import UncertainExecution


def wait_for_test_cleanup(lease: Path):
    lease.parent.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(lease).acquire(timeout=10):
            if lease.with_suffix(".uncertain").exists():
                raise UncertainExecution(
                    "Test supervisor cleanup was not confirmed; inspect processes before recovery"
                )
    except Timeout as exc:
        raise UncertainExecution("Previous test supervisor still owns the workspace") from exc


def run_supervised(command, workspace, env, timeout, lease):
    """No test starts until supervisor owns the lease and receives owner authorization."""
    options = {
        "command": command, "workspace": str(workspace), "env": env,
        "timeout": timeout, "lease": str(lease),
    }
    child = subprocess.Popen(
        [sys.executable, "-m", "harness_workbench.execution", json.dumps(options)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
    )
    lines = queue.Queue()

    def read_protocol():
        for _ in range(2):
            lines.put(child.stdout.readline())

    threading.Thread(target=read_protocol, daemon=True).start()

    def receive(seconds):
        try:
            return lines.get(timeout=seconds)
        except queue.Empty:
            raise UncertainExecution("Test supervisor protocol timed out") from None

    try:
        if receive(15).strip() != "ready":
            raise UncertainExecution("Test supervisor did not acquire its cleanup lease")
        child.stdin.write("go\n")
        child.stdin.flush()
        # Keep stdin open: EOF tells supervisor that the owning worker has died.
        result = receive(timeout + 20)
        child.stdin.close()
        child.wait(timeout=15)
        if child.returncode or not result:
            raise UncertainExecution("Test supervisor exited without a durable result")
        return json.loads(result)
    except (BrokenPipeError, json.JSONDecodeError) as exc:
        raise UncertainExecution("Test supervisor result could not be confirmed") from exc
    finally:
        if not child.stdin.closed:
            child.stdin.close()
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            # Do not steal its lease or assume cleanup succeeded.
            raise UncertainExecution("Test supervisor cleanup did not finish") from None
        child.stdout.close()
        child.stderr.close()


def posix_group_running(group_id: int) -> bool:
    """Linux ignores dead zombies; other POSIX systems fail closed until group disappears."""
    if sys.platform.startswith("linux"):
        for directory in Path("/proc").iterdir():
            if not directory.name.isdigit():
                continue
            try:
                # comm may contain spaces/parentheses; split after its closing delimiter.
                fields = (directory / "stat").read_text().rsplit(") ", 1)[1].split()
                if int(fields[2]) == group_id and fields[0] not in {"Z", "X"}:
                    return True
            except (FileNotFoundError, ProcessLookupError):
                continue
        return False
    try:
        os.killpg(group_id, 0)
        return True
    except ProcessLookupError:
        return False


def stop_posix_group(child):
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait(timeout=10)
    deadline = time.monotonic() + 10
    while posix_group_running(child.pid):
        if time.monotonic() >= deadline:
            raise RuntimeError("POSIX test process group did not drain")
        time.sleep(0.01)


class ProcessTree:
    """Windows Job Object or POSIX process group; gate prevents pre-assignment effects."""

    def __init__(self):
        self.handle = None
        if os.name == "nt":
            from ctypes import wintypes

            class BasicLimits(ctypes.Structure):
                _fields_ = [
                    ("ProcessTime", ctypes.c_longlong), ("JobTime", ctypes.c_longlong),
                    ("Flags", wintypes.DWORD), ("MinWS", ctypes.c_size_t),
                    ("MaxWS", ctypes.c_size_t), ("Active", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("Priority", wintypes.DWORD),
                    ("Scheduling", wintypes.DWORD),
                ]

            class ExtendedLimits(ctypes.Structure):
                _fields_ = [
                    ("Basic", BasicLimits), ("IO", ctypes.c_ulonglong * 6),
                    ("ProcessMemory", ctypes.c_size_t), ("JobMemory", ctypes.c_size_t),
                    ("PeakProcess", ctypes.c_size_t), ("PeakJob", ctypes.c_size_t),
                ]

            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
            self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            self.kernel.SetInformationJobObject.argtypes = [
                wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
            ]
            self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            self.kernel.QueryInformationJobObject.argtypes = [
                wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p
            ]
            self.handle = self.kernel.CreateJobObjectW(None, None)
            limits = ExtendedLimits()
            limits.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.handle or not self.kernel.SetInformationJobObject(
                self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                self.close()
                raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, child):
        if self.handle and not self.kernel.AssignProcessToJobObject(
            self.handle, int(child._handle)
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def stop(self, child):
        if os.name == "nt":
            # Keep the lease until the Job Object reports zero active processes.
            if not self.kernel.TerminateJobObject(self.handle, 1):
                raise ctypes.WinError(ctypes.get_last_error())
            deadline = time.monotonic() + 10
            while True:
                accounting = (ctypes.c_ulonglong * 4)()
                counts = (ctypes.c_ulong * 4)()
                buffer = ctypes.create_string_buffer(
                    ctypes.sizeof(accounting) + ctypes.sizeof(counts)
                )
                if not self.kernel.QueryInformationJobObject(
                    self.handle, 1, buffer, ctypes.sizeof(buffer), None
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
                # JOBOBJECT_BASIC_ACCOUNTING_INFORMATION: four times, pagefaults,
                # total processes, active processes, total terminated processes.
                active = ctypes.c_ulong.from_buffer(buffer, 40).value
                if active == 0:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Windows test Job Object did not drain")
                time.sleep(0.01)
            self.close()
        else:
            stop_posix_group(child)
        child.wait(timeout=10)


def supervise(options):
    lease = Path(options["lease"])
    with FileLock(lease).acquire(timeout=10):
        if lease.with_suffix(".uncertain").exists():
            raise RuntimeError("Previous process-tree cleanup is unconfirmed")
        print("ready", flush=True)
        if sys.stdin.readline().strip() != "go":
            return  # Owner died before authorization: never start tests.
        owner_gone = threading.Event()

        def watch_owner():
            sys.stdin.read()
            owner_gone.set()

        threading.Thread(target=watch_owner, daemon=True).start()
        marker = lease.with_suffix(".uncertain")
        marker.write_text("Process tree cleanup pending", encoding="utf-8")
        tree = ProcessTree()
        with tempfile.TemporaryFile() as output:
            child = None
            try:
                if owner_gone.is_set():
                    marker.unlink()
                    return
                child = subprocess.Popen(
                    [sys.executable, "-m", "harness_workbench.test_process"],
                    stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT,
                    start_new_session=os.name != "nt",
                )
                tree.assign(child)
                # Gate child runs no workspace code before it belongs to the process tree.
                child.stdin.write((json.dumps(options) + "\n").encode())
                child.stdin.close()
                deadline = time.monotonic() + options["timeout"]
                while child.poll() is None and not owner_gone.is_set():
                    if time.monotonic() >= deadline:
                        break
                    owner_gone.wait(0.02)
                timed_out = child.poll() is None and not owner_gone.is_set()
            finally:
                if child is not None:
                    if os.name == "nt" and tree.handle and child.poll() is None:
                        # If assignment failed, the gate is still inert; kill it directly too.
                        child.kill()
                    tree.stop(child)
                tree.close()
            marker.unlink()  # Only after process-tree cleanup has completed.
            if owner_gone.is_set():
                return  # Cleanup completes before the lease is released.
            output.seek(0, os.SEEK_END)
            size = output.tell()
            output.seek(max(0, size - 8000))
            print(json.dumps({
                "returncode": child.returncode, "timed_out": timed_out,
                "output_bytes": size,
                "output": output.read().decode("utf-8", errors="replace"),
            }), flush=True)


if __name__ == "__main__":
    supervise(json.loads(sys.argv[1]))
