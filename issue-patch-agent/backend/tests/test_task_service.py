from backend.app.models import TaskStatus
from backend.app.services.task_service import TaskService


def test_task_service_moves_a_task_through_the_week_one_workflow() -> None:
    service = TaskService()
    task = service.create_task(
        repository_path="/tmp/example-repo",
        issue="修复登录失败时显示空白页的问题",
        test_command="pytest -q",
    )

    for status in (
        TaskStatus.ANALYZING,
        TaskStatus.RETRIEVING,
        TaskStatus.PLANNING,
        TaskStatus.PATCHING,
        TaskStatus.TESTING,
        TaskStatus.REPORTING,
        TaskStatus.COMPLETED,
    ):
        task = service.update_status(task.id, status)

    assert task.status is TaskStatus.COMPLETED
    assert service.get_task(task.id) == task
