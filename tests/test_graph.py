import pytest

from harness_workbench.reproduce import reproduce_upstream
from harness_workbench.service import TaskBusy, TaskService


def test_unmodified_upstream_tool_loop():
    assert reproduce_upstream()["passed"]


def test_complete_graph_repairs_and_verifies_fixture(service):
    task = service.create_demo()
    result = service.run_sync(task["id"])
    assert result["status"] == "succeeded"
    assert result["metrics"]["file_write_attempts"] == 1
    assert result["metrics"]["tool_calls"] == 4  # Three agent tools + Harness acceptance.


@pytest.mark.parametrize("fault", ["after_prepare", "after_effect", "after_journal", "after_graph"])
def test_checkpoint_resume_with_new_service_instance(service, fault):
    task = service.create_demo(fault=fault)
    first = service.run_sync(task["id"])
    assert first["status"] == "interrupted"
    restarted = TaskService(service.settings)
    try:
        final = restarted.run_sync(task["id"])
        assert final["status"] == "succeeded"
        assert final["attempts"] == 2
        assert final["metrics"]["file_write_attempts"] == 1
    finally:
        restarted.close()


def test_running_task_cannot_be_stolen(service):
    task = service.create_demo()
    with service._lock(task["id"]).acquire(timeout=0):
        other = TaskService(service.settings)
        try:
            with pytest.raises(TaskBusy):
                other.schedule(task["id"])
        finally:
            other.close()


def test_graph_blocks_unknown_test_outcome_until_retry_authorized(service):
    task = service.create_demo(fault="after_test_started")
    assert service.run_sync(task["id"])["status"] == "interrupted"
    assert service.run_sync(task["id"])["status"] == "blocked"
    final = service.run_sync(task["id"], retry_uncertain_tests=True)
    assert final["status"] == "succeeded"
    assert final["metrics"]["file_write_attempts"] == 1
