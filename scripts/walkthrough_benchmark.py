"""Prepare and audit real benchmark runs; never approves or publishes content."""

import argparse
import json
from pathlib import Path
from time import perf_counter

import httpx

from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "ImpactCircles_Content_Agent_Benchmark" / "BENCHMARK_FIXTURES.json"
OUTPUT = ROOT / "data" / "walkthrough"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=["S1W1", "S1W2", "S2", "S3"])
    parser.add_argument("--audit-edit", action="store_true")
    args = parser.parse_args()
    fixture = next(s for s in json.loads(FIXTURES.read_text(encoding="utf-8"))["scenarios"]
                   if s["scenario_id"] == args.scenario)
    cfg = Settings()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / f"{args.scenario}.json"
    with httpx.Client(
        base_url="http://127.0.0.1:8001", timeout=120,
        headers={"Authorization": f"Bearer {cfg.reviewer_token.get_secret_value()}"},
    ) as client:
        report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
            "scenario": args.scenario, "project_slug": fixture["project_slug"],
            "fictional": True, "generation_attempts": [],
        }
        if not report.get("content_id"):
            started = perf_counter()
            response = client.post("/api/v1/content", json={
                "source": fixture["raw_input"], "project_slug": fixture["project_slug"],
                "content_type": "research_finding" if args.scenario in {"S2", "S3"}
                else "project_update", "enable_web_search": args.scenario == "S2",
                "search_query": "site:coralreefwatch.noaa.gov Degree Heating Weeks",
            })
            report["generation_attempts"].append({
                "status": response.status_code, "seconds": round(perf_counter() - started, 2),
            })
            if response.status_code != 200:
                report["generation_error"] = response.json()
                path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
                print(json.dumps(report, ensure_ascii=True))
                return
            report["content_id"] = response.json()["id"]
        base = f"/api/v1/content/{report['content_id']}"
        detail = client.get(base).raise_for_status().json()
        rev = next(r for r in detail["revisions"] if r["number"] == detail["content"]["revision"])
        if args.audit_edit and "adversarial_edit" not in report:
            bad = dict(rev["drafts"])
            bad["linkedin"] = fixture["adversarial_draft"]
            response = client.put(base, json={
                "revision": rev["number"], "drafts": bad, "channels": rev["channels"],
            })
            report["adversarial_edit"] = {
                "expected_status": 409, "actual_status": response.status_code,
                "passed": response.status_code == 409,
                "reason": fixture["expected_rejection_reason"],
                "published": False,
            }
            if response.status_code == 200:
                restored = client.put(base, json={
                    "revision": response.json()["number"],
                    "drafts": rev["drafts"], "channels": rev["channels"],
                })
                restored.raise_for_status()
                report["adversarial_edit"]["restored_revision"] = restored.json()["number"]
            detail = client.get(base).raise_for_status().json()
            rev = next(r for r in detail["revisions"]
                       if r["number"] == detail["content"]["revision"])
        prefix = "FICTIONAL BENCHMARK DEMO — not real research.\n\n"
        if not rev["drafts"]["linkedin"].startswith(prefix):
            drafts = {channel: prefix + text for channel, text in rev["drafts"].items()}
            response = client.put(base, json={
                "revision": rev["number"], "drafts": drafts,
                "channels": ["linkedin", "newsletter"],
            })
            response.raise_for_status()
            rev = response.json()
            report["human_review_required"] = True
        report.update({
            "revision": rev["number"], "digest": rev["digest"],
            "drafts": rev["drafts"], "citations": rev.get("citations", []),
            "url": cfg.public_base_url + f"/content/{report['content_id']}",
            "retrieval": {
                "past_posts": len(
                    detail["content"].get("sources_context", {}).get("past_posts", [])
                ),
                "given_links": [
                    {k: link.get(k) for k in ("url", "status", "title", "chars")}
                    for link in detail["content"].get("sources_context", {}).get("given_links", [])
                ],
                "web_search_results": len(
                    detail["content"].get("sources_context", {}).get("web_search", [])
                ),
            },
            "publications": detail["publications"],
        })
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k not in {"drafts", "citations"}},
                         ensure_ascii=True))
        print("LINKEDIN REVIEW TEXT:\n" + rev["drafts"]["linkedin"].encode(
            "ascii", "backslashreplace"
        ).decode("ascii"))
        print("NEWSLETTER REVIEW TEXT:\n" + rev["drafts"]["newsletter"].encode(
            "ascii", "backslashreplace"
        ).decode("ascii"))


if __name__ == "__main__":
    main()
