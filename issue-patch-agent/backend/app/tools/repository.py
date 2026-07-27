import shutil
import select
import subprocess
import tempfile
import time
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
        try:
            self._run_git(source, "worktree", "add", "--detach", str(worktree), "HEAD")
        except Exception:
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise
        resolved_worktree = worktree.resolve()
        self._sources[resolved_worktree] = source
        return resolved_worktree

    def owns(self, worktree: Path) -> bool:
        return worktree.resolve() in self._sources

    def cleanup(self, worktree: Path) -> None:
        resolved_worktree = worktree.resolve()
        source = self._sources.pop(resolved_worktree, None)
        if source is None:
            raise ValueError("Can only clean up a managed worktree")
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

    def __init__(
        self,
        root: Path,
        *,
        max_file_bytes: int = 100_000,
        search_timeout_seconds: int = 10,
        max_diff_chars: int = 100_000,
    ) -> None:
        self.root = root.resolve()
        self.max_file_bytes = max_file_bytes
        self.search_timeout_seconds = search_timeout_seconds
        self.max_diff_chars = max_diff_chars

    def search(self, query: str, *, max_results: int = 20) -> list[str]:
        try:
            process = subprocess.Popen(
                [
                    "rg",
                    "--files-with-matches",
                    "--max-count=1",
                    "--glob",
                    "!**/.git/**",
                    "--",
                    query,
                    str(self.root),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError:
            return self._search_with_python(query, max_results)
        assert process.stdout is not None
        deadline = time.monotonic() + self.search_timeout_seconds
        matches: list[str] = []
        try:
            while True:
                if len(matches) == max_results:
                    process.terminate()
                    process.communicate()
                    return matches
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Code search timed out")
                ready, _, _ = select.select([process.stdout], [], [], remaining)
                if not ready:
                    raise TimeoutError("Code search timed out")
                line = process.stdout.readline()
                if not line:
                    break
                matches.append(str(Path(line.strip()).resolve().relative_to(self.root)))
        except TimeoutError:
            process.kill()
            process.communicate()
            raise
        finally:
            if process.poll() is None:
                process.terminate()
        _, stderr = process.communicate()
        if process.returncode not in (0, 1):
            raise RuntimeError(stderr.strip() or "Code search failed")
        return matches

    def _search_with_python(self, query: str, max_results: int) -> list[str]:
        matches: list[str] = []
        for candidate in self.root.rglob("*"):
            if ".git" in candidate.parts or not candidate.is_file():
                continue
            if candidate.stat().st_size > self.max_file_bytes:
                continue
            try:
                contents = candidate.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if query in contents:
                matches.append(str(candidate.relative_to(self.root)))
                if len(matches) == max_results:
                    break
        return matches

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
        try:
            result = subprocess.run(
                ["git", "-C", str(self.root), "diff", "--no-ext-diff"],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.search_timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise TimeoutError("Git diff timed out") from error
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Unable to read Git diff")
        if len(result.stdout) > self.max_diff_chars:
            raise ValueError("Git diff exceeds the configured size limit")
        return result.stdout
