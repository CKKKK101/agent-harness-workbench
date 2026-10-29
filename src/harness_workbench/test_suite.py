"""Run every original test file explicitly, including files in hidden directories."""

import importlib.util
import sys
import unittest
from pathlib import Path


def main():
    root = Path.cwd()
    sys.path.insert(0, str(root))
    suite = unittest.TestSuite()
    for index, target in enumerate(sys.argv[1:]):
        path = (root / target).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Test path escapes workspace")
        spec = importlib.util.spec_from_file_location(f"harness_test_{index}", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() and result.testsRun > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
