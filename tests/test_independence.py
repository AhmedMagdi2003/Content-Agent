import ast

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.config import APP_ROOT, Settings
from app.models import Base
from app.web import create_app


def test_no_financial_imports():
    """Ensure the content agent has zero dependencies on finance code or modules."""
    forbidden = {"financial", "app.financial", "app.inspection"}
    for path in (APP_ROOT / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in forbidden, f"Forbidden import {node.module} in {path}"
            if isinstance(node, ast.Import):
                assert not any(n.name in forbidden for n in node.names), (
                    f"Forbidden import in {path}"
                )


def test_only_content_tables_exist(runtime):
    _, app_instance, _ = runtime
    assert set(inspect(app_instance.state.engine).get_table_names()) == {
        "content_items",
        "content_revisions",
        "publications",
        "publication_attempts",
        "events",
        "llm_usage",
    }
    assert Base.metadata.schema == "content_ops"


def test_standard_and_legacy_environment_variables(monkeypatch):
    # 1. Standard environment variable names
    monkeypatch.setenv("DATABASE_URL", "sqlite:///standard.db")
    monkeypatch.setenv("REVIEWER_TOKEN", "standard-reviewer-secret-key-24")
    monkeypatch.setenv("MODE", "demo")
    cfg = Settings(_env_file=None)
    assert cfg.database_url.get_secret_value() == "sqlite:///standard.db"
    assert cfg.reviewer_token.get_secret_value() == "standard-reviewer-secret-key-24"
    assert cfg.mode == "demo"

    # 2. Legacy CONTENT_ prefixed variable names also work as aliases
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CONTENT_DATABASE_URL", "sqlite:///legacy.db")
    cfg_legacy = Settings(_env_file=None)
    assert cfg_legacy.database_url.get_secret_value() == "sqlite:///legacy.db"


def test_health_starts_independently():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["service"] == "content-agent"
