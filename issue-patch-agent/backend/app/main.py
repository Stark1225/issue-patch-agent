import os

from fastapi import FastAPI, HTTPException

from backend.app.models import CreateTaskRequest, Task, WorkflowResult
from backend.app.services.patch_generator import OpenAIPatchGenerator, PatchGenerator
from backend.app.services.task_service import TaskNotFoundError, TaskService
from backend.app.services.workflow_service import WorkflowService


def build_patch_generator() -> PatchGenerator | None:
    if not os.getenv("OPENAI_MODEL"):
        return None
    return OpenAIPatchGenerator.from_environment()


app = FastAPI(title="IssuePatch Agent")
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
