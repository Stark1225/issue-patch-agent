import logging
import re
from pathlib import Path

from backend.app.models import PatchResult, Plan, Task, TaskStatus, ToolCall, WorkflowResult
from backend.app.services.patch_generator import (
    DiffApplicationError,
    DiffApplier,
    DiffNormalizer,
    DiffValidationError,
    DiffValidator,
    PatchGenerator,
)
from backend.app.services.task_service import TaskService
from backend.app.tools.repository import GitHubRepositoryCloner, RepositoryTools, WorktreeManager
from backend.app.tools.runner import TestRunner


logger = logging.getLogger(__name__)


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

    def __init__(
        self,
        task_service: TaskService,
        patch_generator: PatchGenerator | None = None,
        repository_cloner: GitHubRepositoryCloner | None = None,
    ) -> None:
        self.task_service = task_service
        self.planner = DeterministicPlanner()
        self.patch_generator = patch_generator
        self.repository_cloner = repository_cloner or GitHubRepositoryCloner()

    def run(self, task_id: str, *, generate_patch: bool = False) -> WorkflowResult:
        task = self.task_service.get_task(task_id)
        calls: list[ToolCall] = []
        plan = Plan(task_id=task.id, steps=[])
        patch_result = PatchResult(task_id=task.id, diff="", tests_passed=None)
        manager = WorktreeManager()
        worktree: Path | None = None
        cloned_repository: Path | None = None

        try:
            self.task_service.update_status(task.id, TaskStatus.ANALYZING)
            if task.repository_url:
                cloned_repository = self.repository_cloner.clone(task.repository_url)
                source_repository = cloned_repository
                calls.append(
                    ToolCall(
                        task_id=task.id,
                        tool_name="clone_repository",
                        arguments={"repository_url": task.repository_url},
                        result="Cloned the public GitHub repository into a temporary directory.",
                    )
                )
            else:
                assert task.repository_path is not None
                source_repository = Path(task.repository_path)
            worktree = manager.create(source_repository)
            calls.append(
                ToolCall(
                    task_id=task.id,
                    tool_name="create_worktree",
                    arguments={"repository_path": str(source_repository)},
                    result="Created an isolated worktree.",
                )
            )
            tools = RepositoryTools(worktree)

            self.task_service.update_status(task.id, TaskStatus.RETRIEVING)
            relevant_files: list[str] = []
            retrieved_files: dict[str, str] = {}
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
                retrieved_files[relative_path] = contents
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
            if generate_patch:
                if self.patch_generator is None:
                    raise RuntimeError("Patch generation is not configured")
                proposed_diff = self.patch_generator.generate(
                    issue=task.issue,
                    plan_steps=plan.steps,
                    files=retrieved_files,
                )
                validator = DiffValidator()
                applier = DiffApplier()
                normalizer = DiffNormalizer()
                try:
                    proposed_diff = normalizer.normalize(
                        proposed_diff, allowed_paths=set(retrieved_files)
                    )
                    validator.validate(proposed_diff, allowed_paths=set(retrieved_files))
                    applier.apply(worktree, proposed_diff)
                except (DiffValidationError, DiffApplicationError) as error:
                    repair = getattr(self.patch_generator, "repair", None)
                    if not callable(repair):
                        raise
                    proposed_diff = repair(
                        issue=task.issue,
                        plan_steps=plan.steps,
                        files=retrieved_files,
                        rejected_diff=proposed_diff,
                        error=str(error),
                    )
                    proposed_diff = normalizer.normalize(
                        proposed_diff, allowed_paths=set(retrieved_files)
                    )
                    validator.validate(proposed_diff, allowed_paths=set(retrieved_files))
                    applier.apply(worktree, proposed_diff)
                    calls.append(
                        ToolCall(
                            task_id=task.id,
                            tool_name="repair_patch",
                            result="Regenerated a patch after the first diff was rejected.",
                        )
                    )
                patch_result = PatchResult(
                    task_id=task.id,
                    diff=tools.diff(),
                    applied_to_worktree=True,
                )
                calls.append(
                    ToolCall(
                        task_id=task.id,
                        tool_name="generate_patch",
                        result="Validated and applied the proposed diff in the temporary worktree.",
                    )
                )
            else:
                calls.append(
                    ToolCall(
                        task_id=task.id,
                        tool_name="prepare_patch",
                        result="Patch generation was not requested; no files were changed.",
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
                try:
                    manager.cleanup(worktree)
                except Exception:
                    logger.exception("Unable to remove temporary worktree")
            if cloned_repository is not None:
                try:
                    self.repository_cloner.cleanup(cloned_repository)
                except Exception:
                    logger.exception("Unable to remove temporary repository clone")
