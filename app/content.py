"""Approval and publication are deterministic Python operations, never model tools."""

import hashlib
import json
import re
from time import perf_counter
from typing import Any, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from sqlalchemy import select, update

from app.ai import provider_for
from app.errors import Conflict
from app.integrations import IntegrationError, Publisher
from app.models import Content, Publication, PublicationAttempt, Revision, now, uid
from app.observability import emit
from app.research import assemble_context, extract_urls, scrape_url, search_web
from app.schemas import CHANNELS


def revision_hash(drafts, channels):
    payload = json.dumps(
        {"drafts": drafts, "channels": sorted(channels)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def revision_id(content_id, number):
    return f"{content_id}:{number}"


WORD_NUMBERS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
}


def check_grounding(source, drafts, sources_metadata=None):
    # This catches concrete unsupported claims, not every possible semantic invention.
    # Human fact review is still mandatory before publication.
    all_source_text = source

    def clean_url(u):
        return u.rstrip(".,;!?:)")

    allowed_urls = {clean_url(u) for u in re.findall(r"https?://[^\s]+", source)}
    if sources_metadata:
        for link in sources_metadata.get("given_links", []):
            if link.get("url"):
                allowed_urls.add(clean_url(link["url"]))
            if link.get("text"):
                all_source_text += "\n" + link["text"]
        for res in sources_metadata.get("web_search", []):
            if res.get("url"):
                allowed_urls.add(clean_url(res["url"]))
            if res.get("snippet"):
                all_source_text += "\n" + res["snippet"]
        for m in sources_metadata.get("past_milestones", []):
            all_source_text += "\n" + (m.get("title") or m.get("summary") or "")
        for p in sources_metadata.get("past_posts", []):
            all_source_text += "\n" + (p.get("created_at", "") + " " + p.get("source", ""))

    source_numbers = set(re.findall(r"\d+(?:[.,]\d+)*", all_source_text))
    source_numbers |= {n.replace(",", "") for n in source_numbers}
    for word, digit in WORD_NUMBERS.items():
        if re.search(r"\b" + word + r"\b", all_source_text, re.IGNORECASE):
            source_numbers.add(digit)

    for draft in drafts.values():
        draft_numbers = set(re.findall(r"\d+(?:[.,]\d+)*", draft))
        unsupported = {
            n for n in draft_numbers
            if n not in source_numbers and n.replace(",", "") not in source_numbers
        }
        if unsupported:
            raise Conflict(
                "Draft contains numbers absent from the source; revise the input and retry"
            )
        draft_urls = {clean_url(u) for u in re.findall(r"https?://[^\s]+", draft)}
        if draft_urls - allowed_urls:
            raise Conflict("Draft contains a citation/link absent from the source")
        for quote in re.findall(r'[“"]([^”"\n]{8,})[”"]', draft):
            if quote not in all_source_text:
                raise Conflict("Draft contains a quote absent from the source")


class ContentState(TypedDict, total=False):
    generation: Any
    channel_drafts: dict
    citations: list
    new_achievements: list


def generate(
    session,
    settings,
    source,
    actor,
    provider=None,
    project_slug=None,
    enable_web_search=False,
    search_query=None,
    given_links=None,
):
    run_id, started = uid(), perf_counter()
    provider = provider or provider_for(settings, session, run_id)

    # 1. Project Memory & Past Milestones retrieval
    past_posts, past_milestones = [], []
    if project_slug:
        prior_items = session.scalars(
            select(Content)
            .where(Content.project_slug == project_slug)
            .order_by(Content.created_at.asc())
        ).all()
        for p in prior_items:
            past_posts.append({
                "id": p.id,
                "created_at": p.created_at.strftime("%Y-%m-%d"),
                "source": p.source,
            })
            if p.sources_context and "achievements" in p.sources_context:
                past_milestones.extend(p.sources_context["achievements"])

    # 2. Given Links Scraping
    urls = extract_urls(source)
    if given_links:
        for u in given_links:
            if u and u not in urls:
                urls.append(u)
    scraped_links = [scrape_url(u) for u in urls[:5]] if urls else []

    # 3. Web Search
    search_results = []
    if enable_web_search:
        q = search_query.strip() if search_query and search_query.strip() else source[:120]
        search_results = search_web(q, max_results=3)

    # 4. Context Assembly
    if not project_slug and not scraped_links and not search_results:
        prompt_text = source
        sources_meta = {"source_brief": source}
    else:
        prompt_text, sources_meta = assemble_context(
            source_brief=source,
            project_name=project_slug,
            past_milestones=past_milestones,
            past_posts=past_posts,
            given_links_content=scraped_links,
            web_search_results=search_results,
        )

    item = Content(
        source=source,
        id=uid(),
        revision=1,
        project_slug=project_slug,
        sources_context=sources_meta,
    )

    def write_drafts(state):
        res = provider.draft(prompt_text)
        channel_drafts = {
            "linkedin": res.linkedin,
            "newsletter": res.newsletter,
            "website": res.website,
        }
        citations = [
            c.model_dump() if hasattr(c, "model_dump") else c
            for c in getattr(res, "citations", [])
        ]
        achievements = getattr(res, "new_achievements", [])
        return {
            "generation": res,
            "channel_drafts": channel_drafts,
            "citations": citations,
            "new_achievements": achievements,
        }

    def persist(state):
        channel_drafts = state["channel_drafts"]
        check_grounding(source, channel_drafts, sources_meta)
        if len(set(channel_drafts.values())) != 3:
            raise Conflict("Provider returned identical drafts")
        session.add(item)
        session.flush()
        citations = state.get("citations", [])
        session.add(
            Revision(
                id=revision_id(item.id, 1),
                content_id=item.id,
                number=1,
                drafts=channel_drafts,
                channels=list(CHANNELS),
                digest=revision_hash(channel_drafts, CHANNELS),
                citations=citations,
            )
        )
        if state.get("new_achievements") and sources_meta:
            existing = sources_meta.get("achievements", [])
            for a in state["new_achievements"]:
                existing.append({
                    "date": now().strftime("%Y-%m-%d"),
                    "summary": a,
                    "post_id": item.id,
                })
            sources_meta["achievements"] = existing
            item.sources_context = sources_meta
        return {}

    graph = StateGraph(ContentState)
    graph.add_node("draft", write_drafts)
    graph.add_node("save_revision", persist)
    graph.add_edge(START, "draft")
    graph.add_edge("draft", "save_revision")
    graph.add_edge("save_revision", END)
    try:
        with tracing_context(enabled=False):
            graph.compile().invoke({}, {"recursion_limit": 5})
    except Exception:
        # Persist failed call usage/events while never storing a successful content item.
        emit(
            session,
            "content",
            "generate",
            "failed",
            run_id=run_id,
            duration_ms=int((perf_counter() - started) * 1000),
            error_code="DRAFT_FAILED",
        )
        session.commit()
        raise
    emit(
        session,
        "content",
        "generate",
        "draft",
        run_id=run_id,
        resource_id=item.id,
        actor=actor,
        fixture=settings.provider == "fixture",
        duration_ms=int((perf_counter() - started) * 1000),
    )
    session.commit()
    return item


def revise(session, content_id, expected, drafts, channels, actor):
    item = session.scalar(select(Content).where(Content.id == content_id).with_for_update())
    if not item or item.revision != expected:
        raise Conflict("Stale content revision; reload before editing")
    old = session.get(Revision, revision_id(content_id, expected))
    result = session.execute(
        update(Content)
        .where(Content.id == content_id, Content.revision == expected)
        .values(revision=expected + 1)
    )
    if not result.rowcount:
        session.rollback()
        raise Conflict("Concurrent edit; reload")
    old.approved_at = old.approved_by = None
    if old.decision == "approved":
        old.decision = "invalidated"
    data = drafts.model_dump()
    revision = Revision(
        id=revision_id(content_id, expected + 1),
        content_id=content_id,
        number=expected + 1,
        drafts=data,
        channels=sorted(channels),
        digest=revision_hash(data, channels),
        citations=old.citations if old else [],
    )
    session.add(revision)
    emit(
        session, "human", "revise_content", "approval_required", resource_id=content_id, actor=actor
    )
    session.commit()
    return revision


def regenerate(session, settings, content_id, expected, actor):
    """Generate a bounded replacement revision for an existing submitted item."""
    item = session.scalar(select(Content).where(Content.id == content_id).with_for_update())
    if not item or item.revision != expected:
        raise Conflict("Stale content revision; reload before generating")
    previous = session.get(Revision, revision_id(content_id, expected))
    run_id = uid()
    provider = provider_for(settings, session, run_id)
    try:
        with tracing_context(enabled=False):
            res = provider.draft(item.source)
            channel_drafts = {
                "linkedin": res.linkedin,
                "newsletter": res.newsletter,
                "website": res.website,
            }
            citations = [
                c.model_dump() if hasattr(c, "model_dump") else c
                for c in getattr(res, "citations", [])
            ]
        check_grounding(item.source, channel_drafts, item.sources_context)
        if len(set(channel_drafts.values())) != 3:
            raise Conflict("Provider returned identical drafts")
    except Exception:
        emit(session, "content", "regenerate", "failed", run_id=run_id, resource_id=content_id,
             error_code="DRAFT_FAILED")
        session.commit()
        raise
    item.revision = expected + 1
    previous.approved_at = previous.approved_by = None
    if previous.decision == "approved":
        previous.decision = "invalidated"
    revision = Revision(
        id=revision_id(content_id, expected + 1),
        content_id=content_id,
        number=expected + 1,
        drafts=channel_drafts,
        channels=list(CHANNELS),
        digest=revision_hash(channel_drafts, CHANNELS),
        citations=citations,
    )
    session.add(revision)
    emit(session, "content", "regenerate", "draft", run_id=run_id, resource_id=content_id,
         actor=actor)
    session.commit()
    return revision


def reject(session, content_id, expected, justification, actor):
    item = session.scalar(select(Content).where(Content.id == content_id).with_for_update())
    if not item or item.revision != expected:
        raise Conflict("Content changed; reload before rejecting")
    revision = session.get(Revision, revision_id(content_id, expected))
    if revision.approved_at:
        raise Conflict("Already approved; create a new revision for another decision")
    claimed = session.execute(
        update(Content)
        .where(Content.id == content_id, Content.revision == expected)
        .values(revision=expected)
    )
    if claimed.rowcount != 1:
        raise Conflict("Concurrent edit; reload")
    revision.decision, revision.decision_reason = "rejected", justification
    emit(
        session,
        "human",
        "reject_content",
        "rejected",
        resource_id=content_id,
        actor=actor,
        revision=expected,
        reason_recorded=True,
    )
    session.commit()
    return revision


def approve_publish(
    session, settings, content_id, expected, digest, actor, publisher=None, retry=False
):
    item = session.scalar(select(Content).where(Content.id == content_id).with_for_update())
    if not item or item.revision != expected:
        raise Conflict("Content changed; approve the current revision")
    revision = session.get(Revision, revision_id(content_id, expected))
    if revision.decision == "rejected":
        raise Conflict("This revision was rejected; save a revised draft before approval")
    if revision.digest != digest or digest != revision_hash(revision.drafts, revision.channels):
        raise Conflict("Content hash changed; reload and approve again")
    if retry and not revision.approved_at:
        raise Conflict("This revision has not been approved")
    if not retry:
        revision.approved_at, revision.approved_by = now(), actor
        revision.decision = "approved"
        emit(
            session,
            "human",
            "approve_content",
            "approved",
            resource_id=content_id,
            actor=actor,
            revision=expected,
            digest=digest,
        )
        # The human decision survives a crash during a remote HTTP call.
        session.commit()
    # A saved edit between approval and this lock invalidates the old revision.
    session.expire_all()
    item = session.scalar(select(Content).where(Content.id == content_id).with_for_update())
    if item.revision != expected:
        raise Conflict("Content changed after approval; approve the current revision")
    claimed = session.execute(
        update(Content)
        .where(Content.id == content_id, Content.revision == expected)
        .values(revision=expected)
    )
    if claimed.rowcount != 1:
        session.rollback()
        raise Conflict("Concurrent edit invalidated approval")
    revision = session.get(Revision, revision_id(content_id, expected))
    if not revision.approved_at or revision.digest != digest:
        raise Conflict("Approval invalidated")
    publisher = publisher or Publisher(settings)
    results = []
    for channel in revision.channels:
        key = f"{revision.id}:{channel}"
        publication = session.get(Publication, key)
        if not publication:
            publication = Publication(
                id=key, revision_id=revision.id, channel=channel, status="pending", attempts=0
            )
            session.add(publication)
            session.flush()
        results.append(publication)
        if publication.status == "published" or publication.attempts >= 3:
            continue
        if publication.status == "uncertain":
            reconcile = getattr(publisher, "reconcile", None)
            if reconcile is None:
                continue
            try:
                result = reconcile(key, digest)
            except IntegrationError as exc:
                publication.error = str(exc)
                continue
            if result is None:
                continue
            publication.status = "published"
            publication.destination = result.destination
            publication.external_id = result.external_id
            publication.url = result.url
            publication.published_at, publication.error = now(), None
            continue
        publication.attempts += 1
        try:
            # Verify again under the content lock, immediately before the HTTP write.
            if not revision.approved_at or revision.digest != digest:
                raise Conflict("Approval invalidated")
            result = publisher.publish(key, channel, revision.drafts[channel], digest)
            publication.status = "published"
            publication.destination = result.destination
            publication.external_id = result.external_id
            publication.url = result.url
            publication.published_at, publication.error = now(), None
        except (IntegrationError, httpx.HTTPError, ValueError) as exc:
            code = str(exc) if isinstance(exc, IntegrationError) else "PUBLISH_FAILED"
            publication.status = "uncertain" if code == "PUBLISH_UNCERTAIN" else "failed"
            publication.error = code
        session.add(
            PublicationAttempt(
                publication_id=publication.id,
                attempt=publication.attempts,
                status=publication.status,
                error=publication.error,
            )
        )
        emit(
            session,
            "integration",
            "publish",
            publication.status,
            resource_id=content_id,
            channel=channel,
            revision=expected,
            attempt=publication.attempts,
            error_code=publication.error,
        )
    session.commit()
    return results
