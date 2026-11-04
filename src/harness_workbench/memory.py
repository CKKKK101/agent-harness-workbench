"""Explicitly scoped, versioned cross-task memory. No automatic LLM fact writes."""

from __future__ import annotations

import json
import re
import time
import uuid

from .memory_search import LocalMemoryEncoder
from .repair_memory import make_card
from .store import Store, encode
from .tools import digest, read_bytes, safe_path


class MemoryConflict(ValueError):
    """The caller edited an old revision; never silently overwrite another writer."""


def validate_scope(scope: str | None):
    if scope is not None and not re.fullmatch(r"[\w.-]{1,80}", scope):
        raise ValueError("Memory scope must contain 1..80 letters, numbers, dots or hyphens")
    return scope


def words(text: str) -> set[str]:
    ascii_words = re.findall(r"[a-z0-9_]+", text.casefold())
    han = re.findall(r"[\u4e00-\u9fff]+", text)
    return set(ascii_words) | {s[i : i + 2] for s in han for i in range(max(1, len(s) - 1))}


class MemoryBank:
    def __init__(self, store: Store, *, encoder=None):
        self.store = store
        self.encoder = encoder or LocalMemoryEncoder(store)

    @staticmethod
    def _decode(row):
        value = dict(row)
        details = value.get("details")
        return value | {
            "evidence": json.loads(row["evidence"]),
            "details": json.loads(details) if isinstance(details, str) else details,
        }

    def list(self, scope, *, history=False):
        validate_scope(scope)
        sql = (
            "SELECT m.*,d.details FROM memories m LEFT JOIN memory_details d "
            "ON d.memory_id=m.id WHERE m.scope=?"
        )
        if not history:
            sql += (
                " AND NOT EXISTS (SELECT 1 FROM memories newer WHERE newer.scope=m.scope "
                "AND newer.key=m.key AND newer.version>m.version)"
            )
        with self.store.connect() as db:
            rows = db.execute(sql + " ORDER BY m.key,m.version", (scope,)).fetchall()
        return [self._decode(row) for row in rows]

    def put(
        self,
        scope,
        key,
        content,
        *,
        kind="fact",
        expected_version=None,
        source_task=None,
        evidence=None,
        expires_in_seconds=None,
        _details=None,
    ):
        validate_scope(scope)
        if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,100}", key):
            raise ValueError("Invalid memory key")
        if (
            kind not in {"constraint", "fact", "experience"}
            or not 1 <= len(content.strip()) <= 2000
        ):
            raise ValueError("Invalid memory kind or content")
        if expires_in_seconds is not None and not 1 <= expires_in_seconds <= 31_536_000:
            raise ValueError("Memory expiry must be between one second and one year")
        evidence = evidence or {}
        if len(evidence) > 30 or (evidence and not source_task):
            raise ValueError("File evidence requires a source task and at most 30 paths")
        if source_task:
            task = self.store.task(source_task)
            if task["memory_scope"] != scope:
                raise ValueError("Source task belongs to another memory scope")
            if kind == "experience" and task["status"] != "succeeded":
                raise ValueError("Repair experiences require Harness-verified successful tasks")
            from pathlib import Path

            for path, expected in evidence.items():
                if not re.fullmatch(r"[0-9a-f]{64}", expected):
                    raise ValueError("File evidence must use a SHA256 hash")
                try:
                    observed = digest(read_bytes(safe_path(Path(task["workspace"]), path)))
                except OSError as exc:
                    raise ValueError("File evidence is unavailable") from exc
                if observed != expected:
                    raise ValueError("File evidence is stale")
        elif kind == "experience":
            raise ValueError("Repair experiences require a successful source task")
        now = time.time()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            latest = db.execute(
                "SELECT * FROM memories WHERE scope=? AND key=? ORDER BY version DESC LIMIT 1",
                (scope, key),
            ).fetchone()
            if (latest["version"] if latest else None) != expected_version:
                raise MemoryConflict("Memory revision changed; reload before updating")
            version = expected_version + 1 if latest else 1
            if latest:
                db.execute("UPDATE memories SET status='superseded' WHERE id=?", (latest["id"],))
            memory_id = uuid.uuid4().hex
            db.execute(
                "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    memory_id,
                    scope,
                    key,
                    version,
                    kind,
                    content.strip(),
                    "active",
                    source_task,
                    encode(evidence),
                    now,
                    now + expires_in_seconds if expires_in_seconds else None,
                ),
            )
            if _details:
                db.execute("INSERT INTO memory_details VALUES (?,?)", (memory_id, encode(_details)))
        with self.store.connect() as db:
            return self._decode(
                db.execute(
                    "SELECT m.*,d.details FROM memories m LEFT JOIN memory_details d "
                    "ON d.memory_id=m.id WHERE m.id=?",
                    (memory_id,),
                ).fetchone()
            )

    def retire(self, scope, key, *, expected_version, delete=False):
        validate_scope(scope)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM memories WHERE scope=? AND key=? ORDER BY version DESC LIMIT 1",
                (scope, key),
            ).fetchone()
            if row is None:
                raise KeyError(key)
            if row["version"] != expected_version:
                raise MemoryConflict("Memory revision changed; reload before retiring")
            value = dict(row)
            db.execute("UPDATE memories SET status='superseded' WHERE id=?", (row["id"],))
            value.update(
                id=uuid.uuid4().hex,
                version=expected_version + 1,
                status="deleted" if delete else "invalid",
                created_at=time.time(),
            )
            if delete:
                value["content"] = ""
            db.execute(
                "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                tuple(
                    value[k]
                    for k in (
                        "id",
                        "scope",
                        "key",
                        "version",
                        "kind",
                        "content",
                        "status",
                        "source_task",
                        "evidence",
                        "created_at",
                        "expires_at",
                    )
                ),
            )
            if not delete:
                db.execute(
                    "INSERT INTO memory_details SELECT ?,details FROM memory_details "
                    "WHERE memory_id=?",
                    (value["id"], row["id"]),
                )
        return self._decode(value)

    def recall(self, scope, query, workspace, *, limit=3, mode="hybrid"):
        from .memory_recall import recall

        return recall(self, scope, query, workspace, limit=limit, mode=mode)

    def remember_success(self, task, workspace):
        """Persist only a compact, verifiable outcome, not model-generated claims."""
        scope = task["memory_scope"]
        if not scope:
            return
        key = "repair:" + task["id"]
        if any(m["key"] == key for m in self.list(scope)):
            return  # Idempotent if a caller repeats post-success recording.
        edits = [
            row
            for row in self.store.tools(task["id"])
            if row["name"] == "replace_text" and row["state"] == "succeeded"
        ]
        paths = sorted({json.loads(row["arguments"])["path"] for row in edits})
        if not paths:
            return
        card = make_card(self.store, task, workspace, paths)
        if card is None:
            return
        content, evidence, details = card
        self.put(
            scope,
            key,
            content,
            kind="experience",
            source_task=task["id"],
            evidence=evidence,
            expires_in_seconds=30 * 24 * 3600,
            _details=details,
        )
