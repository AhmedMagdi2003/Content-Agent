"""Durable, approval-bound jobs claimed by a scheduled Make scenario."""

from sqlalchemy import select, update

from app.errors import Conflict
from app.models import Content, Publication, PublicationAttempt, Revision, now
from app.observability import emit


def guard_edit(session, content_id):
    active = session.scalar(
        select(Publication.id)
        .join(Revision, Publication.revision_id == Revision.id)
        .where(Revision.content_id == content_id, Publication.status == "publishing")
        .limit(1)
    )
    if active:
        raise Conflict("Make is publishing this item; wait for its result before editing")


def invalidate_queued(session, revision_id):
    session.execute(
        update(Publication)
        .where(Publication.revision_id == revision_id, Publication.status == "queued")
        .values(status="cancelled", error="APPROVAL_INVALIDATED")
    )


def enqueue(session, settings, revision):
    enabled = {value.strip() for value in settings.make_channels.split(",")}
    results = []
    for channel in revision.channels:
        key = f"{revision.id}:{channel}"
        publication = session.get(Publication, key)
        if publication is None:
            publication = Publication(
                id=key, revision_id=revision.id, channel=channel, attempts=0,
                status="pending", destination=f"make:{channel}",
            )
            session.add(publication)
        results.append(publication)
        # A lost callback must never lead to a second platform write.
        if publication.status in {"published", "drafted", "queued", "publishing", "uncertain"}:
            continue
        if publication.attempts >= 3:
            continue
        publication.destination = f"make:{channel}"
        if channel not in enabled:
            publication.status, publication.error = "failed", "MAKE_CHANNEL_DISABLED"
        else:
            publication.status, publication.error = "queued", None
        emit(
            session, "integration", "make_enqueue", publication.status,
            resource_id=revision.content_id, channel=channel, revision=revision.number,
            error_code=publication.error,
        )
    return results


def jobs(session, settings, limit=20):
    enabled = [value.strip() for value in settings.make_channels.split(",")]
    rows = session.execute(
        select(Publication, Revision)
        .join(Revision, Publication.revision_id == Revision.id)
        .join(Content, Revision.content_id == Content.id)
        .where(
            Publication.destination.like("make:%"), Publication.status == "queued",
            Publication.channel.in_(enabled),
            Revision.approved_at.is_not(None), Revision.decision == "approved",
            Content.revision == Revision.number,
        )
        .order_by(Content.created_at, Publication.id)
        .limit(limit)
    ).all()
    base = settings.public_base_url
    return [
        {
            "publication_id": publication.id, "channel": publication.channel,
            "digest": revision.digest,
            "claim_url": f"{base}/api/v1/integrations/make/jobs/{publication.id}/claim",
            "result_url": f"{base}/api/v1/integrations/make/jobs/{publication.id}/result",
        }
        for publication, revision in rows
    ]


def locked_job(session, publication_id):
    publication = session.get(Publication, publication_id)
    if publication is None or not publication.destination.startswith("make:"):
        raise Conflict("Make publication not found")
    revision = session.get(Revision, publication.revision_id)
    # Use the same parent lock as editing, approval and other Make workers.
    item = session.scalar(
        select(Content).where(Content.id == revision.content_id).with_for_update()
    )
    session.refresh(publication)
    session.refresh(revision)
    return publication, revision, item


def claim(session, settings, publication_id, digest):
    from app.content import revision_hash

    publication, revision, item = locked_job(session, publication_id)
    if (
        item.revision != revision.number or revision.decision != "approved"
        or not revision.approved_at or revision.digest != digest
        or digest != revision_hash(revision.drafts, revision.channels)
        or publication.channel not in revision.channels
        or publication.channel not in {c.strip() for c in settings.make_channels.split(",")}
    ):
        raise Conflict("Approval changed; this Make job cannot be published")
    claimed = session.execute(
        update(Publication)
        .where(
            Publication.id == publication_id, Publication.status == "queued",
            Publication.attempts < 3,
        )
        .values(status="publishing", attempts=Publication.attempts + 1)
    )
    if claimed.rowcount != 1:
        raise Conflict("Make job already claimed or no longer eligible; do not post")
    session.refresh(publication)
    session.add(PublicationAttempt(
        publication_id=publication.id, attempt=publication.attempts, status="publishing"
    ))
    emit(session, "integration", "make_claim", "publishing", resource_id=item.id,
         channel=publication.channel, attempt=publication.attempts)
    result = {
        "publication_id": publication.id, "idempotency_key": publication.id,
        "content_id": item.id, "revision": revision.number, "digest": digest,
        "channel": publication.channel, "text": revision.drafts[publication.channel],
        "attempt": publication.attempts,
    }
    session.commit()
    return result


def complete(session, publication_id, body):
    publication, revision, item = locked_job(session, publication_id)
    if body.digest != revision.digest or body.attempt != publication.attempts:
        raise Conflict("Result does not match the claimed revision and attempt")
    result_url = str(body.url) if body.url else None
    if body.status == "drafted" and publication.channel != "newsletter":
        raise Conflict("Only newsletter jobs can complete as an email draft")
    if body.status == "published" and publication.channel != "newsletter" and not result_url:
        raise Conflict("Website and LinkedIn results require the actual publication URL")
    if publication.status in {"published", "drafted", "failed"}:
        if (
            publication.status == body.status and publication.external_id == body.external_id
            and publication.url == result_url and publication.error == body.error_code
        ):
            return publication
        raise Conflict("A completed result cannot be overwritten")
    if publication.status not in {"publishing", "uncertain"}:
        raise Conflict("Claim the Make job before reporting its result")
    publication.status = body.status
    publication.external_id = body.external_id
    publication.url = result_url
    publication.error = body.error_code
    publication.published_at = now() if body.status == "published" else None
    attempt = session.scalar(select(PublicationAttempt).where(
        PublicationAttempt.publication_id == publication.id,
        PublicationAttempt.attempt == body.attempt,
    ))
    if attempt:
        attempt.status, attempt.error = body.status, body.error_code
    emit(session, "integration", "make_result", body.status, resource_id=item.id,
         channel=publication.channel, attempt=body.attempt, error_code=body.error_code)
    session.commit()
    return publication
