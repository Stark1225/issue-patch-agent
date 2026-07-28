import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.tools.repository import RepositoryTools, WorktreeManager
from backend.app.tools.runner import CommandNotAllowedError, TestRunner


@pytest.fixture
def source_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "source-repository"
    repository.mkdir()
    subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
    (repository / "src").mkdir()
    (repository / "src" / "app.py").write_text("def health():\n    return 'ok'\n")
    (repository / "guide.md").write_text("This document has no matching file-name text.\n")
    (repository / "test_smoke.py").write_text("def test_smoke():\n    assert True\n")
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


def test_worktree_tools_do_not_modify_the_source_repository(source_repository: Path) -> None:
    manager = WorktreeManager()
    worktree = manager.create(source_repository)
    tools = RepositoryTools(worktree)

    try:
        assert tools.search("def health") == ["src/app.py"]
        assert "return 'ok'" in tools.read_text("src/app.py")

        (worktree / "src" / "app.py").write_text("def health():\n    return 'ready'\n")
        assert "ready" in tools.diff()
        assert "ready" not in (source_repository / "src" / "app.py").read_text()

        with pytest.raises(ValueError, match="outside"):
            tools.read_text("../outside.txt")
    finally:
        manager.cleanup(worktree)


def test_repository_tools_fall_back_when_ripgrep_is_unavailable(
    source_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = WorktreeManager()
    worktree = manager.create(source_repository)
    tools = RepositoryTools(worktree)
    try:
        with monkeypatch.context() as context:
            context.setattr(
                "backend.app.tools.repository.subprocess.Popen",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
            )
            assert tools.search("def health") == ["src/app.py"]
    finally:
        manager.cleanup(worktree)


def test_repository_tools_searches_file_names(source_repository: Path) -> None:
    manager = WorktreeManager()
    worktree = manager.create(source_repository)
    tools = RepositoryTools(worktree)

    try:
        assert tools.search("guide") == ["guide.md"]
    finally:
        manager.cleanup(worktree)


def test_test_runner_rejects_unapproved_commands_and_runs_pytest(
    source_repository: Path,
) -> None:
    manager = WorktreeManager()
    worktree = manager.create(source_repository)
    runner = TestRunner(manager, timeout_seconds=10)

    try:
        with pytest.raises(CommandNotAllowedError):
            runner.run(worktree, "rm -rf /tmp/anything")

        with pytest.raises(CommandNotAllowedError, match="managed worktree"):
            runner.run(source_repository, "pytest -q test_smoke.py")

        with pytest.raises(CommandNotAllowedError, match="outside the managed worktree"):
            runner.run(worktree, f"pytest -q {source_repository / 'test_smoke.py'}")

        result = runner.run(worktree, "pytest -q test_smoke.py")
    finally:
        manager.cleanup(worktree)

    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.command[:3] == (sys.executable, "-m", "pytest")
    assert "1 passed" in result.stdout


def test_worktree_manager_refuses_to_clean_an_unmanaged_path(tmp_path: Path) -> None:
    unmanaged_parent = tmp_path / "unmanaged"
    unmanaged_worktree = unmanaged_parent / "workspace"
    unmanaged_worktree.mkdir(parents=True)

    with pytest.raises(ValueError, match="managed"):
        WorktreeManager().cleanup(unmanaged_worktree)

    assert unmanaged_parent.exists()
