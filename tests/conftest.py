import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import initialize, make_engine
from app.web import create_app


@pytest.fixture
def runtime(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="demo",
        provider="fixture",
        secure_cookies=False,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        local_data_dir=tmp_path,
        reviewer_token="reviewer-" + "x" * 32,
        session_secret="session-" + "x" * 32,
        publisher_secret="publisher-" + "x" * 32,
    )
    engine = make_engine(settings.database_url.get_secret_value())
    initialize(engine)
    app = create_app(settings, engine)
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {settings.reviewer_token.get_secret_value()}"
        yield settings, app, client
    engine.dispose()
