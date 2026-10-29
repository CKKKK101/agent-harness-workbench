"""Narrow coding tools with durable intents and hash-reconciled file recovery.

Workspace path checks are directory isolation, NOT an OS sandbox for Python tests.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from .execution import run_supervised, wait_for_test_cleanup
from .faults import FaultInjector, RecoveryConflict, UncertainExecution
from .store import Store, encode

TOOL_NAMES = {"inspect_file", "replace_text", "run_tests"}
MAX_FILE_BYTES = 256_000
WORKSPACE_EXCLUSIONS = {"__pycache__", ".pytest_cache", ".ruff_cache"}
INTERNAL_PATHS = {".git", ".env", ".workbench"}


def excluded_path(relative: Path) -> bool:
    return any(part in WORKSPACE_EXCLUSIONS for part in relative.parts) or any(
        part.startswith(".harness-write-") for part in relative.parts
    )


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute() or "\\" in relative or ":" in relative:
        raise ValueError("Use a relative POSIX path inside the task workspace")
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()) or candidate == root.resolve():
        raise ValueError("Path escapes the task workspace")
    if any(p in INTERNAL_PATHS for p in Path(relative).parts) or excluded_path(Path(relative)):
        raise ValueError("Access to internal/credential paths is disabled")
    return candidate


def read_bytes(path: Path) -> bytes:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"File exceeds {MAX_FILE_BYTES} bytes")
    return path.read_bytes()


def workspace_digest(root: Path) -> str:
    """Fingerprint source inputs, excluding generated caches. Used for result verification."""
    entries = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if excluded_path(rel):
            continue
        if p.is_symlink():
            raise ValueError("Symbolic links are not supported in task workspaces")
        if p.is_file():
            entries.append((rel.as_posix(), digest(read_bytes(p))))
    return digest(encode(entries).encode())


def atomic_write(path: Path, data: bytes, *, expected_sha256: str | None = None):
    """Same-directory replacement prevents partial file contents after process death."""
    fd, name = tempfile.mkstemp(prefix=".harness-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Best-effort final check, NOT an atomic compare-and-swap with os.replace.
        # All cooperating writers must hold the task lock; external writes are unsupported.
        if expected_sha256 is not None and digest(read_bytes(path)) != expected_sha256:
            raise RecoveryConflict("File changed while preparing replacement; write blocked")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class ToolRunner:
    def __init__(
        self,
        store: Store,
        task_id: str,
        workspace: Path,
        faults: FaultInjector,
        *,
        timeout: int = 20,
        retry_uncertain_tests: bool = False,
    ):
        self.store, self.task_id, self.workspace, self.faults = store, task_id, workspace, faults
        self.timeout = timeout
        self.retry_uncertain_tests = retry_uncertain_tests

    @property
    def test_lease(self) -> Path:
        return self.store.path.parent / "locks" / f"{self.task_id}.tests.lock"

    def execute(self, call_id: str, name: str, args: dict) -> dict:
        wait_for_test_cleanup(self.test_lease)
        if name not in TOOL_NAMES:
            raise ValueError(f"Tool not enabled for this workbench: {name}")
        row = self.store.tool(self.task_id, call_id)
        if row:
            if row["name"] != name or row["arguments"] != encode(args):
                raise RecoveryConflict("Tool-call ID was reused with different arguments")
            if row["state"] == "succeeded":
                self.store.tool_reused(self.task_id, call_id, "durable_result")
                return json.loads(row["result"])
            prepared = json.loads(row["prepared"])
            if name == "run_tests" and row["state"] == "started":
                if not self.retry_uncertain_tests:
                    raise UncertainExecution(
                        "Previous test execution has no durable result. Inspect its effects, "
                        "then resume with retry_uncertain_tests=true if safe."
                    )
                prepared["fingerprint"] = workspace_digest(self.workspace)
                self.store.event(self.task_id, "tool.retry_authorized", {"call_id": call_id})
        else:
            prepared = self._prepare(name, args)
            self.store.prepare(self.task_id, call_id, name, args, prepared)

        if name == "replace_text":
            self.faults.hit("after_prepare")
            path = safe_path(self.workspace, args["path"])
            current_hash = digest(read_bytes(path))
            if current_hash == prepared["after_hash"]:
                result = prepared["result"] | {"reconciled": True}
                self.store.tool_reused(self.task_id, call_id, "file_already_matches_intent")
            elif current_hash == prepared["before_hash"]:
                self.store.tool_started(self.task_id, call_id)
                atomic_write(
                    path, prepared["content"].encode("utf-8"),
                    expected_sha256=prepared["before_hash"],
                )
                self.faults.hit("after_effect")
                result = prepared["result"]
            else:
                raise RecoveryConflict(
                    f"{args['path']} matches neither the saved before nor after hash; "
                    "manual changes were preserved. Create a new task after inspection."
                )
        elif name == "inspect_file":
            self.store.tool_started(self.task_id, call_id)
            data = read_bytes(safe_path(self.workspace, args["path"]))
            result = {"path": args["path"], "sha256": digest(data), "content": data.decode("utf-8")}
        else:
            self.store.tool_started(self.task_id, call_id)
            self.faults.hit("after_test_started")
            result = self._run_tests(args["target"], prepared["fingerprint"])

        self.store.tool_done(self.task_id, call_id, result)
        if name == "replace_text":
            self.faults.hit("after_journal")
        return result

    def _prepare(self, name: str, args: dict) -> dict:
        if name == "run_tests":
            target = args["target"]
            if not re.fullmatch(r"test_[A-Za-z0-9_]+\.py", target):
                raise ValueError("target must be one test_*.py filename (no shell syntax)")
            safe_path(self.workspace, target).stat()
            return {"fingerprint": workspace_digest(self.workspace)}
        path = safe_path(self.workspace, args["path"])
        before = read_bytes(path)
        if name == "inspect_file":
            return {}
        if path.name.startswith("test_") or path.name in {"conftest.py", "pytest.ini"}:
            raise ValueError("Test fixtures are read-only; fix application code instead")
        if digest(before) != args["expected_sha256"]:
            raise ValueError("File changed since inspection; inspect it again before editing")
        text = before.decode("utf-8")
        if not args["old"] or text.count(args["old"]) != 1:
            raise ValueError("old text must occur exactly once; inspect the file again")
        after = text.replace(args["old"], args["new"], 1).encode("utf-8")
        if len(after) > MAX_FILE_BYTES:
            raise ValueError("Replacement would exceed the file size limit")
        return {
            "before_hash": digest(before),
            "after_hash": digest(after),
            "content": after.decode("utf-8"),
            "result": {"path": args["path"], "sha256": digest(after), "changed": before != after},
        }

    def acceptance(self, original: dict[str, str]) -> dict:
        """Harness-owned suite; the agent cannot choose its scope or cached call ID."""
        wait_for_test_cleanup(self.test_lease)
        targets = sorted(
            name for name in original
            if Path(name).name.startswith("test_") and name.endswith(".py")
        )
        if not targets:
            raise RecoveryConflict("No original test manifest; create a new task")
        for target in targets:
            path = safe_path(self.workspace, target)
            if not path.is_file() or read_bytes(path).decode("utf-8") != original[target]:
                raise RecoveryConflict("Original acceptance tests changed; verification blocked")
        call_id = "harness:acceptance:v1"
        row = self.store.tool(self.task_id, call_id)
        args = {"targets": targets, "scope": "original_test_manifest_v1"}
        if row:
            if row["name"] != "harness_acceptance" or row["arguments"] != encode(args):
                raise RecoveryConflict("Acceptance manifest or reserved call ID changed")
            if row["state"] == "succeeded":
                return json.loads(row["result"])
            if row["state"] == "started" and not self.retry_uncertain_tests:
                raise UncertainExecution(
                    "Previous test execution (Harness acceptance) has no durable result; "
                    "explicit retry required"
                )
        else:
            self.store.prepare(
                self.task_id, call_id, "harness_acceptance", args,
                {"fingerprint": workspace_digest(self.workspace)},
            )
        fingerprint = workspace_digest(self.workspace)
        self.store.tool_started(self.task_id, call_id)
        command = [sys.executable, "-m", "harness_workbench.test_suite", *targets]
        result = self._run_tests(None, fingerprint, command=command) | {"targets": targets}
        self.store.tool_done(self.task_id, call_id, result)
        return result

    def _run_tests(self, target: str | None, fingerprint: str, *, command=None) -> dict:
        command = command or [
            sys.executable, "-I", "-m", "unittest", "discover", "-s", ".", "-p", target
        ]
        env = {
            k: v
            for k, v in os.environ.items()
            if k.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LANG"}
        }
        env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        execution = run_supervised(command, self.workspace, env, self.timeout, self.test_lease)
        tail, size = execution["output"], execution["output_bytes"]
        after = workspace_digest(self.workspace)
        # Older unittest versions can exit 0 without tests: require a non-zero count.
        matched = re.search(r"Ran (\d+) tests?", tail)
        count = int(matched.group(1)) if matched else 0
        return {
            "returncode": execution["returncode"],
            "timed_out": execution["timed_out"],
            "output": tail,
            "output_bytes": size,
            "tests_run": count,
            "fingerprint": after,
            "inputs_unchanged": after == fingerprint,
            "verified": execution["returncode"] == 0 and count > 0 and after == fingerprint,
        }
