from backend.app.main import allowed_origins


def test_allowed_origins_defaults_to_local_frontend(monkeypatch) -> None:
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)

    assert allowed_origins() == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_allowed_origins_reads_a_comma_separated_environment_value(monkeypatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", " https://app.example.com,https://preview.example.com , ")

    assert allowed_origins() == ["https://app.example.com", "https://preview.example.com"]
