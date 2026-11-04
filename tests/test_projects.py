"""Repository workflow regressions; no network/model calls or unreviewed code execution."""

import io
import json
import stat
import zipfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_journal import runner_for

import harness_workbench.agent as agent_module
import harness_workbench.projects as projects_module
import harness_workbench.service as service_module
from harness_workbench.api import create_app
from harness_workbench.config import Settings
from harness_workbench.faults import RecoveryConflict
from harness_workbench.fixtures import demo_files
from harness_workbench.models import DemoRepairModel
from harness_workbench.projects import snapshot, unpack_archive

BUG = "Repair calculator add: it subtracts instead of adding"
EXPECTED = "add(2, 3) returns 5, including zero and negative operands"
CANDIDATES = {
    "test_calculator.py": (
        "from calculator import add\ndef test_add():\n"
        "    assert add(2, 3) == 5\n    assert add(-1, 1) == 0\n"
    )
}


@pytest.fixture
def fake_model(monkeypatch):
    # Exercise the real graph/service and supervised processes, with deterministic decisions.
    monkeypatch.setattr(service_module, "create_model", lambda _: DemoRepairModel())
    monkeypatch.setattr(agent_module, "create_model", lambda _: DemoRepairModel())


def test_import_discovers_nested_tests_without_executing_or_reading_host(service, tmp_path):
    sentinel = tmp_path / "must-not-exist"
    code = f"from pathlib import Path\nPath({str(sentinel)!r}).touch()\n"
    project = service.projects.create(
        files={
            "src/application.py": code,
            "tests/unit/test_application.py": code + "def test_app(): assert True\n",
            "tests/extra_test.py": "def test_extra(): assert True\n",
            ".env": "SECRET=do-not-copy",
            "node_modules/pkg/test_x.py": code,
        }
    )
    assert project["test_files"] == ["tests/extra_test.py", "tests/unit/test_application.py"]
    assert project["framework"] == "pytest" and not project["needs_acceptance"]
    assert service.projects.load(project["id"])["files"]["src/application.py"] == code
    assert len(project["files"]) == 3
    assert not sentinel.exists() and not service.store.tasks()


@pytest.mark.parametrize(
    "path",
    [
        "../escape.py",
        "/absolute.py",
        "C:/host.py",
        "tests\\test_x.py",
        "a/../test_x.py",
        "CON.py",
        "x./test_x.py",
        "x\x00.py",
    ],
)
def test_import_rejects_unsafe_paths(service, path):
    with pytest.raises(ValueError):
        service.projects.create(files={path: "pass"})
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM project_imports").fetchone()[0] == 0


def test_import_size_and_case_collisions():
    with pytest.raises(ValueError, match="case-colliding"):
        snapshot({"a.py": "pass", "A.py": "pass"})
    with pytest.raises(ValueError, match="large"):
        snapshot({"a.py": "#" * 256_001})
    with pytest.raises(ValueError, match="200"):
        snapshot({f"a{i}.py": "pass" for i in range(201)})


def archive(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as target:
        for path, content in entries.items():
            target.writestr(path, content)
    return stream.getvalue()


def test_github_archive_import_strips_one_root_and_excludes_secrets():
    files = unpack_archive(
        archive(
            {
                "owner-revision/app.py": "VALUE=1",
                "owner-revision/tests/test_app.py": "def test_app(): assert True",
                "owner-revision/.env": "SECRET=value",
                "owner-revision/.git/config": "secret",
            }
        )
    )
    assert sorted(files) == ["app.py", "tests/test_app.py"]


@pytest.mark.parametrize(
    "entries",
    [
        {"root/../escape.py": "pass"},
        {"root/a.py": "pass", "root/A.py": "pass"},
        {"first/a.py": "pass", "second/b.py": "pass"},
        {"root/a.py": "#" * 256_001},
    ],
)
def test_github_archive_rejects_traversal_collisions_and_limits(entries):
    with pytest.raises(ValueError):
        unpack_archive(archive(entries))


def test_github_archive_rejects_symlink():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as target:
        entry = zipfile.ZipInfo("root/app.py")
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        target.writestr(entry, "../../outside.py")
    with pytest.raises(ValueError, match="links"):
        unpack_archive(stream.getvalue())


def test_public_github_download_and_url_restrictions(service, monkeypatch):
    requests = []

    def open_archive(request, timeout):
        requests.append((request.full_url, timeout))
        return io.BytesIO(archive({"root/app.py": "VALUE=1"}))

    monkeypatch.setattr(
        projects_module.urllib.request,
        "build_opener",
        lambda *_: SimpleNamespace(open=open_archive),
    )
    project = service.projects.create(github_url="https://github.com/owner/repo.git")
    assert project["label"] == "owner/repo" and project["source"] == "github"
    assert requests == [("https://api.github.com/repos/owner/repo/zipball", 25)]
    for url in [
        "http://github.com/a/b",
        "https://localhost/a/b",
        "file:///tmp/a",
        "https://github.com@evil.test/a/b",
        "https://github.com/a/b?token=x",
        "https://github.com/a/b/tree/main",
        "https://github.com/../repo",
    ]:
        with pytest.raises(ValueError):
            service.projects.create(github_url=url)
    assert len(requests) == 1


@pytest.mark.parametrize("passes", [True, False])
def test_imported_project_partial_success_never_bypasses_full_pytest_suite(
    service, fake_model, passes
):
    project = service.projects.create(
        files=demo_files()
        | {
            "tests/other_test.py": f"def test_extra(): assert {passes}\n",
            "pytest.ini": "[pytest]\naddopts = -k does_not_exist\n",
        }
    )
    task = service.create_from_project(project["id"], BUG)
    final = service.run_sync(task["id"])
    rows = service.store.tools(task["id"])
    partial = next(row for row in rows if row["name"] == "run_tests")
    assert json.loads(partial["result"])["verified"]
    evidence = json.loads(next(r for r in rows if r["name"] == "harness_acceptance")["result"])
    assert evidence["tests_run"] == 4 and evidence["verified"] == passes
    assert evidence["targets"] == ["test_calculator.py", "tests/other_test.py"]
    assert final["status"] == ("succeeded" if passes else "failed")
    assert final["acceptance"]["origin"] == "repository_tests"


def test_nested_pytest_target_and_src_layout(service, fake_model):
    project = service.projects.create(
        files={
            "src/application.py": "VALUE=42\n",
            "tests/test_app.py": (
                "from application import VALUE\ndef test_value(): assert VALUE == 42\n"
            ),
        }
    )
    task = service.create_from_project(project["id"], BUG)
    runner = runner_for(service, task)
    assert runner.execute("nested", "run_tests", {"target": "tests/test_app.py"})["verified"]
    assert runner.acceptance(service.store.source_files(task["id"]))["verified"]


@pytest.mark.parametrize(
    "source",
    [
        "import pytest\n@pytest.mark.skip\ndef test_skipped(): assert False\n",
        "import unittest\n@unittest.skip('skip')\nclass T(unittest.TestCase):\n"
        "    def test_skipped(self): self.fail()\n",
    ],
)
def test_all_skipped_is_not_successful_acceptance(service, fake_model, source):
    project = service.projects.create(files={"app.py": "VALUE=1", "tests/test_skip.py": source})
    task = service.create_from_project(project["id"], BUG)
    runner = runner_for(service, task)
    result = runner.acceptance(service.store.source_files(task["id"]))
    assert not result["verified"] and result["tests_run"] == 0


def test_candidate_model_failure_returns_reviewable_error(service, monkeypatch):
    def broken_model(messages):
        raise RuntimeError("Sensitive upstream error")

    monkeypatch.setattr(
        projects_module, "create_model", lambda _: SimpleNamespace(invoke=broken_model)
    )
    project = service.projects.create(files={"app.py": "VALUE=1"})
    with pytest.raises(ValueError, match="provide reviewed tests manually") as error:
        service.projects.candidates(project["id"], BUG, EXPECTED)
    assert "Sensitive" not in str(error.value) and not service.store.tasks()


@pytest.mark.parametrize("path", ["tests/behavior_test.py", "pytest.ini", "conftest.py"])
def test_test_suffix_and_configuration_are_readonly(service, fake_model, path):
    contents = "VALUE=1\n" if path.endswith(".py") else "[pytest]\n"
    project = service.projects.create(files=demo_files() | {path: contents})
    task = service.create_from_project(project["id"], BUG)
    runner = runner_for(service, task)
    read = runner.execute("read", "inspect_file", {"path": path})
    with pytest.raises(ValueError, match="read-only"):
        runner.execute(
            "change",
            "replace_text",
            {
                "path": path,
                "expected_sha256": read["sha256"],
                "old": contents,
                "new": "# removed\n",
            },
        )
    (runner.workspace / path).write_text("# external change\n", encoding="utf-8")
    with pytest.raises(RecoveryConflict, match="tests changed"):
        runner.acceptance(service.store.source_files(task["id"]))


def test_no_tests_requires_expected_behavior_and_explicit_review(service, fake_model):
    project = service.projects.create(files={"calculator.py": demo_files()["calculator.py"]})
    assert project["needs_acceptance"]
    with pytest.raises(ValueError, match="explicitly confirm"):
        service.create_from_project(project["id"], BUG)
    candidate = service.projects.candidates(project["id"], BUG, EXPECTED, CANDIDATES)
    assert candidate["requires_confirmation"] and not service.store.tasks()
    with pytest.raises(ValueError, match="explicitly confirm"):
        service.create_from_project(
            project["id"], BUG, expected=EXPECTED, candidate_id=candidate["id"]
        )
    task = service.create_from_project(
        project["id"], BUG, expected=EXPECTED, candidate_id=candidate["id"], confirm_acceptance=True
    )
    final = service.run_sync(task["id"])
    assert final["status"] == "succeeded"
    assert final["acceptance"]["origin"] == "user_confirmed_candidates"
    assert final["acceptance"]["expected_behavior"] == EXPECTED
    assert (
        service.store.source_files(task["id"])["test_calculator.py"]
        == CANDIDATES["test_calculator.py"]
    )


@pytest.mark.parametrize("change", ["project", "prompt", "expected"])
def test_candidate_confirmation_cannot_be_reused_for_different_inputs(service, fake_model, change):
    files = {"calculator.py": demo_files()["calculator.py"]}
    first = service.projects.create(files=files)
    second = service.projects.create(files=files)
    candidate = service.projects.candidates(first["id"], BUG, EXPECTED, CANDIDATES)
    with pytest.raises(ValueError, match="stale"):
        service.create_from_project(
            second["id"] if change == "project" else first["id"],
            BUG + " changed" if change == "prompt" else BUG,
            expected=EXPECTED + " changed" if change == "expected" else EXPECTED,
            candidate_id=candidate["id"],
            confirm_acceptance=True,
        )
    assert not service.store.tasks()


def test_candidate_generation_is_preview_only_and_manual_revision_is_frozen(service, monkeypatch):
    inputs = []

    def propose(messages):
        inputs.append(messages)
        return SimpleNamespace(content=json.dumps(CANDIDATES))

    monkeypatch.setattr(projects_module, "create_model", lambda _: SimpleNamespace(invoke=propose))
    project = service.projects.create(files={"calculator.py": demo_files()["calculator.py"]})
    candidate = service.projects.candidates(project["id"], BUG, EXPECTED)
    assert inputs and EXPECTED in inputs[0][1][1]
    assert candidate["files"] == CANDIDATES and not service.store.tasks()
    revised = {
        "test_calculator.py": CANDIDATES["test_calculator.py"] + "    assert add(0, 0) == 0\n"
    }
    files, origin = service.projects.task_inputs(
        project["id"], BUG, EXPECTED, candidate["id"], True, revised
    )
    assert files["test_calculator.py"] == revised["test_calculator.py"]
    assert origin["origin"] == "user_confirmed_candidates"


@pytest.mark.parametrize(
    "tests",
    [
        {"calculator.py": "pass"},
        {"../test_x.py": "def test_x(): pass"},
        {"test_x.py": "not valid!"},
        {"test_x.py": "# no tests"},
        {".env/test_x.py": "def test_x(): pass"},
    ],
)
def test_invalid_candidates_do_not_create_task_or_overwrite_source(service, tests):
    project = service.projects.create(files={"calculator.py": "VALUE=1"})
    with pytest.raises(ValueError):
        service.projects.candidates(project["id"], BUG, EXPECTED, tests)
    assert service.projects.load(project["id"])["files"] == {"calculator.py": "VALUE=1"}
    assert not service.store.tasks()


def test_api_import_preview_no_tests_gate_and_confirmed_start(tmp_path, fake_model, monkeypatch):
    scheduled = []
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        project = client.post("/projects/import", json={"files": {"app.py": "VALUE=1"}})
        assert project.status_code == 201
        project_id = project.json()["id"]
        assert client.get(f"/projects/{project_id}").json()["needs_acceptance"]
        monkeypatch.setattr(
            service_module.TaskService, "schedule", lambda self, id: scheduled.append(id)
        )
        body = {"project_id": project_id, "prompt": BUG, "expected": EXPECTED}
        assert client.post("/tasks/from-project", json=body).status_code == 422
        candidate = client.post(
            f"/projects/{project_id}/candidate-tests",
            json={
                "prompt": BUG,
                "expected": EXPECTED,
                "files": CANDIDATES,
            },
        )
        assert candidate.status_code == 201 and scheduled == []
        body["candidate_id"] = candidate.json()["id"]
        assert client.post("/tasks/from-project", json=body).status_code == 422
        assert client.get("/tasks").json() == []
        body["confirm_acceptance"] = True
        task = client.post("/tasks/from-project", json=body)
        assert task.status_code == 202
        assert scheduled == [task.json()["id"]]
        assert task.json()["acceptance"]["origin"] == "user_confirmed_candidates"
        assert client.get("/projects/missing").status_code == 404
