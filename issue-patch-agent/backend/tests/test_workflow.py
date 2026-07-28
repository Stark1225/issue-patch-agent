import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.task_service import TaskService
from backend.app.services.workflow_service import WorkflowService


def create_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "workflow-repository"
    repository.mkdir()
    subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
    (repository / "health.py").write_text("def health():\n    return 'ok'\n")
    (repository / "test_health.py").write_text("from health import health\n\ndef test_health():\n    assert health() == 'ok'\n")
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=IssuePatch Test",
            "-c",
            "user.email=issuepatch@example.com",
            "commit",
            "-m",
            "initial commit",
        ],
        check=True,
        capture_output=True,
    )
    return repository


def test_run_task_returns_a_plan_and_test_report_without_changing_source(tmp_path: Path) -> None:
    repository = create_repository(tmp_path)
    client = TestClient(app)
    create_response = client.post(
        "/tasks",
        json={
            "repository_path": str(repository),
            "issue": "Inspect the health function and verify its test",
            "test_command": "pytest -q",
        },
    )

    response = client.post(f"/tasks/{create_response.json()['id']}/run")

    assert response.status_code == 200
    body = response.json()
    assert body["task"]["status"] == "completed"
    assert body["plan"]["steps"]
    assert any(call["tool_name"] == "search" for call in body["tool_calls"])
    assert any(call["tool_name"] == "read_file" for call in body["tool_calls"])
    assert body["patch_result"]["diff"] == ""
    assert body["patch_result"]["tests_passed"] is True
    assert "return 'ok'" in (repository / "health.py").read_text()


def test_run_task_returns_not_found_for_an_unknown_task() -> None:
    response = TestClient(app).post("/tasks/not-a-task/run")

    assert response.status_code == 404


def test_run_task_marks_a_failed_test_run_as_failed(tmp_path: Path) -> None:
    repository = create_repository(tmp_path)
    client = TestClient(app)
    create_response = client.post(
        "/tasks",
        json={
            "repository_path": str(repository),
            "issue": "Inspect the health function",
            "test_command": "pytest -q missing_test.py",
        },
    )

    response = client.post(f"/tasks/{create_response.json()['id']}/run")

    assert response.status_code == 200
    assert response.json()["task"]["status"] == "failed"
    assert response.json()["patch_result"]["tests_passed"] is False


class FakeRepositoryCloner:
    def __init__(self, repository: Path) -> None:
        self.repository = repository
        self.cloned_urls: list[str] = []
        self.cleaned_repositories: list[Path] = []

    def clone(self, repository_url: str) -> Path:
        self.cloned_urls.append(repository_url)
        return self.repository

    def cleanup(self, repository: Path) -> None:
        self.cleaned_repositories.append(repository)


def test_run_task_clones_a_github_repository_before_creating_a_worktree(tmp_path: Path) -> None:
    repository = create_repository(tmp_path)
    cloner = FakeRepositoryCloner(repository)
    task_service = TaskService()
    task = task_service.create_task(
        repository_url="https://github.com/owner/repository",
        issue="Inspect the health function and verify its test",
        test_command="pytest -q",
    )

    result = WorkflowService(task_service, repository_cloner=cloner).run(task.id)

    assert result.task.status == "completed"
    assert cloner.cloned_urls == ["https://github.com/owner/repository"]
    assert cloner.cleaned_repositories == [repository]
    assert result.tool_calls[0].tool_name == "clone_repository"
