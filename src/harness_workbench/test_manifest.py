"""Static discovery: importing a project must never import or execute its Python code."""

import ast
from pathlib import PurePosixPath

TEST_CONFIG = {"conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"}


def is_test(path: str) -> bool:
    name = PurePosixPath(path).name
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def manifest(files: dict[str, str]) -> list[str]:
    return sorted(path for path in files if is_test(path))


def framework(files: dict[str, str]) -> str:
    for path in manifest(files):
        try:
            tree = ast.parse(files[path])
        except SyntaxError:
            # Let the final suite report the actual collection error.
            return "pytest"
        if any(
            isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
            for n in tree.body
        ):
            return "pytest"
        if any(
            isinstance(n, ast.Import)
            and any(a.name == "pytest" for a in n.names)
            or isinstance(n, ast.ImportFrom)
            and n.module == "pytest"
            for n in ast.walk(tree)
        ):
            return "pytest"
    return "pytest" if any(PurePosixPath(p).name == "conftest.py" for p in files) else "unittest"


def protected(path: str) -> bool:
    return is_test(path) or PurePosixPath(path).name in TEST_CONFIG
