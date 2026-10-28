import time

from fastapi.testclient import TestClient

from harness_workbench.api import create_app
from harness_workbench.config import Settings


def test_api_demo_events_files_and_terminal_resume(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        assert client.get("/health").json()["model_mode"] == "demo"
        created = client.post("/tasks/demo")
        assert created.status_code == 202
        task_id = created.json()["id"]
        for _ in range(100):
            task = client.get(f"/tasks/{task_id}").json()
            if task["status"] != "running":
                break
            time.sleep(0.05)
        assert task["status"] == "succeeded"
        assert client.post(f"/tasks/{task_id}/resume", json={}).status_code == 409
        files = client.get(f"/tasks/{task_id}/files").json()
        assert "return a + b" in files["calculator.py"]
        diff = client.get(f"/tasks/{task_id}/diff").json()
        assert diff["baseline_available"]
        changed = [entry for entry in diff["files"] if entry["change"] == "modified"]
        assert len(changed) == 1
        assert "return a - b" in changed[0]["before"]
        assert "return a + b" in changed[0]["after"]
        events = client.get(f"/tasks/{task_id}/events").json()
        assert any(e["kind"] == "verification.completed" for e in events)
        with client.stream("GET", f"/tasks/{task_id}/stream") as response:
            text = "".join(response.iter_text())
        assert "event: task.succeeded" in text
        cursor = events[-1]["id"]
        assert client.get(f"/tasks/{task_id}/events?after={cursor}").json() == []
        assert client.get("/tasks/not-found").status_code == 404


def test_api_rejects_paths_before_creating_task(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        response = client.post(
            "/tasks",
            json={
                "prompt": "Please fix this code",
                "files": {"../outside.py": "x", "test_a.py": "x"},
            },
        )
        assert response.status_code == 422
        assert client.get("/tasks").json() == []


def test_real_model_configuration_fails_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        response = client.post(
            "/tasks",
            json={
                "prompt": "Please fix this code",
                "files": {"test_a.py": "x"},
                "model_mode": "openai",
            },
        )
        assert response.status_code == 422
        assert "requires" in response.json()["detail"]


def test_frontend_assets_and_safe_model_status(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-key-not-for-the-browser")
    monkeypatch.setenv("OPENAI_MODEL", "example-model")
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Harness Studio" in response.text
        for asset in ("app.js", "styles.css", "favicon.svg"):
            assert client.get(f"/assets/{asset}").status_code == 200
        health = client.get("/health")
        assert health.json()["model_configured"] is True
        assert health.json()["model_name"] == "example-model"
        assert "private-key-not-for-the-browser" not in health.text


def test_legacy_task_diff_does_not_invent_a_baseline(service):
    task = service.create_demo()
    with service.store.connect() as db:
        db.execute("DELETE FROM source_files WHERE task_id=?", (task["id"],))
    diff = service.diff(task["id"])
    assert not diff["baseline_available"]
    assert all(entry["change"] == "unknown" and entry["before"] is None for entry in diff["files"])
