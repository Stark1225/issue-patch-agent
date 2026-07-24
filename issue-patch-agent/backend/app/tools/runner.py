import shlex
import subprocess
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
        if not self.worktree_manager.owns(repository):
            raise CommandNotAllowedError("Tests can only run inside a managed worktree")
        command = tuple(shlex.split(command_text))
        if not command or not self._is_allowed(command):
            raise CommandNotAllowedError(
                "Only pytest and python -m pytest commands are allowed in this version"
            )
        try:
            completed = subprocess.run(
                command,
                cwd=repository,
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

    def _truncate(self, output: str) -> str:
        return output[: self.max_output_chars]

    @staticmethod
    def _as_text(output: str | bytes | None) -> str:
        if output is None:
            return ""
        if isinstance(output, bytes):
            return output.decode(errors="replace")
        return output
