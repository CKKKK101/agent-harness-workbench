from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from filelock import FileLock, Timeout
from langgraph.checkpoint.sqlite import SqliteSaver

from .agent import build_agent
from .config import Settings
from .faults import FaultInjector, InjectedCrash, RecoveryConflict, UncertainExecution
from .fixtures import DEMO_PROMPT, demo_files
from .models import create_model
from .store import Store
from .tools import MAX_FILE_BYTES, ToolRunner, safe_path, workspace_digest

TERMINAL = {"succeeded", "failed", "blocked", "interrupted"}


class TaskBusy(Exception):
    pass


class TaskService:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(settings.data_dir / "application.sqlite")
        self.pool = ThreadPoolExecutor(
            max_workers=settings.max_workers, thread_name_prefix="harness"
        )
        self._guard = threading.Lock()
        (settings.data_dir / "locks").mkdir(exist_ok=True)
        (settings.data_dir / "checkpoints").mkdir(exist_ok=True)
        self.recover_abandoned()

    def _lock(self, task_id: str) -> FileLock:
        return FileLock(self.settings.data_dir / "locks" / f"{task_id}.lock", thread_local=False)

    def recover_abandoned(self):
        for task in self.store.tasks():
            if task["status"] != "running":
                continue
            try:
                with self._lock(task["id"]).acquire(timeout=0):
                    if self.store.task(task["id"])["status"] == "running":
                        self.store.set_status(
                            task["id"],
                            "interrupted",
                            error="Previous worker exited; resume is available",
                        )
            except Timeout:
                pass  # A live process still owns this task; never steal its workspace.

    def create_task(
        self,
        prompt: str,
        files: dict[str, str],
        *,
        mode: str | None = None,
        fault: str | None = None,
    ) -> dict:
        mode = mode or self.settings.model_mode
        if not 1 <= len(files) <= 30:
            raise ValueError("Provide between 1 and 30 UTF-8 source/test files")
        if sum(len(s.encode("utf-8")) for s in files.values()) > 512_000:
            raise ValueError("Workspace upload exceeds 512 KB")
        if not any(Path(name).name.startswith("test_") for name in files):
            raise ValueError("Provide at least one test_*.py unittest fixture")
        # Validate paths before creating anything. API clients cannot select host directories.
        root = self.settings.data_dir / "workspaces" / uuid.uuid4().hex
        for name, content in files.items():
            safe_path(root, name)
            if len(content.encode("utf-8")) > MAX_FILE_BYTES:
                raise ValueError(f"File too large: {name}")
        if mode == "demo" and files != demo_files():
            raise ValueError(
                "Demo mode supports only the bundled fixture; use openai mode for your code"
            )
        # Fail early on missing configuration without exposing secrets.
        create_model(mode)
        for name, content in files.items():
            path = safe_path(root, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="")
        task_id = uuid.uuid4().hex
        full_prompt = prompt + "\nWorkspace files: " + ", ".join(sorted(files))
        self.store.create_task(task_id, full_prompt, mode, root, fault=fault, files=files)
        return self.get(task_id)

    def create_demo(self, *, fault: str | None = None) -> dict:
        return self.create_task(DEMO_PROMPT, demo_files(), mode="demo", fault=fault)

    def get(self, task_id: str) -> dict:
        task = self.store.task(task_id)
        calls = self.store.tools(task_id)
        # Do not expose preimages, full tool arguments or filesystem paths in task listings.
        return {
            k: task[k]
            for k in (
                "id",
                "prompt",
                "model_mode",
                "status",
                "attempts",
                "result",
                "error",
                "created_at",
                "updated_at",
            )
        } | {
            "metrics": {
                "tool_calls": len(calls),
                "tool_execution_attempts": sum(row["executions"] for row in calls),
                "reused_results": sum(row["reuses"] for row in calls),
                "file_write_attempts": sum(
                    row["executions"] for row in calls if row["name"] == "replace_text"
                ),
            }
        }

    def schedule(self, task_id: str, *, retry_uncertain_tests: bool = False) -> Future:
        with self._guard:
            if self.store.task(task_id)["status"] in {"succeeded", "failed"}:
                raise ValueError("Finished tasks are immutable; create a new task")
            lock = self._lock(task_id)
            try:
                lock.acquire(timeout=0)
            except Timeout as exc:
                raise TaskBusy("Task is already executing in another worker") from exc
            try:
                # Re-read under the lock: a previous worker may have just finished.
                if self.store.task(task_id)["status"] in {"succeeded", "failed"}:
                    raise ValueError("Finished tasks are immutable; create a new task")
                self.store.set_status(task_id, "running")
                future = self.pool.submit(self._run_locked, task_id, lock, retry_uncertain_tests)
            except BaseException:
                if self.store.task(task_id)["status"] == "running":
                    self.store.set_status(task_id, "interrupted", error="Worker scheduling failed")
                lock.release()
                raise
            return future

    def run_sync(
        self,
        task_id: str,
        *,
        hard_crash: bool = False,
        retry_uncertain_tests: bool = False,
    ) -> dict:
        with self._lock(task_id).acquire(timeout=0):
            if self.store.task(task_id)["status"] in {"succeeded", "failed"}:
                raise ValueError("Finished tasks are immutable; create a new task")
            self.store.set_status(task_id, "running")
            self._execute(
                task_id, hard_crash=hard_crash, retry_uncertain_tests=retry_uncertain_tests
            )
        return self.get(task_id)

    def _run_locked(self, task_id: str, lock: FileLock, retry_uncertain_tests: bool):
        try:
            self._execute(task_id, retry_uncertain_tests=retry_uncertain_tests)
        finally:
            lock.release()

    def _execute(self, task_id: str, *, hard_crash=False, retry_uncertain_tests=False):
        task = self.store.task(task_id)
        workspace = Path(task["workspace"])
        faults = FaultInjector(self.store, task_id, hard=hard_crash)
        runner = ToolRunner(
            self.store,
            task_id,
            workspace,
            faults,
            timeout=self.settings.test_timeout,
            retry_uncertain_tests=retry_uncertain_tests,
        )
        config = {
            "configurable": {"thread_id": task_id},
            "recursion_limit": self.settings.recursion_limit,
        }
        try:
            db_path = str(self.settings.data_dir / "checkpoints" / f"{task_id}.sqlite")
            with SqliteSaver.from_conn_string(db_path) as checkpointer:
                agent = build_agent(task["model_mode"], runner, checkpointer)
                snapshot = agent.get_state(config)
                if snapshot.values and not snapshot.next:
                    # The graph finished before the application status committed.
                    result = snapshot.values
                else:
                    inputs = (
                        None
                        if snapshot.values
                        else {"messages": [{"role": "user", "content": task["prompt"]}]}
                    )
                    result = agent.invoke(inputs, config)
                faults.hit("after_graph")
                self._finalize(task_id, workspace, result)
        except InjectedCrash as exc:
            self.store.set_status(task_id, "interrupted", error=f"Injected crash: {exc}")
        except (RecoveryConflict, UncertainExecution) as exc:
            self.store.set_status(task_id, "blocked", error=str(exc))
        except Exception as exc:
            # Provider errors might echo secrets; persist only the error type.
            self.store.event(task_id, "execution.error", {"type": type(exc).__name__})
            self.store.set_status(
                task_id, "failed", error=f"Execution failed: {type(exc).__name__}"
            )
            raise

    def _finalize(self, task_id: str, workspace: Path, result: dict):
        tests = [
            row
            for row in self.store.tools(task_id)
            if row["name"] == "run_tests" and row["state"] == "succeeded"
        ]
        evidence = json.loads(tests[-1]["result"]) if tests else {}
        verified = evidence.get("verified") and evidence.get("fingerprint") == workspace_digest(
            workspace
        )
        last = result["messages"][-1]
        content = last.content
        answer = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        self.store.event(task_id, "verification.completed", {"verified": bool(verified)})
        self.store.set_status(
            task_id,
            "succeeded" if verified else "failed",
            result=answer,
            error=None if verified else "No passing, non-empty test result for the final workspace",
        )

    def files(self, task_id: str) -> dict[str, str]:
        root = Path(self.store.task(task_id)["workspace"])
        return {
            p.relative_to(root).as_posix(): safe_path(
                root, p.relative_to(root).as_posix()
            ).read_text(encoding="utf-8")
            for p in sorted(root.rglob("*"))
            if p.is_file()
            and not p.is_symlink()
            and not any(
                part.startswith(".") or part == "__pycache__" for part in p.relative_to(root).parts
            )
        }

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)

    def diff(self, task_id: str) -> dict:
        before = self.store.source_files(task_id)
        after = self.files(task_id)
        files = []
        for name in sorted(before.keys() | after.keys()):
            change = "unknown"
            if before:
                if name not in before:
                    change = "added"
                elif name not in after:
                    change = "deleted"
                else:
                    change = "unchanged" if before[name] == after[name] else "modified"
            files.append(
                {
                    "path": name,
                    "before": before.get(name),
                    "after": after.get(name),
                    "change": change,
                }
            )
        return {"baseline_available": bool(before), "files": files}
