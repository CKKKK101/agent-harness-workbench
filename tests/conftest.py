import pytest

from harness_workbench.config import Settings
from harness_workbench.service import TaskService


@pytest.fixture
def service(tmp_path):
    instance = TaskService(Settings(data_dir=tmp_path / "runtime"))
    yield instance
    instance.close()
