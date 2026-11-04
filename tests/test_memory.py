import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_workbench.api import create_app
from harness_workbench.config import Settings
from harness_workbench.memory import MemoryBank, MemoryConflict
from harness_workbench.service import TaskService
from harness_workbench.store import Store
from harness_workbench.tools import digest


def test_memory_survives_restart_and_is_injected_into_two_tasks(service):
    memory = service.memory.put(
        "repo-a", "style", "Use explicit types in calculator.py", kind="constraint"
    )
    first = service.create_demo(memory_scope="repo-a")
    assert service.run_sync(first["id"])["status"] == "succeeded"
    restarted = TaskService(service.settings)
    try:
        second = restarted.create_demo(memory_scope="repo-a")
        assert restarted.run_sync(second["id"])["status"] == "succeeded"
        for task_id in (first["id"], second["id"]):
            views = restarted.context_views(task_id)
            assert views[0]["memory_references"][0]["id"] == memory["id"]
            assert "Use explicit types" in str(views[0]["messages"])
        assert len([m for m in restarted.memory.list("repo-a") if m["kind"] == "experience"]) == 2
    finally:
        restarted.close()


def test_scope_and_unscoped_tasks_are_isolated(service):
    task = service.create_demo()
    workspace = Path(service.store.task(task["id"])["workspace"])
    service.memory.put("repo-a", "rules", "Never modify calculator.py tests", kind="constraint")
    assert not service.memory.recall("repo-b", "calculator", workspace)["selected"]
    assert not service.memory.recall(None, "calculator", workspace)["selected"]


@pytest.mark.parametrize("scope", ["", "../repo", "a/b", "a:b", "with space"])
def test_invalid_scope_is_rejected_before_task_creation(service, scope):
    with pytest.raises(ValueError):
        service.create_demo(memory_scope=scope)
    assert not service.store.tasks()


def test_update_is_versioned_and_stale_writer_cannot_overwrite(service):
    bank = service.memory
    bank.put("repo", "style", "old", kind="constraint")
    current = bank.put("repo", "style", "new", expected_version=1, kind="constraint")
    assert current["version"] == 2
    with pytest.raises(MemoryConflict):
        bank.put("repo", "style", "stale", expected_version=1)
    assert [(m["content"], m["status"]) for m in bank.list("repo", history=True)] == [
        ("old", "superseded"),
        ("new", "active"),
    ]


@pytest.mark.parametrize("delete", [True, False])
def test_retired_latest_revision_never_resurrects_an_older_one(service, delete):
    bank = service.memory
    bank.put("repo", "key", "old", kind="constraint")
    bank.put("repo", "key", "new", kind="constraint", expected_version=1)
    retired = bank.retire("repo", "key", expected_version=2, delete=delete)
    assert retired["version"] == 3
    assert retired["status"] == ("deleted" if delete else "invalid")
    assert not bank.recall("repo", "new old", service.settings.data_dir)["selected"]
    assert len(bank.list("repo")) == 1
    if delete:
        assert retired["content"] == ""


def test_expired_memory_is_excluded(service, monkeypatch):
    import harness_workbench.memory as module

    value = service.memory.put("repo", "key", "constraint", kind="constraint", expires_in_seconds=1)
    monkeypatch.setattr(module.time, "time", lambda: value["expires_at"] + 1)
    result = service.memory.recall("repo", "constraint", service.settings.data_dir)
    assert not result["selected"] and result["excluded"][0]["reason"] == "expired"


def test_file_evidence_is_revalidated_for_each_workspace(service):
    task = service.create_demo(memory_scope="repo")
    workspace = Path(service.store.task(task["id"])["workspace"])
    path = workspace / "calculator.py"
    original = path.read_bytes()
    service.memory.put(
        "repo",
        "calculator",
        "calculator.py has two arguments",
        source_task=task["id"],
        evidence={"calculator.py": digest(original)},
    )
    assert service.memory.recall("repo", "calculator", workspace)["selected"]
    path.write_text("changed", encoding="utf-8")
    recall = service.memory.recall("repo", "calculator", workspace)
    assert recall["excluded"][0]["reason"] == "stale_for_workspace"
    assert not recall["selected"]
    # A different checkout with the matching file can still use this evidence.
    path.write_bytes(original)
    assert service.memory.recall("repo", "calculator", workspace)["selected"]


def test_wrong_source_scope_bad_hash_missing_file_and_unverified_experience_rejected(service):
    task = service.create_demo(memory_scope="a")
    with pytest.raises(ValueError, match="another"):
        service.memory.put("b", "x", "fact", source_task=task["id"])
    with pytest.raises(ValueError, match="SHA256"):
        service.memory.put("a", "x", "fact", source_task=task["id"], evidence={"x.py": "bad"})
    with pytest.raises(ValueError, match="unavailable"):
        service.memory.put("a", "x", "fact", source_task=task["id"], evidence={"x.py": "0" * 64})
    with pytest.raises(ValueError, match="verified"):
        service.memory.put("a", "x", "success", source_task=task["id"], kind="experience")
    with pytest.raises(ValueError, match="source task"):
        service.memory.put("a", "x", "fact", evidence={"x.py": "0" * 64})


def test_irrelevant_facts_are_not_recalled_but_scoped_constraints_are(service):
    bank = service.memory
    bank.put("repo", "colors", "主题颜色设置为蓝色")
    bank.put("repo", "typing", "Use type hints", kind="constraint")
    recall = bank.recall("repo", "修复加法计算错误", service.settings.data_dir)
    assert [m["key"] for m in recall["selected"]] == ["typing"]
    assert recall["excluded"][0]["reason"] == "irrelevant"


def test_concurrent_memory_writers_use_revision_cas(service):
    service.memory.put("repo", "key", "first")

    def update(content):
        try:
            return MemoryBank(Store(service.store.path)).put(
                "repo", "key", content, expected_version=1
            )["version"]
        except MemoryConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ["a", "b"]))
    assert sorted(map(str, results)) == ["2", "conflict"]


def test_additive_schema_migration_preserves_old_tasks(service):
    task = service.create_demo()
    with sqlite3.connect(service.store.path) as db:
        for table in ("memories", "task_scopes", "context_views"):
            db.execute(f"DROP TABLE {table}")
    migrated = Store(service.store.path)
    assert migrated.task(task["id"])["memory_scope"] is None
    assert not MemoryBank(migrated).list("repo")
    assert Store(service.store.path).task(task["id"])["id"] == task["id"]


def test_memory_api_lifecycle_and_cross_scope_recall(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        created = client.put(
            "/memory/repo", json={"key": "style", "content": "type hints", "kind": "constraint"}
        )
        assert created.status_code == 200 and created.json()["version"] == 1
        assert (
            client.put("/memory/repo", json={"key": "style", "content": "overwrite"}).status_code
            == 409
        )
        task = client.post("/tasks/demo", json={"memory_scope": "repo"}).json()
        assert client.post("/memory/other/recall", json={"task_id": task["id"]}).status_code == 409
        recall = client.post("/memory/repo/recall", json={"task_id": task["id"]}).json()
        assert any(m["key"] == "style" for m in recall["selected"])
        assert (
            client.post(
                "/memory/repo/invalidate", json={"key": "style", "expected_version": 1}
            ).json()["status"]
            == "invalid"
        )
        assert client.delete("/memory/repo/style?expected_version=2").json()["status"] == "deleted"
        assert client.get("/memory/repo?history=true").status_code == 200
        assert client.get(f"/tasks/{task['id']}/context").status_code == 200
        assert client.put("/memory/bad:scope", json={"key": "x", "content": "y"}).status_code == 422
