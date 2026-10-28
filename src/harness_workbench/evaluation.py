"""Real subprocess crashes; deterministic graph inputs. Not an LLM performance benchmark."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from .config import Settings
from .fixtures import demo_files
from .service import TaskService


def evaluate(data_dir: Path) -> dict:
    run_dir = data_dir / "evaluations" / str(time.time_ns())
    service = TaskService(Settings(data_dir=run_dir))
    results = []
    try:
        for fault in [None, "after_prepare", "after_effect", "after_journal", "after_graph"]:
            task = service.create_demo(fault=fault)
            command = [
                sys.executable,
                "-m",
                "harness_workbench.cli",
                "--data-dir",
                str(run_dir),
                "_worker",
                task["id"],
            ]
            started = time.perf_counter()
            first = subprocess.run(
                command + (["--hard-crash"] if fault else []),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
            expected_exit = 86 if fault else 0
            if first.returncode != expected_exit:
                raise AssertionError(f"Unexpected worker exit {first.returncode}: {first.stderr}")
            if fault:
                second = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=120,
                )
                if second.returncode:
                    raise AssertionError(f"Recovery failed: {second.stderr}")
            final = service.get(task["id"])
            files = service.files(task["id"])
            unchanged_tests = files["test_calculator.py"] == demo_files()["test_calculator.py"]
            passed = (
                final["status"] == "succeeded"
                and unchanged_tests
                and "return a + b" in files["calculator.py"]
                and final["metrics"]["file_write_attempts"] == 1
            )
            results.append(
                {
                    "fault": fault or "none",
                    "passed": passed,
                    "worker_exit": first.returncode,
                    "status": final["status"],
                    "attempts": final["attempts"],
                    "tests_unchanged": unchanged_tests,
                    **final["metrics"],
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                }
            )
    finally:
        service.close()
    report = {
        "upstream": "deepagents==0.7.32",
        "model": "deterministic_fixture",
        "scope": "engineering recovery only; no general coding or LLM-quality claim",
        "passed": sum(row["passed"] for row in results),
        "total": len(results),
        "cases": results,
    }
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    (output / "recovery-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if report["passed"] != report["total"]:
        raise AssertionError(json.dumps(report, indent=2))
    return report
