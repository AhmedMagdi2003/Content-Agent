"""Existing approval/publish smoke flow adapted to the independent app on port 8001."""

import json
from time import perf_counter

import httpx

from content_app.config import APP_ROOT, Settings


def run():
    cfg = Settings()
    if cfg.mode != "demo" or cfg.provider != "fixture":
        raise RuntimeError("This smoke demo requires explicit content fixture mode")
    output = APP_ROOT / "sample_outputs"
    output.mkdir(exist_ok=True)
    source = (APP_ROOT / "tests/fixtures/project-update.txt").read_text(encoding="utf-8")
    started = perf_counter()
    with httpx.Client(
        base_url="http://127.0.0.1:8001",
        timeout=90,
        headers={"Authorization": f"Bearer {cfg.reviewer_token.get_secret_value()}"},
    ) as client:
        response = client.post("/api/v1/content", json={"source": source})
        response.raise_for_status()
        item = response.json()
        endpoint = f"/api/v1/content/{item['id']}"
        original = client.get(endpoint).json()["revisions"][0]
        assert client.get(endpoint).json()["publications"] == []
        assert (
            client.post(
                endpoint + "/retry", json={"revision": 1, "digest": original["digest"]}
            ).status_code
            == 409
        )
        drafts = original["drafts"]
        drafts["website"] += "\n\nPrepared for the fictional project workspace."
        response = client.put(
            endpoint, json={"revision": 1, "drafts": drafts, "channels": ["website", "linkedin"]}
        )
        response.raise_for_status()
        revision = response.json()
        assert (
            client.post(
                endpoint + "/approve-and-publish",
                json={"revision": 1, "digest": original["digest"]},
            ).status_code
            == 409
        )
        approved = client.post(
            endpoint + "/approve-and-publish", json={"revision": 2, "digest": revision["digest"]}
        )
        approved.raise_for_status()
        publications = approved.json()
        assert {p["channel"] for p in publications} == {"website", "linkedin"}
        assert all(p["status"] == "published" and p["published_at"] for p in publications), (
            publications
        )
        repeated = client.post(
            endpoint + "/retry", json={"revision": 2, "digest": revision["digest"]}
        )
        assert repeated.status_code == 200 and all(p["attempts"] == 1 for p in repeated.json())
        with httpx.Client(timeout=10) as public:
            for publication in publications:
                page = public.get(publication["url"])
                page.raise_for_status()
                assert "LOCAL TEST" in page.text
        updated = client.put(
            endpoint, json={"revision": 2, "drafts": drafts, "channels": ["website", "linkedin"]}
        )
        updated.raise_for_status()
        assert (
            client.post(
                endpoint + "/retry", json={"revision": 2, "digest": revision["digest"]}
            ).status_code
            == 409
        )
        assert (
            client.post(
                endpoint + "/retry", json={"revision": 3, "digest": updated.json()["digest"]}
            ).status_code
            == 409
        )
        details = client.get(endpoint).json()
        for name, value in [
            ("three-channel-drafts.json", {"source": source, **revision}),
            ("publication-log.json", publications),
            ("revision-history.json", details),
        ]:
            (output / name).write_text(json.dumps(value, indent=2), encoding="utf-8")
        evidence = {
            "base_url": "http://127.0.0.1:8001",
            "finance_running_required": False,
            "ai_inference": False,
            "publisher": "real HTTP to local test API",
            "content_id": item["id"],
            "approved_revision": 2,
            "approved_digest": revision["digest"],
            "current_revision": 3,
            "selected_channels": ["website", "linkedin"],
            "content_url": f"http://127.0.0.1:8001/content/{item['id']}",
            "published_urls": [p["url"] for p in publications],
            "request_id": approved.headers.get("x-request-id"),
            "elapsed_seconds": round(perf_counter() - started, 3),
        }
        (output / "smoke-evidence.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
    print("PASS: independent content generation, edit, approval, HTTP publishing and invalidation.")
    print("Fictional outputs saved in content-agent/sample_outputs; no live model call claimed.")


if __name__ == "__main__":
    run()
