import subprocess
from pathlib import Path

import pytest

from backend.app.services.patch_generator import (
    DeepSeekPatchGenerator,
    DiffNormalizer,
    DiffValidationError,
    DiffValidator,
)
from backend.app.services.task_service import TaskService
from backend.app.services.workflow_service import WorkflowService


class FakePatchGenerator:
    def generate(self, *, issue: str, plan_steps: list[str], files: dict[str, str]) -> str:
        return """diff --git a/health.py b/health.py
--- a/health.py
+++ b/health.py
@@ -1,2 +1,2 @@
 def health():
-    return 'ok'
+    return 'ready'
diff --git a/test_health.py b/test_health.py
--- a/test_health.py
+++ b/test_health.py
@@ -1,4 +1,4 @@
 from health import health

 def test_health():
-    assert health() == 'ok'
+    assert health() == 'ready'
"""


class RepairingPatchGenerator(FakePatchGenerator):
    def generate(self, *, issue: str, plan_steps: list[str], files: dict[str, str]) -> str:
        return "diff --git a/other.py b/other.py\n--- a/other.py\n+++ b/other.py\n"

    def repair(
        self,
        *,
        issue: str,
        plan_steps: list[str],
        files: dict[str, str],
        rejected_diff: str,
        error: str,
    ) -> str:
        return super().generate(issue=issue, plan_steps=plan_steps, files=files)


def create_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "patch-repository"
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


class FakeCompletions:
    def __init__(self) -> None:
        self.request: dict[str, str] | None = None

    def create(self, *, model: str, messages: list[dict[str, str]], stream: bool):
        self.request = {"model": model, "input": messages[-1]["content"]}
        message = type("Message", (), {"content": "```diff\ndiff --git a/app.py b/app.py\n```"})()
        return type("Response", (), {"choices": [type("Choice", (), {"message": message})()]})()


class FakeChat:
    def __init__(self) -> None:
        self.completions = FakeCompletions()


class FakeDeepSeekClient:
    def __init__(self) -> None:
        self.chat = FakeChat()


def test_deepseek_patch_generator_uses_chat_api_and_removes_a_code_fence() -> None:
    client = FakeDeepSeekClient()
    generator = DeepSeekPatchGenerator(model="configured-model", client=client)

    diff = generator.generate(
        issue="Fix the health response",
        plan_steps=["Inspect health.py"],
        files={"health.py": "def health(): return 'ok'"},
    )

    assert diff == "diff --git a/app.py b/app.py"
    assert client.chat.completions.request is not None
    assert client.chat.completions.request["model"] == "configured-model"
    assert "health.py" in client.chat.completions.request["input"]


def test_workflow_applies_a_generated_diff_only_in_its_temporary_worktree(tmp_path: Path) -> None:
    repository = create_repository(tmp_path)
    task_service = TaskService()
    task = task_service.create_task(
        repository_path=str(repository),
        issue="Change health response to ready",
        test_command="pytest -q",
    )

    result = WorkflowService(task_service, patch_generator=FakePatchGenerator()).run(
        task.id, generate_patch=True
    )

    assert result.task.status == "completed"
    assert result.patch_result.diff.startswith("diff --git")
    assert result.patch_result.applied_to_worktree is True
    assert result.patch_result.tests_passed is True
    assert "return 'ok'" in (repository / "health.py").read_text()


def test_workflow_repairs_one_rejected_model_diff(tmp_path: Path) -> None:
    repository = create_repository(tmp_path)
    task_service = TaskService()
    task = task_service.create_task(
        repository_path=str(repository),
        issue="Change health response to ready",
        test_command="pytest -q",
    )

    result = WorkflowService(task_service, patch_generator=RepairingPatchGenerator()).run(
        task.id, generate_patch=True
    )

    assert result.task.status == "completed"
    assert any(call.tool_name == "repair_patch" for call in result.tool_calls)


def test_diff_validator_rejects_a_path_outside_the_worktree() -> None:
    unsafe_diff = """diff --git a/../../outside.py b/../../outside.py
--- a/../../outside.py
+++ b/../../outside.py
@@ -0,0 +1 @@
+unsafe
"""

    with pytest.raises(DiffValidationError, match="outside"):
        DiffValidator().validate(unsafe_diff)


def test_diff_normalizer_maps_a_unique_relative_path_and_corrects_hunk_counts() -> None:
    diff = """diff --git a/backend/app/main.py b/backend/app/main.py
--- a/backend/app/main.py
+++ b/backend/app/main.py
@@ -1,9 +1,99 @@
 def health():
+    \"\"\"Report whether the service is available.\"\"\"
     return {\"status\": \"ok\"}
"""

    normalized = DiffNormalizer().normalize(
        diff, allowed_paths={"issue-patch-agent/backend/app/main.py"}
    )

    assert "a/issue-patch-agent/backend/app/main.py" in normalized
    assert "@@ -1,2 +1,3 @@" in normalized
