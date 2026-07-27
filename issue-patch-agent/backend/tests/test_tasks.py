from fastapi.testclient import TestClient

from backend.app.main import app


def test_create_task_returns_a_queued_task() -> None:
    client = TestClient(app)

    response = client.post(
        "/tasks",
        json={
            "repository_path": "/tmp/example-repo",
            "issue": "修复登录失败时显示空白页的问题",
            "test_command": "pytest -q",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "queued"
    assert isinstance(body["id"], str)
    assert body["id"] != ""


def test_create_task_requires_all_agent_inputs() -> None:
    client = TestClient(app)

    response = client.post("/tasks", json={"issue": "修复登录失败"})

    assert response.status_code == 422


def test_local_frontend_origin_is_allowed_to_create_tasks() -> None:
    response = TestClient(app).options(
        "/tasks",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
