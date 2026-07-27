# IssuePatch Agent

An inspectable skeleton for an Agent that will eventually turn a GitHub Issue into a tested patch. The first week deliberately contains no LLM calls, repository writes, or command execution.

## Included in week one

- FastAPI service with `GET /health` and `POST /tasks`
- Pydantic domain models: `Task`, `Plan`, `ToolCall`, and `PatchResult`
- In-memory task service and explicit Agent workflow states
- Disposable git worktrees, scoped code search/file reads, diffs, and allowlisted pytest execution
- `POST /tasks/{id}/run` orchestration with a plan, tool-call log, and test report
- CLI that prints `queued → analyzing → retrieving → planning → patching → testing → reporting → completed`
- Unit tests, Docker image definition, and GitHub Actions CI

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
uvicorn backend.app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` to call the API.

Create a task with `POST /tasks`, then call `POST /tasks/{id}/run`. The default deterministic planner retrieves files and emits a reviewable plan without changing code.

## Generate a patch for review

Set credentials in the shell that starts the server; never commit them:

```bash
export DEEPSEEK_API_KEY="..."
export DEEPSEEK_MODEL="deepseek-v4-flash"
```

Call `POST /tasks/{id}/run?generate_patch=true`. The project uses DeepSeek's OpenAI-compatible Chat API at `https://api.deepseek.com`. The model may only return a unified diff. The service validates its paths, applies it only to a disposable worktree, runs the allowlisted tests there, and returns the diff and results. The source repository is never modified.

## Run the CLI

```bash
issue-patch-agent run \
  --repo /tmp/example-repo \
  --issue "Fix the blank page on failed login" \
  --test-command "pytest -q"
```

## Test

```bash
python -m pytest -q
```

## Security boundary

This version only stores task metadata in memory and prints simulated workflow stages. Repository tools operate only in a temporary git worktree; they never write to the source checkout. Test execution is restricted to `pytest` and `python -m pytest`, has a timeout, and does not invoke a shell. It still does not call a model, push commits, or create pull requests.
