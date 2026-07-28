import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.app.models import CreateTaskRequest, Task, WorkflowResult
from backend.app.services.patch_generator import DeepSeekPatchGenerator, PatchGenerator
from backend.app.services.task_service import TaskNotFoundError, TaskService
from backend.app.services.workflow_service import WorkflowService


def allowed_origins() -> list[str]:
    configured_origins = os.getenv("ALLOWED_ORIGINS")
    if configured_origins:
        return [origin.strip() for origin in configured_origins.split(",") if origin.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://issue-patch-agent-web.onrender.com",
    ]


def build_patch_generator() -> PatchGenerator | None:
    if not os.getenv("DEEPSEEK_API_KEY"):
        return None
    return DeepSeekPatchGenerator.from_environment()


app = FastAPI(title="IssuePatch Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
task_service = TaskService()
workflow_service = WorkflowService(task_service, patch_generator=build_patch_generator())


@app.post("/tasks", status_code=201)
def create_task(request: CreateTaskRequest) -> Task:
    return task_service.create_task(**request.model_dump())


@app.post("/tasks/{task_id}/run")
def run_task(task_id: str, generate_patch: bool = False) -> WorkflowResult:
    try:
        return workflow_service.run(task_id, generate_patch=generate_patch)
    except TaskNotFoundError as error:
        raise HTTPException(status_code=404, detail="Task not found") from error


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
