from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


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
    repository_path: str = Field(min_length=1)
    issue: str = Field(min_length=1)
    test_command: str = Field(min_length=1)


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
