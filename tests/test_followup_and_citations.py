import pytest

from app import content
from app.errors import Conflict
from app.research import assemble_context, extract_urls


def test_url_extraction_and_cleaning():
    text = (
        "Check our protocol at https://example.com/protocol.html "
        "and code at https://github.com/org/repo."
    )
    urls = extract_urls(text)
    assert "https://example.com/protocol.html" in urls
    assert "https://github.com/org/repo" in urls
    assert not any(u.endswith(".") for u in urls)


def test_context_assembly_with_project_and_links():
    context, meta = assemble_context(
        source_brief="Week 2: Completed field test in Upper River.",
        project_name="river-sampling",
        past_milestones=[{"date": "2026-10-15", "title": "Field checklist finalized"}],
        past_posts=[{"created_at": "2026-10-15", "source": "Week 1: Checklist finalized."}],
        given_links_content=[
            {
                "url": "https://example.com/protocol",
                "title": "Water Protocol",
                "text": "Turbidity sensors require calibration at 20 degrees Celsius.",
                "status": "success",
            }
        ],
        web_search_results=[
            {
                "title": "River Standards",
                "url": "https://standards.org/water",
                "snippet": "Target pH range is between 6.5 and 8.5.",
            }
        ],
    )
    assert "PROJECT MEMORY & CONTINUITY CONTEXT: river-sampling" in context
    assert "Field checklist finalized" in context
    assert "CURRENT SOURCE UPDATE (THIS WEEK'S NEW FACTS):" in context
    assert "Turbidity sensors require calibration" in context
    assert "Target pH range is between 6.5 and 8.5" in context
    assert meta["project_name"] == "river-sampling"


def test_project_followup_and_cumulative_achievements(runtime):
    cfg, app, client = runtime

    # Week 1 Post
    w1_res = client.post(
        "/api/v1/content",
        json={
            "source": "Week 1: River team completed the initial water protocol.",
            "project_slug": "river-study",
        },
    )
    assert w1_res.status_code == 200
    item1 = w1_res.json()
    assert item1["project_slug"] == "river-study"

    # Verify project listing API
    p_list = client.get("/api/v1/projects").json()
    assert len(p_list) >= 1
    proj = next(p for p in p_list if p["project_slug"] == "river-study")
    assert proj["post_count"] == 1

    # Week 2 Post with follow-up awareness
    w2_res = client.post(
        "/api/v1/content",
        json={
            "source": "Week 2: River team deployed turbidity sensors in the upper basin.",
            "project_slug": "river-study",
        },
    )
    assert w2_res.status_code == 200
    item2 = w2_res.json()
    assert item2["project_slug"] == "river-study"

    # Verify project details API
    proj_details = client.get("/api/v1/projects/river-study").json()
    assert proj_details["post_count"] == 2
    assert len(proj_details["posts"]) == 2


def test_citations_attached_to_generated_revision(runtime):
    cfg, app, client = runtime
    source_text = "The lab measured 45 milligrams per liter of dissolved oxygen."
    res = client.post(
        "/api/v1/content",
        json={"source": source_text},
    )
    assert res.status_code == 200
    item = res.json()

    status = client.get(f"/api/v1/content/{item['id']}").json()
    rev = status["revisions"][0]
    assert "citations" in rev
    assert len(rev["citations"]) >= 1
    cit = rev["citations"][0]
    assert "block_id" in cit
    assert "claim" in cit
    assert "source_quote" in cit
    assert cit["source_type"] == "source_brief"


def test_grounding_rejects_hallucinated_metrics_and_quotes():
    source = "The laboratory protocol was updated for seasonal testing."
    # 1. Hallucinated number
    with pytest.raises(Conflict, match="Draft contains numbers absent from the source"):
        content.check_grounding(source, {"website": "The team achieved 99% accuracy."})

    # 2. Hallucinated URL
    with pytest.raises(Conflict, match="Draft contains a citation/link absent from the source"):
        content.check_grounding(
            source, {"website": "Read more at https://hallucinated-site.org/docs"}
        )

    # 3. Hallucinated Quote
    with pytest.raises(Conflict, match="Draft contains a quote absent from the source"):
        content.check_grounding(
            source, {"website": 'The director stated "This changes everything for science".'}
        )


def test_grounding_accepts_verified_inspected_links():
    source = "The team published their findings online."
    sources_meta = {
        "given_links": [
            {
                "url": "https://example.com/findings",
                "title": "Findings",
                "text": "We observed 42 distinct micro-organism colonies.",
            }
        ]
    }
    # Using number 42 and url from inspected link passes grounding check
    drafts = {
        "website": (
            "As published at https://example.com/findings, the team observed 42 distinct colonies."
        )
    }
    # Should not raise
    content.check_grounding(source, drafts, sources_metadata=sources_meta)
