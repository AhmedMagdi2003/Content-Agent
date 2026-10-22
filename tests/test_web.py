import json

from sqlalchemy import select

from app.models import Event
from app.web import create_app


def test_auth_csrf_and_content_only_dashboard(runtime):
    cfg, _, client = runtime
    del client.headers["Authorization"]
    assert (
        client.post("/api/v1/content", json={"source": "A fictional source update."}).status_code
        == 401
    )
    assert (
        client.post("/login", data={"token": cfg.reviewer_token.get_secret_value()}).status_code
        == 200
    )
    assert (
        client.post("/api/v1/content", json={"source": "A fictional source update."}).status_code
        == 403
    )
    assert client.get("/content").status_code == 200
    assert "Financial Operations" not in client.get("/content").text
    assert client.get("/operations").status_code == 200
    assert client.get("/api/v1/documents/not-owned").status_code == 404


def test_content_persists_across_independent_app_instances(runtime):
    from fastapi.testclient import TestClient

    cfg, app, client = runtime
    item = client.post(
        "/api/v1/content", json={"source": "A fictional workshop reviewed its checklist."}
    ).json()
    with TestClient(create_app(cfg)) as restarted:
        restarted.headers["Authorization"] = f"Bearer {cfg.reviewer_token.get_secret_value()}"
        result = restarted.get(f"/api/v1/content/{item['id']}").json()
        assert result["content"]["source"] == item["source"]
        assert len(result["revisions"][0]["drafts"]) == 3
    with app.state.sessions() as session:
        events = session.scalars(select(Event).where(Event.resource_id == item["id"])).all()
        assert events and events[0].request_id and events[0].run_id
        assert all(item["source"] not in json.dumps(event.safe_metadata) for event in events)
