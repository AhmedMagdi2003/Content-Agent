"""One persistence model; SQLAlchemy NUMERIC keeps money exact on PostgreSQL."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, MetaData, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return str(uuid4())


def now():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(schema="content_ops")


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    stage: Mapped[str] = mapped_column(String(80))
    operation: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40))
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    safe_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class Usage(Base):
    __tablename__ = "llm_usage"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(String(50))
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_usd: Mapped[Decimal | None] = mapped_column(Numeric(16, 8), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class Content(Base):
    __tablename__ = "content_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    source: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    project_slug: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    content_type: Mapped[str] = mapped_column(
        String(50), default="project_update", server_default="project_update"
    )
    sources_context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Revision(Base):
    __tablename__ = "content_revisions"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    content_id: Mapped[str] = mapped_column(ForeignKey("content_items.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    drafts: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    channels: Mapped[list] = mapped_column(JSON)
    decision: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft")
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    citations: Mapped[list | None] = mapped_column(JSON, default=list, nullable=True)


class Publication(Base):
    __tablename__ = "publications"
    id: Mapped[str] = mapped_column(String(150), primary_key=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("content_revisions.id"), index=True)
    channel: Mapped[str] = mapped_column(String(40))
    destination: Mapped[str] = mapped_column(String(80), default="local_test")
    status: Mapped[str] = mapped_column(String(30), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    external_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(120), nullable=True)


class PublicationAttempt(Base):
    __tablename__ = "publication_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    publication_id: Mapped[str] = mapped_column(ForeignKey("publications.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
