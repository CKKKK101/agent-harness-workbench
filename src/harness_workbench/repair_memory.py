"""Derive factual repair cards from original/final files and Harness evidence.

No LLM is asked to invent a root cause. Changed code describes an observed remedy,
not proof that the same remedy is valid in a different task.
"""

from __future__ import annotations

import ast
import difflib
import json
import re

from .store import encode
from .tools import digest, read_bytes, safe_path, workspace_digest


def redact(text):
    text = re.sub(
        r"(?i)(api[_-]?key|password|secret|token)\s*[=:]\s*[^\s,;]+", r"\1=[REDACTED]", text
    )
    return re.sub(r"\b(?:sk-[\w-]{16,}|gh[pousr]_[A-Za-z0-9]{20,})", "[REDACTED]", text)


def symbols(text):
    try:
        return sorted(
            {
                n.name
                for n in ast.walk(ast.parse(text))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            }
        )[:20]
    except SyntaxError:
        return []


def make_card(store, task, workspace, paths):
    rows = [
        r
        for r in store.tools(task["id"])
        if r["name"] == "harness_acceptance" and r["state"] == "succeeded"
    ]
    evidence = json.loads(rows[-1]["result"]) if rows else {}
    if (
        not evidence.get("verified")
        or evidence.get("tests_run", 0) < 1
        or evidence.get("fingerprint") != workspace_digest(workspace)
    ):
        raise ValueError("Experience requires fresh independent Harness acceptance evidence")
    original = store.source_files(task["id"])
    changes = []
    hashes = {}
    for path in paths:
        before = original[path]
        after_bytes = read_bytes(safe_path(workspace, path))
        after = after_bytes.decode("utf-8")
        if before == after:
            continue
        delta = list(difflib.unified_diff(before.splitlines(), after.splitlines(), n=0))
        removed = "\n".join(
            line[1:] for line in delta if line.startswith("-") and not line.startswith("---")
        )
        added = "\n".join(
            line[1:] for line in delta if line.startswith("+") and not line.startswith("+++")
        )
        changes.append(
            {
                "path": path,
                "before_sha256": digest(before.encode()),
                "after_sha256": digest(after_bytes),
                "symbols": symbols(after),
                "removed": redact(removed)[:240],
                "added": redact(added)[:240],
            }
        )
        hashes[path] = digest(after_bytes)
    if not changes:
        return None
    # Prompt is the requested behavior, not an inferred diagnosis.
    problem = redact(task["prompt"].split("\nWorkspace files:")[0])[:600]
    remedy = "; ".join(
        c["path"] + ": " + c["removed"][:70] + " → " + c["added"][:70] for c in changes[:3]
    )
    details = {
        "schema": 1,
        "record_type": "verified_repair",
        "problem": problem,
        "observed_remedy": remedy,
        "root_cause": "not_inferred",
        "changes": changes,
        "applicability": {
            "scope": task["memory_scope"],
            "language": "Python",
            "policy": "reference_only; inspect current code and rerun acceptance",
        },
        "verification": {
            "source_task": task["id"],
            "tests_run": evidence["tests_run"],
            "targets": evidence["targets"],
            "fingerprint": evidence["fingerprint"],
            "acceptance_origin": (store.acceptance(task["id"]) or {}).get(
                "origin", "uploaded_tests"
            ),
        },
    }
    signature = digest(encode({"problem": problem, "changes": changes}).encode())
    details["signature"] = signature
    content = (
        "问题 / Requested behavior: " + problem[:180] + "\n"
        "历史修改 / Observed remedy: " + remedy[:300] + "\n"
        f"验证 / Verification: Harness {evidence['tests_run']} tests passed. "
        "仅作经验参考；先读取当前代码，再独立验收；未自动推断根因。"
    )
    return content, hashes, details
