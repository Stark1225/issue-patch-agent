import pytest

from backend.app.tools.repository import GitHubRepositoryCloner


@pytest.mark.parametrize(
    ("repository_url", "expected"),
    [
        ("https://github.com/owner/repository", "https://github.com/owner/repository.git"),
        ("https://github.com/owner/repository.git", "https://github.com/owner/repository.git"),
    ],
)
def test_normalize_url_accepts_public_github_repository_urls(
    repository_url: str, expected: str
) -> None:
    assert GitHubRepositoryCloner.normalize_url(repository_url) == expected


@pytest.mark.parametrize(
    "repository_url",
    [
        "http://github.com/owner/repository",
        "https://gitlab.com/owner/repository",
        "https://github.com/owner/repository/issues",
        "https://github.com/owner/repository?ref=main",
        "https://github.com/owner/repository%2Fother",
    ],
)
def test_normalize_url_rejects_unsupported_repository_urls(repository_url: str) -> None:
    with pytest.raises(ValueError):
        GitHubRepositoryCloner.normalize_url(repository_url)


def test_clone_requires_an_explicitly_approved_repository() -> None:
    cloner = GitHubRepositoryCloner(approved_repositories={"owner/other-repository"})

    with pytest.raises(PermissionError, match="not approved"):
        cloner.clone("https://github.com/owner/repository")
