import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from backend.app.tools.repository import WorktreeManager

class CommandNotAllowedError(ValueError):
    """Raised when a task asks to execute a command outside the explicit allowlist."""


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool


class TestRunner:
    """Runs a narrowly allowlisted test command without invoking a shell."""

    __test__ = False
    _ALLOWED_PREFIXES = (("pytest",), ("python", "-m", "pytest"))

    def __init__(
        self,
        worktree_manager: WorktreeManager,
        *,
        timeout_seconds: int = 60,
        max_output_chars: int = 20_000,
    ) -> None:
        self.worktree_manager = worktree_manager
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars

    def run(self, repository: Path, command_text: str) -> CommandResult:
        worktree = repository.resolve()
        if not self.worktree_manager.owns(worktree):
            raise CommandNotAllowedError("Tests can only run inside a managed worktree")
        requested_command = tuple(shlex.split(command_text))
        if not requested_command or not self._is_allowed(requested_command):
            raise CommandNotAllowedError(
                "Only pytest and python -m pytest commands are allowed in this version"
            )
        self._validate_arguments(worktree, requested_command)
        command = self._resolve_command(requested_command)
        try:
            completed = subprocess.run(
                command,
                cwd=worktree,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            return CommandResult(
                command=command,
                exit_code=completed.returncode,
                stdout=self._truncate(completed.stdout),
                stderr=self._truncate(completed.stderr),
                timed_out=False,
            )
        except subprocess.TimeoutExpired as error:
            return CommandResult(
                command=command,
                exit_code=None,
                stdout=self._truncate(self._as_text(error.stdout)),
                stderr=self._truncate(self._as_text(error.stderr)),
                timed_out=True,
            )

    def _is_allowed(self, command: tuple[str, ...]) -> bool:
        return any(command[: len(prefix)] == prefix for prefix in self._ALLOWED_PREFIXES)

    @staticmethod
    def _resolve_command(command: tuple[str, ...]) -> tuple[str, ...]:
        if command[:1] == ("pytest",):
            return (sys.executable, "-m", "pytest", *command[1:])
        return (sys.executable, *command[1:])

    def _validate_arguments(self, worktree: Path, command: tuple[str, ...]) -> None:
        prefix_length = max(
            len(prefix) for prefix in self._ALLOWED_PREFIXES if command[: len(prefix)] == prefix
        )
        arguments = command[prefix_length:]
        blocked_options = {"-c", "--rootdir", "--confcutdir", "--pyargs", "-p", "-o"}
        if any(argument in blocked_options for argument in arguments):
            raise CommandNotAllowedError("Pytest configuration overrides are not allowed")

        for argument in arguments:
            if argument.startswith("--rootdir=") or argument.startswith("--confcutdir="):
                raise CommandNotAllowedError("Pytest configuration overrides are not allowed")
            if argument.startswith("-"):
                continue
            target = argument.split("::", maxsplit=1)[0]
            candidate = (worktree / target).resolve()
            try:
                candidate.relative_to(worktree)
            except ValueError as error:
                raise CommandNotAllowedError(
                    "Test targets cannot point outside the managed worktree"
                ) from error

    def _truncate(self, output: str) -> str:
        return output[: self.max_output_chars]

    @staticmethod
    def _as_text(output: str | bytes | None) -> str:
        if output is None:
            return ""
        if isinstance(output, bytes):
            return output.decode(errors="replace")
        return output
