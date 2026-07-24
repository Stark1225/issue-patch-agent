from fastapi import FastAPI

from backend.app.models import CreateTaskRequest, Task
from backend.app.services.task_service import TaskService

app = FastAPI(title="IssuePatch Agent")
task_service = TaskService()


@app.post("/tasks", status_code=201)
def create_task(request: CreateTaskRequest) -> Task:
    return task_service.create_task(**request.model_dump())


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
