import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import content
from app.errors import Conflict
from app.integrations import Publisher
from app.models import Publication
from app.publisher import Post, create_publisher
from app.schemas import Drafts

SOURCE = "The fictional River Research team reviewed a sampling checklist at its workshop."


def new_content(client):
    response = client.post("/api/v1/content", json={"source": SOURCE})
    assert response.status_code == 200, response.text
    item = response.json()
    details = client.get(f"/api/v1/content/{item['id']}").json()
    return item, details["revisions"][0]


def test_drafts_are_distinct_and_do_not_publish(runtime):
    cfg, app, client = runtime
    item, revision = new_content(client)
    assert len(set(revision["drafts"].values())) == 3
    assert all(SOURCE in value for value in revision["drafts"].values())
    assert client.get(f"/api/v1/content/{item['id']}").json()["publications"] == []
    endpoint = f"/api/v1/content/{item['id']}/retry"
    assert (
        client.post(endpoint, json={"revision": 1, "digest": revision["digest"]}).status_code == 409
    )
    del client.headers["Authorization"]
    assert (
        client.post(
            f"/api/v1/content/{item['id']}/approve-and-publish",
            json={"revision": 1, "digest": revision["digest"]},
        ).status_code
        == 401
    )


def test_exact_revision_partial_failure_and_retry(runtime):
    cfg, app, client = runtime
    item, revision = new_content(client)
    calls = []
    fail_social = True

    def handler(request):
        import json

        payload = json.loads(request.content)
        calls.append(payload)
        if payload["channel"] == "linkedin" and fail_social:
            return httpx.Response(503)
        return httpx.Response(200, json={"url": f"http://test/posts/{payload['key']}"})

    publisher = Publisher(cfg, httpx.MockTransport(handler))
    with app.state.sessions() as session:
        selected = content.revise(
            session,
            item["id"],
            1,
            Drafts(**revision["drafts"]),
            ["website", "linkedin"],
            "reviewer",
        )
        digest = selected.digest
        assert (
            content.approve_publish(session, cfg, item["id"], 2, digest, "reviewer", publisher)[
                0
            ].attempts
            == 1
        )
        assert {p.status for p in session.scalars(select(Publication))} == {"published", "failed"}
        fail_social = False
        content.approve_publish(
            session, cfg, item["id"], 2, digest, "reviewer", publisher, retry=True
        )
        assert [p["channel"] for p in calls].count("website") == 1
        assert [p["channel"] for p in calls].count("linkedin") == 2
        newer = content.revise(
            session,
            item["id"],
            2,
            Drafts(**{**revision["drafts"], "website": "Edited source update"}),
            ["website"],
            "reviewer",
        )
        with pytest.raises(Conflict):
            content.approve_publish(session, cfg, item["id"], 2, digest, "reviewer", publisher)
        with pytest.raises(Conflict):
            content.approve_publish(
                session, cfg, item["id"], 3, newer.digest, "reviewer", publisher, retry=True
            )
        with pytest.raises(Conflict):
            content.approve_publish(session, cfg, item["id"], 3, digest, "reviewer", publisher)
    assert len(calls) == 3


def test_retry_ceiling(runtime):
    cfg, app, client = runtime
    item, revision = new_content(client)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    with app.state.sessions() as session:
        for retry in [False, True, True, True]:
            content.approve_publish(
                session,
                cfg,
                item["id"],
                1,
                revision["digest"],
                "reviewer",
                Publisher(cfg, httpx.MockTransport(handler)),
                retry=retry,
            )
        assert all(p.attempts == 3 for p in session.scalars(select(Publication)))
    assert len(calls) == 9


def test_test_publisher_signatures_idempotency_and_escaped_page(runtime, tmp_path):
    cfg, _, _ = runtime
    from app.integrations import signed_body

    engine = create_engine(
        f"sqlite:///{tmp_path / 'pub.db'}", connect_args={"check_same_thread": False}
    )
    with TestClient(create_publisher(cfg, engine)) as client:
        payload = {
            "key": "test:website",
            "channel": "website",
            "text": "<script>alert(1)</script>",
            "digest": "a" * 64,
        }
        body, signature = signed_body(cfg.publisher_secret.get_secret_value(), payload)
        assert client.post("/api/posts", content=body).status_code == 401
        for _ in range(2):
            assert (
                client.post(
                    "/api/posts", content=body, headers={"X-Signature": signature}
                ).status_code
                == 200
            )
        assert "&lt;script&gt;" in client.get("/posts/test:website").text
        payload["text"] = "Different content"
        body, signature = signed_body(cfg.publisher_secret.get_secret_value(), payload)
        assert (
            client.post("/api/posts", content=body, headers={"X-Signature": signature}).status_code
            == 409
        )
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        assert len(session.scalars(select(Post)).all()) == 1
    engine.dispose()


def test_publication_performs_real_loopback_http(runtime):
    """Actual network socket test, distinct from MockTransport tests above."""
    cfg, app, client = runtime
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"url":"http://127.0.0.1/posts/real-http-test"}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        configured = cfg.model_copy(
            update={"publisher_url": f"http://127.0.0.1:{server.server_port}"}
        )
        item, revision = new_content(client)
        with app.state.sessions() as session:
            results = content.approve_publish(
                session, configured, item["id"], 1, revision["digest"], "reviewer"
            )
            assert all(p.status == "published" and p.published_at for p in results)
        assert len(received) == 3
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()


def test_uncertain_publish_is_reconciled_without_reposting(runtime):
    cfg, app, client = runtime
    item, revision = new_content(client)
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            raise httpx.ReadTimeout("response lost")
        return httpx.Response(
            200,
            json={
                "external_id": "content:website",
                "url": "http://test/posts/content:website",
                "destination": "local_test",
                "digest": revision["digest"],
            },
        )

    publisher = Publisher(cfg, httpx.MockTransport(handler))
    with app.state.sessions() as session:
        content.approve_publish(
            session, cfg, item["id"], 1, revision["digest"], "reviewer", publisher
        )
        result = content.approve_publish(
            session, cfg, item["id"], 1, revision["digest"], "reviewer", publisher, retry=True
        )
        assert result[0].status == "published"
        assert calls == ["POST"] * 3 + ["GET"] * 3
