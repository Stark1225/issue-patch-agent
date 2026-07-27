from fastapi import FastAPI, HTTPException

from backend.app.models import CreateTaskRequest, Task, WorkflowResult
from backend.app.services.task_service import TaskNotFoundError, TaskService
from backend.app.services.workflow_service import WorkflowService

app = FastAPI(title="IssuePatch Agent")
task_service = TaskService()
workflow_service = WorkflowService(task_service)


@app.post("/tasks", status_code=201)
def create_task(request: CreateTaskRequest) -> Task:
    return task_service.create_task(**request.model_dump())


@app.post("/tasks/{task_id}/run")
def run_task(task_id: str) -> WorkflowResult:
    try:
        return workflow_service.run(task_id)
    except TaskNotFoundError as error:
        raise HTTPException(status_code=404, detail="Task not found") from error


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
