"""Memory content, hybrid retrieval and lifecycle boundaries, without model/network calls."""

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import harness_workbench.memory_search as search
from harness_workbench.api import create_app
from harness_workbench.config import Settings
from harness_workbench.memory import MemoryBank
from harness_workbench.memory_search import LocalMemoryEncoder, bm25, rank
from harness_workbench.repair_memory import make_card, redact
from harness_workbench.service import TaskService
from harness_workbench.store import encode
from harness_workbench.tools import digest


class FixedEncoder:
    def __init__(self, hook=None):
        self.hook = hook
        self.requests = []

    def embed(self, texts):
        self.requests.append(texts)
        if self.hook:
            self.hook()
        return [[1.0, 0.0] for _ in texts]


def verified_task(service):
    task = service.create_demo(memory_scope="project")
    assert service.run_sync(task["id"])["status"] == "succeeded"
    return task


def test_verified_repair_has_problem_patch_and_independent_evidence(service):
    task = verified_task(service)
    item = service.memory.list("project")[0]
    card = item["details"]
    assert card["record_type"] == "verified_repair"
    assert card["root_cause"] == "not_inferred"
    assert card["problem"] and "return a - b" in card["observed_remedy"]
    assert "return a + b" in card["observed_remedy"]
    assert card["changes"][0]["symbols"] == ["add"]
    assert card["verification"]["tests_run"] == 3
    assert card["verification"]["source_task"] == task["id"]
    assert card["verification"]["acceptance_origin"] == "uploaded_tests"


def test_experience_is_reference_on_changed_files_but_file_fact_stays_strict(service):
    task = verified_task(service)
    source = Path(service.store.task(task["id"])["workspace"])
    service.memory.put(
        "project",
        "current-file-fact",
        "calculator.py uses addition",
        source_task=task["id"],
        evidence={"calculator.py": digest((source / "calculator.py").read_bytes())},
    )
    new = service.create_demo(memory_scope="project")
    workspace = Path(service.store.task(new["id"])["workspace"])
    result = service.memory.recall("project", "calculator add", workspace, mode="bm25")
    assert len(result["selected"]) == 1
    assert result["selected"][0]["kind"] == "experience"
    assert result["selected"][0]["evidence_status"] == "changed_or_missing_files"
    assert "reference_only" in result["selected"][0]["use_policy"]
    assert any(m["reason"] == "stale_for_workspace" for m in result["excluded"])


def test_followup_task_after_service_restart_receives_historical_experience(service):
    first = verified_task(service)
    restarted = TaskService(service.settings)
    try:
        second = restarted.create_demo(memory_scope="project")
        assert restarted.run_sync(second["id"])["status"] == "succeeded"
        refs = restarted.context_views(second["id"])[0]["memory_references"]
        experience = next(item for item in refs if item["source_task"] == first["id"])
        assert "reference_only" in experience["use_policy"]
        assert experience["evidence_status"] == "changed_or_missing_files"
        assert "历史修改" in experience["content"]
    finally:
        restarted.close()


def test_failed_or_stale_acceptance_never_generates_experience(service):
    task = service.create_demo(memory_scope="project")
    workspace = Path(service.store.task(task["id"])["workspace"])
    with pytest.raises(ValueError, match="independent"):
        make_card(service.store, service.store.task(task["id"]), workspace, ["calculator.py"])
    assert service.memory.list("project") == []
    service.run_sync(task["id"])
    (workspace / "calculator.py").write_text("VALUE=1", encoding="utf-8")
    with pytest.raises(ValueError, match="fresh"):
        make_card(service.store, service.store.task(task["id"]), workspace, ["calculator.py"])


def test_repeated_verified_experience_is_deduplicated_during_recall(service):
    verified_task(service)
    verified_task(service)
    assert len(service.memory.list("project")) == 2  # Complete source-task audit retained.
    result = service.memory.recall(
        "project", "calculator add", service.settings.data_dir, mode="bm25"
    )
    assert len(result["selected"]) == 1
    assert any(item["reason"] == "duplicate" for item in result["excluded"])


def test_lost_source_verification_excludes_historical_experience(service):
    task = verified_task(service)
    with service.store.connect() as db:
        db.execute(
            "UPDATE tool_calls SET result=? WHERE task_id=? AND name='harness_acceptance'",
            (encode({"verified": False}), task["id"]),
        )
    result = service.memory.recall("project", "calculator", service.settings.data_dir, mode="bm25")
    assert not result["selected"]
    assert result["excluded"][0]["reason"] == "unverified_source"


def test_bm25_and_rrf_are_real_rankings_with_empty_rejection():
    documents = ["数组 空输入 返回默认值", "登录凭据 JWT 刷新", "网页颜色"]
    scores = bm25("空输入", documents)
    assert scores[0] > 0 and scores[1:] == [0, 0]
    assert rank("火山地质", documents, mode="bm25") == []
    vectors = [[1, 0], [1, 0], [0, 1], [-1, 0]]
    result = rank("空输入", documents, vectors)
    assert result[0]["index"] == 0 and result[0]["cosine"] == 1
    assert result[0]["rrf"] == pytest.approx(2 / 61)


def test_dense_only_synonym_can_recall_without_lexical_overlap(service):
    service.memory.put("project", "jwt", "JWT 令牌过期")
    bank = MemoryBank(service.store, encoder=FixedEncoder())
    assert not bank.recall("project", "突然需要重新登录", service.settings.data_dir, mode="bm25")[
        "selected"
    ]
    result = bank.recall("project", "突然需要重新登录", service.settings.data_dir)
    assert result["selected"][0]["key"] == "jwt"
    assert result["retrieval"]["used"] == "hybrid"


@pytest.mark.parametrize("mutation", ["delete", "invalidate", "replace"])
def test_revision_changed_during_embedding_is_not_injected(service, mutation):
    bank = service.memory
    bank.put("project", "jwt", "JWT 令牌过期")

    def mutate():
        if mutation == "replace":
            bank.put("project", "jwt", "new revision", expected_version=1)
        else:
            bank.retire("project", "jwt", expected_version=1, delete=mutation == "delete")

    bank.encoder = FixedEncoder(mutate)
    result = bank.recall("project", "令牌过期", service.settings.data_dir)
    assert not result["selected"]
    assert any(item["reason"] == "revision_changed" for item in result["excluded"])


@pytest.mark.parametrize(
    "failure", [ValueError("broken native worker"), subprocess.TimeoutExpired("embedding", 12)]
)
def test_embedding_error_or_timeout_falls_back_to_bm25(service, failure):
    class Broken:
        def embed(self, texts):
            raise failure

    service.memory.put("project", "jwt", "JWT 令牌过期")
    bank = MemoryBank(service.store, encoder=Broken())
    result = bank.recall("project", "JWT", service.settings.data_dir)
    assert result["selected"][0]["key"] == "jwt"
    assert result["retrieval"]["used"] == "bm25"
    assert result["retrieval"]["fallback"] == "encoder_unavailable"
    assert "broken native" not in str(result)


def test_retrieval_never_encodes_other_scope_or_retired_records(service):
    service.memory.put("project", "keep", "JWT 令牌过期")
    service.memory.put("other-project", "secret", "other project private note")
    service.memory.put("project", "gone", "deleted private note")
    service.memory.retire("project", "gone", expected_version=1, delete=True)
    encoder = FixedEncoder()
    bank = MemoryBank(service.store, encoder=encoder)
    bank.recall("project", "JWT", service.settings.data_dir)
    assert "private" not in str(encoder.requests)


def test_cached_embeddings_do_not_revive_deleted_revision(service, monkeypatch):
    calls = []

    def fake_worker(python, payload):
        calls.append(payload)
        return {"identity": "test-model", "vectors": [[1, 0] for _ in payload["texts"]]}

    monkeypatch.setattr(search, "worker", fake_worker)
    encoder = LocalMemoryEncoder(service.store)
    encoder.profile.write_text(
        encode(
            {"identity": "test-model", "dimensions": 2, "python": "unused", "cache_dir": "unused"}
        ),
        encoding="utf-8",
    )
    bank = MemoryBank(service.store, encoder=encoder)
    bank.put("project", "jwt", "JWT 令牌过期")
    assert bank.recall("project", "JWT", service.settings.data_dir)["selected"]
    assert bank.recall("project", "JWT", service.settings.data_dir)["selected"]
    assert len(calls) == 1
    bank.retire("project", "jwt", expected_version=1, delete=True)
    assert not bank.recall("project", "JWT", service.settings.data_dir)["selected"]
    assert len(calls) == 1


def test_corrupt_vector_cache_is_not_trusted(service):
    encoder = LocalMemoryEncoder(service.store)
    encoder.profile.write_text(encode({"identity": "test", "dimensions": 2}), encoding="utf-8")
    with service.store.connect() as db:
        db.execute("INSERT INTO memory_vectors VALUES (?,?,?)", ("test", digest(b"query"), "[1]"))
    with pytest.raises(ValueError, match="vector"):
        encoder.embed(["query"])


def test_redaction_removes_credential_values():
    text = redact("api_key='example-value' token=another-secret password=sample")
    assert "example-value" not in text and "another-secret" not in text and "sample" not in text


def test_memory_api_recall_debug_and_model_status(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        status = client.get("/memory-status").json()
        assert status["fusion"] == "rrf" and not status["model_prepared"]
        client.put("/memory/project", json={"key": "jwt", "content": "JWT 令牌过期"})
        task = client.app.state.service.create_demo(memory_scope="project")
        result = client.post(
            "/memory/project/recall",
            json={
                "task_id": task["id"],
                "query": "JWT",
                "mode": "hybrid",
                "top_k": 1,
            },
        )
        assert result.status_code == 200
        assert result.json()["selected"][0]["key"] == "jwt"
        assert result.json()["retrieval"]["fallback"] == "model_not_prepared"
        assert (
            client.post(
                "/memory/project/recall",
                json={
                    "task_id": task["id"],
                    "mode": "invalid",
                },
            ).status_code
            == 422
        )
