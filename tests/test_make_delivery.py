from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.integrations import Publisher
from app.web import create_app

SOURCE = "A fictional research team reviewed a sampling checklist; field testing is planned."
ROOT = "/api/v1/integrations/make/jobs"


def make_runtime(runtime):
    cfg, app, client = runtime
    cfg.publisher_backend = "make"
    cfg.public_base_url = "https://content.example.test"
    cfg.make_api_token = SecretStr("make-test-" + "a" * 40)
    cfg.secure_cookies = True
    headers = {"Authorization": f"Bearer {cfg.make_api_token.get_secret_value()}"}
    return cfg, app, client, headers


def draft_and_approve(client):
    item = client.post("/api/v1/content", json={"source": SOURCE}).json()
    base = f"/api/v1/content/{item['id']}"
    revision = client.get(base).json()["revisions"][0]
    edited = client.put(base, json={
        "revision": 1, "drafts": revision["drafts"], "channels": ["linkedin", "website"],
    }).json()
    approval = {"revision": 2, "digest": edited["digest"]}
    response = client.post(f"{base}/approve-and-publish", json=approval)
    assert response.status_code == 200
    return base, edited, approval, response.json()


def claim(client, headers, publication, digest):
    return client.post(f"{ROOT}/{publication['id']}/claim", headers=headers,
                       json={"digest": digest})


def complete(client, headers, publication, digest, attempt, **fields):
    return client.post(f"{ROOT}/{publication['id']}/result", headers=headers,
                       json={"digest": digest, "attempt": attempt, **fields})


def test_make_queue_is_approval_gated_and_has_separate_auth(runtime, monkeypatch):
    cfg, app, client, headers = make_runtime(runtime)

    def forbidden(*args):
        raise AssertionError("Make approval must never call the synchronous publisher")

    monkeypatch.setattr(Publisher, "publish", forbidden)
    item = client.post("/api/v1/content", json={"source": SOURCE}).json()
    assert client.get(ROOT, headers=headers).json() == {"jobs": []}
    assert client.get(ROOT).status_code == 401  # Reviewer token is not the integration token.
    assert client.post("/api/v1/content", json={"source": SOURCE},
                       headers=headers).status_code == 401
    revision = client.get(f"/api/v1/content/{item['id']}").json()["revisions"][0]
    assert revision["channels"] == ["linkedin", "website"]
    assert claim(client, headers, {"id": f"{revision['id']}:website"},
                 revision["digest"]).status_code == 409
    edited = client.put(f"/api/v1/content/{item['id']}", json={
        "revision": 1, "drafts": revision["drafts"],
        "channels": ["linkedin", "website", "newsletter"],
    }).json()
    response = client.post(f"/api/v1/content/{item['id']}/approve-and-publish", json={
        "revision": 2, "digest": edited["digest"],
    })
    assert response.status_code == 200
    rows = {row["channel"]: row for row in response.json()}
    assert rows["newsletter"]["error"] == "MAKE_CHANNEL_DISABLED"
    assert rows["website"]["status"] == rows["linkedin"]["status"] == "queued"
    jobs = client.get(ROOT, headers=headers).json()["jobs"]
    assert len(jobs) == 2
    assert all("text" not in job and "token" not in str(job) for job in jobs)
    assert jobs[0]["claim_url"].startswith(cfg.public_base_url)
    assert client.get(f"{ROOT}?limit=101", headers=headers).status_code == 422


def test_claim_once_then_publish_callback_is_idempotent(runtime):
    _, _, client, headers = make_runtime(runtime)
    base, revision, approval, publications = draft_and_approve(client)
    publication = publications[0]
    digest = revision["digest"]
    assert claim(client, headers, publication, "0" * 64).status_code == 409
    response = claim(client, headers, publication, digest)
    assert response.status_code == 200
    job = response.json()
    assert job["text"] == revision["drafts"][publication["channel"]]
    assert job["attempt"] == 1
    assert claim(client, headers, publication, digest).status_code == 409
    edit = {"revision": 2, "drafts": revision["drafts"], "channels": ["website"]}
    assert client.put(base, json=edit).status_code == 409
    assert client.post(f"{base}/generate", json={"revision": 2}).status_code == 409
    assert complete(client, headers, publication, digest, 1,
                    status="published").status_code == 422
    assert complete(client, headers, publication, digest, 1, status="published",
                    external_id="actual-platform-id").status_code == 409
    result = {"status": "published", "external_id": "actual-platform-id",
              "url": "https://platform.example.test/posts/actual-platform-id"}
    assert complete(client, headers, publication, digest, 2, **result).status_code == 409
    response = complete(client, headers, publication, digest, 1, **result)
    assert response.status_code == 200
    assert response.json()["published_at"]
    repeated = complete(client, headers, publication, digest, 1, **result)
    # SQLite drops timezone metadata on reload; the stored instant must not change.
    assert datetime.fromisoformat(repeated.json()["published_at"]).replace(tzinfo=None) == (
        datetime.fromisoformat(response.json()["published_at"]).replace(tzinfo=None)
    )
    assert complete(client, headers, publication, digest, 1, status="failed",
                    error_code="PLATFORM_401").status_code == 409
    assert client.post(f"{base}/retry", json=approval).json()[0]["status"] == "published"


def test_edit_or_regenerate_cancels_waiting_jobs(runtime):
    _, _, client, headers = make_runtime(runtime)
    base, revision, _, publications = draft_and_approve(client)
    edit = {"revision": 2, "drafts": revision["drafts"], "channels": ["website"]}
    assert client.put(base, json=edit).status_code == 200
    assert client.get(ROOT, headers=headers).json()["jobs"] == []
    assert claim(client, headers, publications[0], revision["digest"]).status_code == 409
    assert {p["status"] for p in client.get(base).json()["publications"]} == {"cancelled"}
    _, revision, _, publications = draft_and_approve(client)
    other_base = f"/api/v1/content/{publications[0]['revision_id'].rsplit(':', 1)[0]}"
    assert client.post(f"{other_base}/generate", json={"revision": 2}).status_code == 200
    assert client.get(ROOT, headers=headers).json()["jobs"] == []


def test_partial_failure_retry_preserves_success_and_rejects_old_callback(runtime):
    _, _, client, headers = make_runtime(runtime)
    base, revision, approval, publications = draft_and_approve(client)
    rows = {p["channel"]: p for p in publications}
    digest = revision["digest"]
    for channel, publication in rows.items():
        assert claim(client, headers, publication, digest).status_code == 200
        result = (
            {"status": "published", "external_id": "website-post",
             "url": "https://website.example.test/posts/website-post"}
            if channel == "website" else
            {"status": "failed", "error_code": "PLATFORM_401"}
        )
        assert complete(client, headers, publication, digest, 1, **result).status_code == 200
    response = client.post(f"{base}/retry", json=approval)
    assert response.status_code == 200
    jobs = client.get(ROOT, headers=headers).json()["jobs"]
    assert [j["channel"] for j in jobs] == ["linkedin"]
    linkedin = rows["linkedin"]
    assert claim(client, headers, linkedin, digest).json()["attempt"] == 2
    assert complete(client, headers, linkedin, digest, 1, status="failed",
                    error_code="PLATFORM_401").status_code == 409
    assert complete(client, headers, linkedin, digest, 2, status="published",
                    external_id="linkedin-post",
                    url="https://platform.example.test/posts/linkedin-post").status_code == 200
    website = next(p for p in client.get(base).json()["publications"] if p["channel"] == "website")
    assert website["attempts"] == 1


def test_uncertain_result_waits_for_reconciliation_and_retry_ceiling(runtime):
    _, _, client, headers = make_runtime(runtime)
    base, revision, approval, publications = draft_and_approve(client)
    publication, other = publications
    digest = revision["digest"]
    assert claim(client, headers, publication, digest).status_code == 200
    assert complete(client, headers, publication, digest, 1, status="uncertain",
                    error_code="PLATFORM_TIMEOUT").status_code == 200
    for attempt in range(1, 4):
        assert claim(client, headers, other, digest).json()["attempt"] == attempt
        assert complete(client, headers, other, digest, attempt, status="failed",
                        error_code="PLATFORM_503").status_code == 200
        assert client.post(f"{base}/retry", json=approval).status_code == 200
    assert client.get(ROOT, headers=headers).json()["jobs"] == []
    assert claim(client, headers, publication, digest).status_code == 409
    assert claim(client, headers, other, digest).status_code == 409
    assert complete(client, headers, publication, digest, 1, status="published",
                    external_id="found-after-timeout",
                    url="https://platform.example.test/posts/found").status_code == 200


def test_make_jobs_survive_app_restart_and_disabled_channels_cannot_be_claimed(runtime):
    cfg, _, client, headers = make_runtime(runtime)
    _, revision, _, publications = draft_and_approve(client)
    with TestClient(create_app(cfg)) as restarted:
        assert len(restarted.get(ROOT, headers=headers).json()["jobs"]) == 2
    cfg.make_channels = "website"
    jobs = client.get(ROOT, headers=headers).json()["jobs"]
    assert [j["channel"] for j in jobs] == ["website"]
    linkedin = next(p for p in publications if p["channel"] == "linkedin")
    assert claim(client, headers, linkedin, revision["digest"]).status_code == 409


def test_two_make_workers_cannot_claim_the_same_publication(runtime):
    _, _, client, headers = make_runtime(runtime)
    _, revision, _, publications = draft_and_approve(client)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(claim, client, headers, publications[0], revision["digest"])
                   for _ in range(2)]
        statuses = sorted(future.result().status_code for future in futures)
    assert statuses == [200, 409]


def test_newsletter_draft_is_not_reported_as_published_or_retried(runtime):
    cfg, _, client, headers = make_runtime(runtime)
    cfg.make_channels = "linkedin,website,newsletter"
    item = client.post("/api/v1/content", json={"source": SOURCE}).json()
    base = f"/api/v1/content/{item['id']}"
    revision = client.get(base).json()["revisions"][0]
    saved = client.put(base, json={
        "revision": 1, "drafts": revision["drafts"], "channels": ["newsletter"],
    }).json()
    approval = {"revision": 2, "digest": saved["digest"]}
    publication = client.post(f"{base}/approve-and-publish", json=approval).json()[0]
    assert claim(client, headers, publication, saved["digest"]).status_code == 200
    result = {"status": "drafted", "external_id": "actual-gmail-draft-id"}
    response = complete(client, headers, publication, saved["digest"], 1, **result)
    assert response.status_code == 200
    assert response.json()["status"] == "drafted"
    assert response.json()["published_at"] is None
    assert complete(client, headers, publication, saved["digest"], 1,
                    **result).status_code == 200
    assert client.post(f"{base}/retry", json=approval).json()[0]["status"] == "drafted"
    assert client.get(ROOT, headers=headers).json()["jobs"] == []

    _, revision, _, publications = draft_and_approve(client)
    publication = publications[0]
    assert claim(client, headers, publication, revision["digest"]).status_code == 200
    assert complete(client, headers, publication, revision["digest"], 1,
                    **result).status_code == 409


@pytest.mark.parametrize("url", ["http://example.test", "https://user:secret@example.test",
                                 "https://example.test/path", "https://example.test?q=secret"])
def test_make_requires_an_https_origin(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, public_base_url=url)
