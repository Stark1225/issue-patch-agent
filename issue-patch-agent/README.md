# IssuePatch Agent

An inspectable skeleton for an Agent that will eventually turn a GitHub Issue into a tested patch. The first week deliberately contains no LLM calls, repository writes, or command execution.

## Included in week one

- FastAPI service with `GET /health` and `POST /tasks`
- Pydantic domain models: `Task`, `Plan`, `ToolCall`, and `PatchResult`
- In-memory task service and explicit Agent workflow states
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

This version only stores task metadata in memory and prints simulated workflow stages. It does not inspect a repository, write files, execute the provided test command, call a model, push commits, or create pull requests.
