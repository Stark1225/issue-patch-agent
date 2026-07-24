import argparse
from collections.abc import Sequence

from backend.app.models import TaskStatus
from backend.app.services.task_service import TaskService


WORKFLOW = (
    TaskStatus.ANALYZING,
    TaskStatus.RETRIEVING,
    TaskStatus.PLANNING,
    TaskStatus.PATCHING,
    TaskStatus.TESTING,
    TaskStatus.REPORTING,
    TaskStatus.COMPLETED,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the IssuePatch Agent workflow skeleton.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Print the first-week workflow stages.")
    run_parser.add_argument("--repo", required=True, help="Path to the target repository.")
    run_parser.add_argument("--issue", required=True, help="Issue text to analyse.")
    run_parser.add_argument("--test-command", required=True, help="Test command recorded for later weeks.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = TaskService()
    task = service.create_task(
        repository_path=args.repo,
        issue=args.issue,
        test_command=args.test_command,
    )
    print(f"task={task.id} status={task.status}")

    for status in WORKFLOW:
        task = service.update_status(task.id, status)
        print(f"task={task.id} status={task.status}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
