import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Protocol


class ModelConfigurationError(RuntimeError):
    """Raised when model-backed patch generation has not been configured."""


class DiffValidationError(ValueError):
    """Raised when a proposed unified diff is malformed or violates path limits."""


class DiffApplicationError(RuntimeError):
    """Raised when Git cannot safely apply a validated diff."""


class PatchGenerator(Protocol):
    def generate(self, *, issue: str, plan_steps: list[str], files: dict[str, str]) -> str: ...


class DeepSeekPatchGenerator:
    """Generates unified diffs through DeepSeek's OpenAI-compatible Chat API."""

    def __init__(self, *, model: str, client: object) -> None:
        self.model = model
        self.client = client

    @classmethod
    def from_environment(cls) -> "DeepSeekPatchGenerator":
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ModelConfigurationError("Set DEEPSEEK_API_KEY before requesting patch generation")
        try:
            from openai import OpenAI
        except ImportError as error:
            raise ModelConfigurationError("Install the openai package for DeepSeek compatibility") from error
        return cls(model=model, client=OpenAI(api_key=api_key, base_url="https://api.deepseek.com"))

    def generate(self, *, issue: str, plan_steps: list[str], files: dict[str, str]) -> str:
        context = "\n\n".join(f"FILE: {path}\n{contents}" for path, contents in files.items())
        prompt = f"""You are proposing a minimal code change for a software engineer to review.

Issue:
{issue}

Plan:
{chr(10).join(f'- {step}' for step in plan_steps)}

You may modify only the files shown below. Return only a valid unified diff beginning with `diff --git`. Do not include Markdown fences, explanations, shell commands, or any paths outside this context.

{context}"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "Return only a unified diff."},
                {"role": "user", "content": prompt},
            ],
            stream=False,
        )
        output = response.choices[0].message.content
        if not output:
            raise RuntimeError("The model returned no patch text")
        return self._strip_code_fence(output)

    @staticmethod
    def _strip_code_fence(output: str) -> str:
        stripped = output.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            return "\n".join(stripped.splitlines()[1:-1]).strip()
        return stripped


class DiffValidator:
    def __init__(self, *, max_chars: int = 100_000) -> None:
        self.max_chars = max_chars

    def validate(self, diff: str, *, allowed_paths: set[str] | None = None) -> str:
        if not diff.strip().startswith("diff --git "):
            raise DiffValidationError("Patch must be a unified diff beginning with 'diff --git'")
        if len(diff) > self.max_chars:
            raise DiffValidationError("Patch exceeds the configured size limit")

        paths = [
            self._normalise_path(line)
            for line in diff.splitlines()
            if line.startswith("--- ") or line.startswith("+++ ")
        ]
        paths = [path for path in paths if path is not None]
        if not paths:
            raise DiffValidationError("Patch does not contain file headers")
        if allowed_paths is not None and not set(paths).issubset(allowed_paths):
            raise DiffValidationError("Patch modifies a path outside the retrieved context")
        return diff

    @staticmethod
    def _normalise_path(header: str) -> str | None:
        raw_path = header[4:].split("\t", maxsplit=1)[0]
        if raw_path == "/dev/null":
            return None
        if not raw_path.startswith(("a/", "b/")):
            raise DiffValidationError("Patch contains a path outside the worktree")
        path = PurePosixPath(raw_path[2:])
        if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
            raise DiffValidationError("Patch contains a path outside the worktree")
        return path.as_posix()


class DiffApplier:
    def __init__(self, *, timeout_seconds: int = 15) -> None:
        self.timeout_seconds = timeout_seconds

    def apply(self, worktree: Path, diff: str) -> None:
        for arguments in (("apply", "--check", "--whitespace=error"), ("apply", "--whitespace=error")):
            result = subprocess.run(
                ["git", "-C", str(worktree), *arguments],
                input=diff,
                text=True,
                capture_output=True,
                check=False,
                timeout=self.timeout_seconds,
            )
            if result.returncode != 0:
                raise DiffApplicationError(result.stderr.strip() or "Git rejected the proposed patch")
