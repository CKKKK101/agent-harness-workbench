from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .memory import MemoryConflict
from .service import TERMINAL, TaskBusy, TaskService


class TaskInput(BaseModel):
    prompt: str = Field(min_length=5, max_length=8000)
    files: dict[str, str] = Field(min_length=1, max_length=30)
    model_mode: Literal["demo", "openai"] | None = None
    memory_scope: str | None = Field(default=None, min_length=1, max_length=80)


class DemoInput(BaseModel):
    memory_scope: str | None = Field(default=None, min_length=1, max_length=80)


class ProjectInput(BaseModel):
    files: dict[str, str] | None = Field(default=None, max_length=5000)
    github_url: str | None = Field(default=None, max_length=300)
    label: str = Field(default="Local project", max_length=200)


class CandidateInput(BaseModel):
    prompt: str = Field(min_length=5, max_length=8000)
    expected: str = Field(min_length=5, max_length=8000)
    files: dict[str, str] | None = Field(default=None, max_length=10)


class ProjectTaskInput(BaseModel):
    project_id: str
    prompt: str = Field(min_length=5, max_length=8000)
    expected: str = Field(default="", max_length=8000)
    candidate_id: str | None = None
    candidate_files: dict[str, str] | None = Field(default=None, max_length=10)
    confirm_acceptance: bool = False
    memory_scope: str | None = Field(default=None, min_length=1, max_length=80)


class MemoryInput(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=2000)
    kind: Literal["constraint", "fact", "experience"] = "fact"
    expected_version: int | None = Field(default=None, ge=1)
    source_task: str | None = None
    evidence: dict[str, str] = Field(default_factory=dict, max_length=30)
    expires_in_seconds: int | None = Field(default=None, ge=1, le=31_536_000)


class RetireMemoryInput(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)


class RecallInput(BaseModel):
    task_id: str


class ResumeInput(BaseModel):
    retry_uncertain_tests: bool = False


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = TaskService(settings)
        yield
        app.state.service.close()

    app = FastAPI(
        title="Deep Agents Workbench",
        version="0.1.0",
        lifespan=lifespan,
        description=(
            "Local coding-agent task service. Demo uses a deterministic fixture model, "
            "not an LLM. Run only trusted test code; workspace paths are not an OS sandbox."
        ),
    )
    static_dir = Path(__file__).parent / "static"
    app.mount("/assets", StaticFiles(directory=static_dir), name="assets")

    def svc(request: Request) -> TaskService:
        return request.app.state.service

    def ensure_task(service: TaskService, task_id: str):
        try:
            return service.get(task_id)
        except KeyError as exc:
            raise HTTPException(404, "Task not found") from exc

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/health")
    def health():
        configured = bool(os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL"))
        return {
            "status": "ok",
            "model_mode": settings.model_mode,
            "upstream": "deepagents==0.7.32",
            "model_configured": configured,
            "model_name": os.getenv("OPENAI_MODEL") if configured else None,
            "context_enabled": settings.context_enabled,
        }

    @app.get("/tasks")
    def list_tasks(request: Request):
        service = svc(request)
        return [service.get(t["id"]) for t in service.store.tasks()]

    @app.post("/projects/import", status_code=201)
    def import_project(body: ProjectInput, request: Request):
        try:
            return svc(request).projects.create(**body.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/projects/{project_id}")
    def get_project(project_id: str, request: Request):
        try:
            return svc(request).projects.preview(project_id)
        except KeyError as exc:
            raise HTTPException(404, "Project import not found") from exc

    @app.post("/projects/{project_id}/candidate-tests", status_code=201)
    def propose_tests(project_id: str, body: CandidateInput, request: Request):
        try:
            return svc(request).projects.candidates(project_id, **body.model_dump())
        except KeyError as exc:
            raise HTTPException(404, "Project import not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/tasks/from-project", status_code=202)
    def create_project_task(body: ProjectTaskInput, request: Request):
        service = svc(request)
        try:
            task = service.create_from_project(**body.model_dump())
            service.schedule(task["id"])
            return service.get(task["id"])
        except KeyError as exc:
            raise HTTPException(404, "Project import not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/tasks/demo", status_code=202)
    def create_demo(request: Request, body: DemoInput | None = None):
        service = svc(request)
        try:
            task = service.create_demo(memory_scope=body.memory_scope if body else None)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        service.schedule(task["id"])
        return service.get(task["id"])

    @app.post("/tasks", status_code=202)
    def create_task(body: TaskInput, request: Request):
        service = svc(request)
        try:
            task = service.create_task(
                body.prompt, body.files, mode=body.model_mode, memory_scope=body.memory_scope
            )
            service.schedule(task["id"])
            return service.get(task["id"])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str, request: Request):
        return ensure_task(svc(request), task_id)

    @app.get("/tasks/{task_id}/context")
    def get_context(task_id: str, request: Request):
        service = svc(request)
        ensure_task(service, task_id)
        return service.context_views(task_id)

    def memory_error(exc):
        code = 409 if isinstance(exc, MemoryConflict) else 404 if isinstance(exc, KeyError) else 422
        return HTTPException(code, str(exc))

    @app.get("/memory/{scope}")
    def list_memory(scope: str, request: Request, history: bool = False):
        try:
            return svc(request).memory.list(scope, history=history)
        except ValueError as exc:
            raise memory_error(exc) from exc

    @app.put("/memory/{scope}")
    def write_memory(scope: str, body: MemoryInput, request: Request):
        try:
            return svc(request).memory.put(scope, **body.model_dump())
        except (ValueError, KeyError) as exc:
            raise memory_error(exc) from exc

    @app.post("/memory/{scope}/invalidate")
    def invalidate_memory(scope: str, body: RetireMemoryInput, request: Request):
        try:
            return svc(request).memory.retire(scope, **body.model_dump())
        except (ValueError, KeyError) as exc:
            raise memory_error(exc) from exc

    @app.delete("/memory/{scope}/{key:path}")
    def delete_memory(scope: str, key: str, request: Request, expected_version: int = Query(ge=1)):
        try:
            return svc(request).memory.retire(
                scope, key, expected_version=expected_version, delete=True
            )
        except (ValueError, KeyError) as exc:
            raise memory_error(exc) from exc

    @app.post("/memory/{scope}/recall")
    def recall_memory(scope: str, body: RecallInput, request: Request):
        service = svc(request)
        ensure_task(service, body.task_id)
        task = service.store.task(body.task_id)
        if task["memory_scope"] != scope:
            raise HTTPException(409, "Task belongs to another memory scope")
        return service.memory.recall(scope, task["prompt"], Path(task["workspace"]))

    @app.post("/tasks/{task_id}/resume", status_code=202)
    def resume(task_id: str, body: ResumeInput, request: Request):
        service = svc(request)
        ensure_task(service, task_id)
        try:
            service.schedule(task_id, retry_uncertain_tests=body.retry_uncertain_tests)
        except (ValueError, TaskBusy) as exc:
            raise HTTPException(409, str(exc)) from exc
        return service.get(task_id)

    @app.get("/tasks/{task_id}/files")
    def get_files(task_id: str, request: Request):
        service = svc(request)
        ensure_task(service, task_id)
        return service.files(task_id)

    @app.get("/tasks/{task_id}/diff")
    def get_diff(task_id: str, request: Request):
        service = svc(request)
        ensure_task(service, task_id)
        return service.diff(task_id)

    @app.get("/tasks/{task_id}/events")
    def get_events(task_id: str, request: Request, after: int = Query(0, ge=0)):
        service = svc(request)
        ensure_task(service, task_id)
        return service.store.events(task_id, after)

    @app.get("/tasks/{task_id}/stream")
    async def stream(task_id: str, request: Request, after: int = Query(0, ge=0)):
        service = svc(request)
        ensure_task(service, task_id)
        last_header = request.headers.get("last-event-id", "0")
        if not last_header.isdigit():
            raise HTTPException(400, "Last-Event-ID must be a nonnegative integer")
        cursor = max(after, int(last_header))

        async def generate():
            nonlocal cursor
            while not await request.is_disconnected():
                events = service.store.events(task_id, cursor)
                for event in events:
                    cursor = event["id"]
                    data = json.dumps(event, ensure_ascii=False)
                    yield f"id: {cursor}\nevent: {event['kind']}\ndata: {data}\n\n"
                if len(events) < 500 and service.get(task_id)["status"] in TERMINAL:
                    return
                yield ": keepalive\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app
