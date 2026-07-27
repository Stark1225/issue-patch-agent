import re
from pathlib import Path

from backend.app.models import PatchResult, Plan, Task, TaskStatus, ToolCall, WorkflowResult
from backend.app.services.task_service import TaskService
from backend.app.tools.repository import RepositoryTools, WorktreeManager
from backend.app.tools.runner import TestRunner


class DeterministicPlanner:
    """Produces a transparent planning baseline until a model provider is configured."""

    def search_terms(self, issue: str) -> list[str]:
        terms = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", issue)
        return list(dict.fromkeys(terms))[:3] or [issue]

    def create_plan(self, task: Task, relevant_files: list[str]) -> Plan:
        file_summary = ", ".join(relevant_files) if relevant_files else "the repository test suite"
        return Plan(
            task_id=task.id,
            steps=[
                f"Review the issue: {task.issue}",
                f"Inspect relevant code and tests: {file_summary}",
                "Prepare a patch for human approval before applying it.",
                f"Run the allowed verification command: {task.test_command}",
            ],
        )


class WorkflowService:
    """Runs the inspect-plan-test workflow while preserving the source checkout."""

    def __init__(self, task_service: TaskService) -> None:
        self.task_service = task_service
        self.planner = DeterministicPlanner()

    def run(self, task_id: str) -> WorkflowResult:
        task = self.task_service.get_task(task_id)
        calls: list[ToolCall] = []
        plan = Plan(task_id=task.id, steps=[])
        patch_result = PatchResult(task_id=task.id, diff="", tests_passed=None)
        manager = WorktreeManager()
        worktree: Path | None = None

        try:
            self.task_service.update_status(task.id, TaskStatus.ANALYZING)
            worktree = manager.create(Path(task.repository_path))
            calls.append(
                ToolCall(
                    task_id=task.id,
                    tool_name="create_worktree",
                    arguments={"repository_path": task.repository_path},
                    result="Created an isolated worktree.",
                )
            )
            tools = RepositoryTools(worktree)

            self.task_service.update_status(task.id, TaskStatus.RETRIEVING)
            relevant_files: list[str] = []
            for term in self.planner.search_terms(task.issue):
                matches = tools.search(term)
                relevant_files.extend(match for match in matches if match not in relevant_files)
                calls.append(
                    ToolCall(
                        task_id=task.id,
                        tool_name="search",
                        arguments={"query": term},
                        result=", ".join(matches) or "No matching files.",
                    )
                )
            for relative_path in relevant_files[:3]:
                contents = tools.read_text(relative_path)
                calls.append(
                    ToolCall(
                        task_id=task.id,
                        tool_name="read_file",
                        arguments={"path": relative_path},
                        result=contents[:2_000],
                    )
                )

            self.task_service.update_status(task.id, TaskStatus.PLANNING)
            plan = self.planner.create_plan(task, relevant_files)

            self.task_service.update_status(task.id, TaskStatus.PATCHING)
            calls.append(
                ToolCall(
                    task_id=task.id,
                    tool_name="prepare_patch",
                    result="No patch writer is configured; no files were changed.",
                )
            )
            patch_result = PatchResult(task_id=task.id, diff=tools.diff())

            self.task_service.update_status(task.id, TaskStatus.TESTING)
            command_result = TestRunner(manager).run(worktree, task.test_command)
            patch_result.tests_passed = command_result.exit_code == 0 and not command_result.timed_out
            calls.append(
                ToolCall(
                    task_id=task.id,
                    tool_name="run_tests",
                    arguments={"command": task.test_command},
                    result=(
                        f"exit_code={command_result.exit_code} timed_out={command_result.timed_out}\n"
                        f"{command_result.stdout}{command_result.stderr}"
                    ),
                )
            )

            self.task_service.update_status(task.id, TaskStatus.REPORTING)
            final_status = TaskStatus.COMPLETED if patch_result.tests_passed else TaskStatus.FAILED
            task = self.task_service.update_status(task.id, final_status)
            return WorkflowResult(
                task=task,
                plan=plan,
                tool_calls=calls,
                patch_result=patch_result,
            )
        except Exception as error:
            task = self.task_service.update_status(task.id, TaskStatus.FAILED)
            return WorkflowResult(
                task=task,
                plan=plan,
                tool_calls=calls,
                patch_result=patch_result,
                error=str(error),
            )
        finally:
            if worktree is not None and manager.owns(worktree):
                manager.cleanup(worktree)
