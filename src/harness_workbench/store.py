"""SQLite application state. LangGraph checkpoints live in a separate database."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, prompt TEXT NOT NULL, model_mode TEXT NOT NULL,
                    workspace TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                    attempts INTEGER NOT NULL DEFAULT 0, result TEXT, error TEXT,
                    fault TEXT, fault_used INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                    kind TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_task ON events(task_id, id);
                CREATE TABLE IF NOT EXISTS tool_calls (
                    task_id TEXT NOT NULL, call_id TEXT NOT NULL, name TEXT NOT NULL,
                    arguments TEXT NOT NULL, state TEXT NOT NULL,
                    prepared TEXT, result TEXT, error TEXT,
                    executions INTEGER NOT NULL DEFAULT 0,
                    reuses INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL,
                    PRIMARY KEY (task_id, call_id)
                );
                CREATE TABLE IF NOT EXISTS source_files (
                    task_id TEXT NOT NULL, path TEXT NOT NULL, content TEXT NOT NULL,
                    PRIMARY KEY (task_id, path)
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_task(
        self, task_id: str, prompt: str, mode: str, workspace: Path, fault=None, files=None
    ):
        now = time.time()
        with self.connect() as db:
            db.execute(
                "INSERT INTO tasks(id,prompt,model_mode,workspace,fault,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (task_id, prompt, mode, str(workspace), fault, now, now),
            )
            db.executemany(
                "INSERT INTO source_files(task_id,path,content) VALUES(?,?,?)",
                [(task_id, name, content) for name, content in (files or {}).items()],
            )
        self.event(task_id, "task.created", {"model_mode": mode})

    def source_files(self, task_id: str) -> dict[str, str]:
        with self.connect() as db:
            return {
                row["path"]: row["content"]
                for row in db.execute(
                    "SELECT path,content FROM source_files WHERE task_id=? ORDER BY path",
                    (task_id,),
                )
            }

    def task(self, task_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return dict(row)

    def tasks(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM tasks ORDER BY created_at DESC")]

    def set_status(self, task_id: str, status: str, *, result=None, error=None):
        with self.connect() as db:
            db.execute(
                "UPDATE tasks SET status=?,result=?,error=?,updated_at=?,"
                "attempts=attempts+? WHERE id=?",
                (status, result, error, time.time(), int(status == "running"), task_id),
            )
        self.event(task_id, f"task.{status}", {"error": error})

    def event(self, task_id: str, kind: str, payload: dict):
        with self.connect() as db:
            db.execute(
                "INSERT INTO events(task_id,kind,payload,created_at) VALUES(?,?,?,?)",
                (task_id, kind, encode(payload), time.time()),
            )

    def events(self, task_id: str, after: int = 0) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM events WHERE task_id=? AND id>? ORDER BY id LIMIT 500",
                (task_id, after),
            ).fetchall()
        return [dict(row) | {"payload": json.loads(row["payload"])} for row in rows]

    def tool(self, task_id: str, call_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM tool_calls WHERE task_id=? AND call_id=?", (task_id, call_id)
            ).fetchone()
        return dict(row) if row else None

    def tools(self, task_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM tool_calls WHERE task_id=? ORDER BY updated_at", (task_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def prepare(self, task_id: str, call_id: str, name: str, args: dict, prepared: dict):
        with self.connect() as db:
            db.execute(
                "INSERT INTO tool_calls(task_id,call_id,name,arguments,state,prepared,updated_at) "
                "VALUES(?,?,?,?,'prepared',?,?)",
                (task_id, call_id, name, encode(args), encode(prepared), time.time()),
            )
        self.event(task_id, "tool.prepared", {"call_id": call_id, "name": name})

    def tool_started(self, task_id: str, call_id: str):
        with self.connect() as db:
            db.execute(
                "UPDATE tool_calls SET state='started',executions=executions+1,updated_at=? "
                "WHERE task_id=? AND call_id=?",
                (time.time(), task_id, call_id),
            )

    def tool_done(self, task_id: str, call_id: str, result: dict):
        with self.connect() as db:
            db.execute(
                "UPDATE tool_calls SET state='succeeded',result=?,error=NULL,updated_at=? "
                "WHERE task_id=? AND call_id=?",
                (encode(result), time.time(), task_id, call_id),
            )
        self.event(task_id, "tool.completed", {"call_id": call_id, "result": result})

    def tool_reused(self, task_id: str, call_id: str, reason: str):
        with self.connect() as db:
            db.execute(
                "UPDATE tool_calls SET reuses=reuses+1,updated_at=? WHERE task_id=? AND call_id=?",
                (time.time(), task_id, call_id),
            )
        self.event(task_id, "tool.reused", {"call_id": call_id, "reason": reason})

    def consume_fault(self, task_id: str, point: str) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE tasks SET fault_used=1 WHERE id=? AND fault=? AND fault_used=0",
                (task_id, point),
            )
            return cursor.rowcount == 1
