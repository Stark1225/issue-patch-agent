from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.app.tools.repository import GitHubRepositoryCloner


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(StrEnum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    RETRIEVING = "retrieving"
    PLANNING = "planning"
    PATCHING = "patching"
    TESTING = "testing"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"


class CreateTaskRequest(BaseModel):
    repository_path: str | None = None
    repository_url: str | None = None
    issue: str = Field(min_length=1)
    test_command: str = Field(min_length=1)

    @field_validator("repository_url")
    @classmethod
    def repository_url_is_a_supported_github_url(cls, value: str | None) -> str | None:
        if value is not None:
            GitHubRepositoryCloner.normalize_url(value)
        return value

    @model_validator(mode="after")
    def has_repository_source(self) -> "CreateTaskRequest":
        if bool(self.repository_path) == bool(self.repository_url):
            raise ValueError("Provide exactly one of repository_path or repository_url")
        return self


class Task(CreateTaskRequest):
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: TaskStatus = TaskStatus.QUEUED
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Plan(BaseModel):
    task_id: str
    steps: list[str]


class ToolCall(BaseModel):
    task_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: str | None = None


class PatchResult(BaseModel):
    task_id: str
    diff: str
    tests_passed: bool | None = None
    applied_to_worktree: bool = False


class WorkflowResult(BaseModel):
    task: Task
    plan: Plan
    tool_calls: list[ToolCall]
    patch_result: PatchResult
    error: str | None = None
