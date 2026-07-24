import shutil
import subprocess
import tempfile
from pathlib import Path


class WorktreeManager:
    """Creates disposable Git worktrees without changing the source checkout."""

    def __init__(self) -> None:
        self._sources: dict[Path, Path] = {}

    def create(self, source_repository: Path) -> Path:
        source = source_repository.resolve()
        self._run_git(source, "rev-parse", "--is-inside-work-tree")
        temporary_root = Path(tempfile.mkdtemp(prefix="issue-patch-agent-"))
        worktree = temporary_root / "workspace"
        self._run_git(source, "worktree", "add", "--detach", str(worktree), "HEAD")
        self._sources[worktree] = source
        return worktree

    def cleanup(self, worktree: Path) -> None:
        resolved_worktree = worktree.resolve()
        source = self._sources.pop(resolved_worktree, None)
        if source is not None:
            self._run_git(source, "worktree", "remove", "--force", str(resolved_worktree))
        shutil.rmtree(resolved_worktree.parent, ignore_errors=True)

    @staticmethod
    def _run_git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Git command failed")
        return result


class RepositoryTools:
    """Read-only inspection helpers plus diff retrieval, scoped to one worktree."""

    def __init__(self, root: Path, *, max_file_bytes: int = 100_000) -> None:
        self.root = root.resolve()
        self.max_file_bytes = max_file_bytes

    def search(self, query: str, *, max_results: int = 20) -> list[str]:
        result = subprocess.run(
            ["rg", "--files-with-matches", "--glob", "!**/.git/**", "--", query, str(self.root)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 1:
            return []
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Code search failed")
        return [
            str(Path(line).resolve().relative_to(self.root))
            for line in result.stdout.splitlines()[:max_results]
        ]

    def read_text(self, relative_path: str) -> str:
        candidate = (self.root / relative_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise ValueError("Requested path is outside the worktree") from error
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        if candidate.stat().st_size > self.max_file_bytes:
            raise ValueError("Requested file exceeds the configured size limit")
        return candidate.read_text(encoding="utf-8")

    def diff(self) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.root), "diff", "--no-ext-diff"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Unable to read Git diff")
        return result.stdout
