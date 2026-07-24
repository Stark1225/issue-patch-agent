from backend.app.cli import main


def test_run_command_prints_each_workflow_stage(capsys) -> None:
    exit_code = main(
        [
            "run",
            "--repo",
            "/tmp/example-repo",
            "--issue",
            "修复登录失败时显示空白页的问题",
            "--test-command",
            "pytest -q",
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "queued" in output
    assert "analyzing" in output
    assert "reporting" in output
    assert "completed" in output
