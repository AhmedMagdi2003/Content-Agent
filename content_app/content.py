"""Approval and publication are deterministic Python operations, never model tools."""

import hashlib
import json
import re
from time import perf_counter
from typing import TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from sqlalchemy import select, update

from content_app.ai import provider_for
from content_app.errors import Conflict
from content_app.integrations import IntegrationError, Publisher
from content_app.models import Content, Publication, Revision, now, uid
from content_app.observability import emit
from content_app.schemas import CHANNELS, Drafts


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


def check_grounding(source, drafts):
    # This catches concrete unsupported claims, not every possible semantic invention.
    # Human fact review is still mandatory before publication.
    source_numbers = set(re.findall(r"\d+(?:[.,]\d+)*", source))
    source_urls = set(re.findall(r"https?://[^\s]+", source))
    for draft in drafts.values():
        if set(re.findall(r"\d+(?:[.,]\d+)*", draft)) - source_numbers:
            raise Conflict(
                "Draft contains numbers absent from the source; revise the input and retry"
            )
        if set(re.findall(r"https?://[^\s]+", draft)) - source_urls:
            raise Conflict("Draft contains a citation/link absent from the source")
        for quote in re.findall(r'[“"]([^”"\n]{8,})[”"]', draft):
            if quote not in source:
                raise Conflict("Draft contains a quote absent from the source")


class ContentState(TypedDict, total=False):
    drafts: Drafts


def generate(session, settings, source, actor, provider=None):
    run_id, started = uid(), perf_counter()
    provider = provider or provider_for(settings, session, run_id)
    item = Content(source=source, id=uid(), revision=1)

    def write_drafts(state):
        return {"drafts": provider.draft(source)}

    def persist(state):
        drafts = state["drafts"].model_dump()
        check_grounding(source, drafts)
        if len(set(drafts.values())) != 3:
            raise Conflict("Provider returned identical drafts")
        session.add(item)
        session.flush()
        session.add(
            Revision(
                id=revision_id(item.id, 1),
                content_id=item.id,
                number=1,
                drafts=drafts,
                channels=list(CHANNELS),
                digest=revision_hash(drafts, CHANNELS),
            )
        )
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
    # Publishing holds this same content lock across its bounded HTTP calls. An edit
    # arriving during publication waits; it cannot silently change the approved payload.
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
    )
    session.add(revision)
    emit(
        session, "human", "revise_content", "approval_required", resource_id=content_id, actor=actor
    )
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
        publication.attempts += 1
        try:
            # Verify again under the content lock, immediately before the HTTP write.
            if not revision.approved_at or revision.digest != digest:
                raise Conflict("Approval invalidated")
            url = publisher.publish(key, channel, revision.drafts[channel], digest)
            publication.status, publication.url = "published", url
            publication.published_at, publication.error = now(), None
        except (IntegrationError, httpx.HTTPError, ValueError) as exc:
            publication.status = "failed"
            publication.error = str(exc) if isinstance(exc, IntegrationError) else "PUBLISH_FAILED"
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
