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
from .service import TERMINAL, TaskBusy, TaskService


class TaskInput(BaseModel):
    prompt: str = Field(min_length=5, max_length=8000)
    files: dict[str, str] = Field(min_length=1, max_length=30)
    model_mode: Literal["demo", "openai"] | None = None


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
        }

    @app.get("/tasks")
    def list_tasks(request: Request):
        service = svc(request)
        return [service.get(t["id"]) for t in service.store.tasks()]

    @app.post("/tasks/demo", status_code=202)
    def create_demo(request: Request):
        service = svc(request)
        task = service.create_demo()
        service.schedule(task["id"])
        return service.get(task["id"])

    @app.post("/tasks", status_code=202)
    def create_task(body: TaskInput, request: Request):
        service = svc(request)
        try:
            task = service.create_task(body.prompt, body.files, mode=body.model_mode)
            service.schedule(task["id"])
            return service.get(task["id"])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str, request: Request):
        return ensure_task(svc(request), task_id)

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
