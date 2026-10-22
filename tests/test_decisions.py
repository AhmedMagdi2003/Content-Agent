from sqlalchemy import create_engine, text

from app.db import initialize


def test_rejection_blocks_publication_until_new_revision(runtime):
    _, _, client = runtime
    item = client.post(
        "/api/v1/content", json={"source": "The fictional team reviewed its protocol."}
    ).json()
    endpoint = f"/api/v1/content/{item['id']}"
    revision = client.get(endpoint).json()["revisions"][0]
    response = client.post(
        endpoint + "/reject",
        json={
            "revision": 1,
            "justification": "The draft needs a clearer explanation before publication.",
        },
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "rejected"
    assert (
        client.post(
            endpoint + "/approve-and-publish", json={"revision": 1, "digest": revision["digest"]}
        ).status_code
        == 409
    )
    assert client.get(endpoint).json()["publications"] == []
    updated = client.put(
        endpoint, json={"revision": 1, "drafts": revision["drafts"], "channels": ["website"]}
    )
    assert updated.json()["decision"] == "draft"
    assert (
        client.post(
            endpoint + "/reject",
            json={"revision": 1, "justification": "This stale revision cannot be rejected."},
        ).status_code
        == 409
    )


def test_additive_migration_preserves_approved_revision(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    # Simulate the previous schema with an approved revision to verify migration.
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE content_revisions (id TEXT PRIMARY KEY, "
                "content_id TEXT, number INTEGER, drafts JSON, digest TEXT, channels JSON, "
                "approved_by TEXT, approved_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO content_revisions VALUES "
                "('old:1','old',1,'{}','hash','[]','reviewer','2026-10-21 10:00:00')"
            )
        )
    initialize(engine)
    initialize(engine)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT decision,approved_by FROM content_revisions")).one()
        assert row == ("approved", "reviewer")
    engine.dispose()
