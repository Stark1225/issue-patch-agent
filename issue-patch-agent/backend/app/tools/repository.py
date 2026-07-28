import shutil
import select
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse


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


class GitHubRepositoryCloner:
    """Clones a public GitHub repository into a disposable directory."""

    def __init__(
        self,
        *,
        timeout_seconds: int = 60,
        approved_repositories: set[str] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        configured_repositories = approved_repositories
        if configured_repositories is None:
            configured_repositories = {
                repository.strip()
                for repository in os.getenv("APPROVED_GITHUB_REPOSITORIES", "").split(",")
                if repository.strip()
            }
        self.approved_repositories = configured_repositories
        self._clone_roots: dict[Path, Path] = {}

    def clone(self, repository_url: str) -> Path:
        normalized_url = self.normalize_url(repository_url)
        if self.repository_name(normalized_url) not in self.approved_repositories:
            raise PermissionError("This GitHub repository is not approved for cloud execution")
        clone_root = Path(tempfile.mkdtemp(prefix="issue-patch-agent-clone-"))
        repository = clone_root / "repository"
        try:
            result = subprocess.run(
                [
                    "git",
                    "-c",
                    "protocol.file.allow=never",
                    "clone",
                    "--depth",
                    "1",
                    "--no-tags",
                    normalized_url,
                    str(repository),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            shutil.rmtree(clone_root, ignore_errors=True)
            raise TimeoutError("Repository clone timed out") from error
        if result.returncode != 0:
            shutil.rmtree(clone_root, ignore_errors=True)
            raise RuntimeError(result.stderr.strip() or "Unable to clone repository")
        resolved_repository = repository.resolve()
        self._clone_roots[resolved_repository] = clone_root
        return resolved_repository

    def cleanup(self, repository: Path) -> None:
        clone_root = self._clone_roots.pop(repository.resolve(), None)
        if clone_root is not None:
            shutil.rmtree(clone_root, ignore_errors=True)

    @staticmethod
    def normalize_url(repository_url: str) -> str:
        parsed = urlparse(repository_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or parsed.port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Only public https://github.com/owner/repository URLs are supported")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 2:
            raise ValueError("GitHub repository URLs must use /owner/repository")
        owner, repository = parts
        if repository.endswith(".git"):
            repository = repository[:-4]
        if not owner or not repository or not all(
            character.isalnum() or character in "._-" for character in f"{owner}{repository}"
        ):
            raise ValueError("GitHub owner and repository names contain unsupported characters")
        return f"https://github.com/{owner}/{repository}.git"

    @staticmethod
    def repository_name(normalized_url: str) -> str:
        parts = [part for part in urlparse(normalized_url).path.split("/") if part]
        return f"{parts[0]}/{parts[1].removesuffix('.git')}"


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
import os
