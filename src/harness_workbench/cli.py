from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Settings
from .service import TaskService

FAULT_POINTS = [
    "after_prepare",
    "after_effect",
    "after_journal",
    "after_graph",
    "after_test_started",
]


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Deep Agents Workbench")
    parser.add_argument("--data-dir", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "reproduce", help="Exercise the unmodified upstream graph, without API keys"
    )
    demo = commands.add_parser("demo", help="Run the deterministic repair fixture")
    demo.add_argument("--fault", choices=FAULT_POINTS)
    resume = commands.add_parser("resume", help="Resume an interrupted or blocked task")
    resume.add_argument("task_id")
    resume.add_argument("--retry-uncertain-tests", action="store_true")
    status = commands.add_parser("status")
    status.add_argument("task_id")
    run = commands.add_parser("run", help="Run trusted source files with a real model")
    run.add_argument("--workspace", type=Path, required=True)
    run.add_argument("--prompt", required=True)
    commands.add_parser("evaluate", help="Kill worker subprocesses at 4 boundaries and resume")
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8000)
    worker = commands.add_parser("_worker", help=argparse.SUPPRESS)
    worker.add_argument("task_id")
    worker.add_argument("--hard-crash", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.data_dir:
        settings = Settings(
            data_dir=args.data_dir.resolve(),
            model_mode=settings.model_mode,
            max_workers=settings.max_workers,
            test_timeout=settings.test_timeout,
        )
    if args.command == "reproduce":
        from .reproduce import reproduce_upstream

        emit(reproduce_upstream())
        return
    if args.command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port)
        return
    if args.command == "evaluate":
        from .evaluation import evaluate

        emit(evaluate(settings.data_dir))
        return
    service = TaskService(settings)
    try:
        if args.command == "demo":
            task = service.create_demo(fault=args.fault)
            emit(service.run_sync(task["id"]))
        elif args.command == "resume":
            if service.get(args.task_id)["status"] in {"succeeded", "failed"}:
                parser.error("Task already finished; create a new task")
            emit(service.run_sync(args.task_id, retry_uncertain_tests=args.retry_uncertain_tests))
        elif args.command == "status":
            emit(service.get(args.task_id))
        elif args.command == "_worker":
            emit(service.run_sync(args.task_id, hard_crash=args.hard_crash))
        elif args.command == "run":
            root = args.workspace.resolve()
            if not root.is_dir():
                parser.error("--workspace must be a directory")
            files = {}
            for path in root.rglob("*.py"):
                if any(
                    p.startswith(".") or p == "__pycache__" for p in path.relative_to(root).parts
                ):
                    continue
                if path.is_symlink():
                    parser.error("Workspace symlinks are not supported")
                files[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
            task = service.create_task(args.prompt, files, mode="openai")
            emit(service.run_sync(task["id"]))
    finally:
        service.close()


if __name__ == "__main__":
    main()
