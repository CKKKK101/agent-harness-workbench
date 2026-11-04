"""Run every original test file explicitly, including files in hidden directories."""

import importlib.util
import sys
import unittest
from pathlib import Path


def main():
    root = Path.cwd()
    sys.path.insert(0, str(root))
    if (root / "src").is_dir():
        sys.path.insert(0, str(root / "src"))
    targets = sys.argv[1:]
    engine = targets.pop(0) if targets and targets[0].startswith("--") else "--unittest"
    if engine == "--pytest":
        import pytest

        class CountTests:
            def __init__(self):
                self.count = 0

            def pytest_runtest_logreport(self, report):
                if report.when == "call" and not report.skipped:
                    self.count += 1

        counter = CountTests()
        # Ignore user addopts (e.g. --lf/-k) so final acceptance cannot silently select a subset.
        result = pytest.main(
            [
                "-q",
                "-o",
                "addopts=",
                "-o",
                "cache_dir=" + str(root / ".pytest_cache"),
                "-o",
                "python_files=test_*.py *_test.py",
                "--import-mode=importlib",
                *targets,
            ],
            plugins=[counter],
        )
        print(f"HARNESS_TEST_COUNT={counter.count}", flush=True)
        return 0 if result == 0 and counter.count > 0 else 1
    suite = unittest.TestSuite()
    for index, target in enumerate(targets):
        path = (root / target).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Test path escapes workspace")
        spec = importlib.util.spec_from_file_location(f"harness_test_{index}", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    count = result.testsRun - len(result.skipped)
    print(f"HARNESS_TEST_COUNT={count}", flush=True)
    return 0 if result.wasSuccessful() and count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
