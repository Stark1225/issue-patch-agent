# IssuePatch Agent

An inspectable Agent that turns a repository issue description into a reviewable patch proposal and test report. It works in a disposable Git worktree, so it never changes source working-tree files.

## Included

- FastAPI service with `GET /health` and `POST /tasks`
- Pydantic domain models: `Task`, `Plan`, `ToolCall`, and `PatchResult`
- In-memory task service and explicit Agent workflow states
- Disposable git worktrees, scoped code search/file reads, diffs, and allowlisted pytest execution
- `POST /tasks/{id}/run` orchestration with a plan, tool-call log, and test report
- Optional DeepSeek-powered unified diff generation
- React task dashboard, Docker Compose deployment definition, and unit tests

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

For the cloud dashboard, provide a public GitHub repository URL such as `https://github.com/owner/repository`. The service shallow-clones it into a temporary directory, creates an isolated worktree, and deletes both after the run. Local `repository_path` input remains available for Docker Compose and API clients.

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

## Run the frontend locally

In a second terminal, after starting the FastAPI backend on port 8000:

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (normally `http://localhost:5173`). The development proxy forwards `/api` requests to the local backend.

For a separately hosted frontend, set `VITE_API_BASE_URL` to the backend's public URL when building the frontend. Set `ALLOWED_ORIGINS` on the backend to the frontend's public URL. Both values are deployment configuration and are not committed.

## Run with Docker Compose

Install and start Docker Desktop first. Docker Compose will run the backend and dashboard together. The Agent needs access to the repositories it analyzes, so mount the **parent directory** that contains your target Git repositories:

```bash
export HOST_REPOSITORIES_DIR="/absolute/path/to/your/repositories"
export DEEPSEEK_API_KEY="..."
docker compose up --build
```

Then open `http://localhost:8080`.

In the dashboard, repository paths must use the path inside the container. For example, if the host repository is `/Users/name/projects/demo-repo` and `HOST_REPOSITORIES_DIR=/Users/name/projects`, enter:

```text
/repositories/demo-repo
```

The mount is writable because Git creates and removes temporary worktrees. Keep `DEEPSEEK_API_KEY` in your terminal environment or a local untracked `.env` file; never commit it. Stop the services with:

```bash
docker compose down
```

## Test

```bash
python -m pytest -q
```

## Security boundary

Tasks are stored only in memory. Repository tools operate only in a temporary Git worktree; they never write to source working-tree files, though Git temporarily updates repository metadata while managing worktrees. Test execution is restricted to `pytest` and `python -m pytest`, has a timeout, and does not invoke a shell. The Agent does not push commits or create pull requests.
