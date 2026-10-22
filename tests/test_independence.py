import ast

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from content_app.config import APP_ROOT, Settings
from content_app.models import Base
from content_app.web import create_app


def test_no_financial_imports():
    for path in (APP_ROOT / "content_app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module == "app" or (node.module or "").startswith("app.")), path
            if isinstance(node, ast.Import):
                assert not any(n.name == "app" or n.name.startswith("app.") for n in node.names), (
                    path
                )


def test_only_content_tables_exist(runtime):
    _, app, _ = runtime
    assert set(inspect(app.state.engine).get_table_names()) == {
        "content_items",
        "content_revisions",
        "publications",
        "publication_attempts",
        "events",
        "llm_usage",
    }
    assert Base.metadata.schema == "content_ops"


def test_unprefixed_financial_environment_is_not_consumed(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///financial.db")
    monkeypatch.setenv("REVIEWER_TOKEN", "financial-reviewer-secret")
    monkeypatch.setenv("MODE", "demo")
    cfg = Settings(_env_file=None)
    assert not cfg.database_url.get_secret_value()
    assert not cfg.reviewer_token.get_secret_value()
    assert cfg.mode == "cloud"


def test_health_starts_without_any_financial_configuration():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["service"] == "content-agent"


def test_content_cookie_is_separate(runtime):
    cfg, _, client = runtime
    response = client.post(
        "/login", data={"token": cfg.reviewer_token.get_secret_value()}, follow_redirects=False
    )
    assert "content_session=" in response.headers["set-cookie"]
    assert "session=" not in response.headers["set-cookie"].split("content_session=")[0]
