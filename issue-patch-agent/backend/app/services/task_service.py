from backend.app.models import Task, TaskStatus, utc_now


class TaskNotFoundError(KeyError):
    """Raised when a task identifier is absent from the in-memory store."""


class TaskService:
    """In-memory task store used by the first-week project skeleton."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def create_task(
        self,
        *,
        repository_path: str,
        issue: str,
        test_command: str,
    ) -> Task:
        task = Task(
            repository_path=repository_path,
            issue=issue,
            test_command=test_command,
        )
        self._tasks[task.id] = task
        return task

    def get_task(self, task_id: str) -> Task:
        try:
            return self._tasks[task_id]
        except KeyError as error:
            raise TaskNotFoundError(task_id) from error

    def update_status(self, task_id: str, status: TaskStatus) -> Task:
        task = self.get_task(task_id)
        task.status = status
        task.updated_at = utc_now()
        return task
