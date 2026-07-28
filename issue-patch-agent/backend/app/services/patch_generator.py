import os
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Protocol


class ModelConfigurationError(RuntimeError):
    """Raised when model-backed patch generation has not been configured."""


class DiffValidationError(ValueError):
    """Raised when a proposed unified diff is malformed or violates path limits."""


class DiffApplicationError(RuntimeError):
    """Raised when Git cannot safely apply a validated diff."""


class DiffNormalizer:
    """Repairs harmless model formatting mistakes before Git remains the final authority."""

    _HUNK_HEADER = re.compile(
        r"^@@ -(?P<old_start>\d+)(?:,\d+)? \+(?P<new_start>\d+)(?:,\d+)? @@(?P<suffix>.*)$"
    )

    def normalize(self, diff: str, *, allowed_paths: set[str]) -> str:
        lines = self._map_paths(diff.splitlines(), allowed_paths)
        return "\n".join(self._fix_hunk_counts(lines)) + "\n"

    @staticmethod
    def _map_paths(lines: list[str], allowed_paths: set[str]) -> list[str]:
        replacements: dict[str, str] = {}
        for line in lines:
            if line.startswith(("--- a/", "+++ b/")):
                path = line[6:].split("\t", maxsplit=1)[0]
                if path in allowed_paths:
                    continue
                candidates = [allowed for allowed in allowed_paths if allowed.endswith(f"/{path}")]
                if len(candidates) == 1:
                    replacements[path] = candidates[0]
        mapped_lines: list[str] = []
        for line in lines:
            for original, replacement in replacements.items():
                if line.startswith("diff --git "):
                    line = line.replace(f"a/{original}", f"a/{replacement}").replace(
                        f"b/{original}", f"b/{replacement}"
                    )
                elif line.startswith("--- a/"):
                    line = line.replace(f"a/{original}", f"a/{replacement}", 1)
                elif line.startswith("+++ b/"):
                    line = line.replace(f"b/{original}", f"b/{replacement}", 1)
            mapped_lines.append(line)
        return mapped_lines

    def _fix_hunk_counts(self, lines: list[str]) -> list[str]:
        normalized = lines[:]
        index = 0
        while index < len(normalized):
            match = self._HUNK_HEADER.match(normalized[index])
            if match is None:
                index += 1
                continue
            end = index + 1
            old_count = new_count = 0
            while end < len(normalized) and not normalized[end].startswith(("@@ ", "diff --git ")):
                line = normalized[end]
                if line.startswith("-"):
                    old_count += 1
                elif line.startswith("+"):
                    new_count += 1
                elif not line.startswith("\\"):
                    old_count += 1
                    new_count += 1
                end += 1
            normalized[index] = (
                f"@@ -{match.group('old_start')},{old_count} "
                f"+{match.group('new_start')},{new_count} @@{match.group('suffix')}"
            )
            index = end
        return normalized


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

You may modify only the files shown below. Return only a valid unified diff beginning with `diff --git`. Use standard Git headers (`diff --git`, `---`, `+++`) and make every hunk header line count match its contents exactly. Do not include Markdown fences, explanations, shell commands, ellipses, or any paths outside this context.

{context}"""
        return self._request_diff(prompt)

    def repair(
        self,
        *,
        issue: str,
        plan_steps: list[str],
        files: dict[str, str],
        rejected_diff: str,
        error: str,
    ) -> str:
        allowed_files = ", ".join(files)
        prompt = f"""Repair a rejected unified diff for this issue:

{issue}

The previous diff failed validation with:
{error}

You may modify only these files: {allowed_files}
Return a complete replacement diff beginning with `diff --git`. Use correct Git hunk line counts. Return no explanation or Markdown fence.

Previous rejected diff:
{rejected_diff}

Current file contents:
{chr(10).join(f'FILE: {path}{chr(10)}{contents}' for path, contents in files.items())}"""
        return self._request_diff(prompt)

    def _request_diff(self, prompt: str) -> str:
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
