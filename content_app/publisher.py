"""Separate local test website/social API. Start on port 8011, never production accounts."""

import hashlib
import hmac
import html
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import JSON, String, Text, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from content_app.config import Settings
from content_app.schemas import CHANNELS


class PublisherBase(DeclarativeBase):
    pass


class Post(PublisherBase):
    __tablename__ = "test_posts"
    key: Mapped[str] = mapped_column(String(150), primary_key=True)
    channel: Mapped[str] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON)


class PostInput(BaseModel):
    key: str = Field(min_length=1, max_length=150, pattern=r"^[a-zA-Z0-9:-]+$")
    channel: str
    text: str = Field(min_length=1, max_length=15000)
    digest: str = Field(min_length=64, max_length=64)


def create_publisher(settings=None, engine=None):
    cfg = settings or Settings()
    root = cfg.local_data_dir
    if engine is None:
        root.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            f"sqlite:///{Path(root) / 'publisher.db'}", connect_args={"check_same_thread": False}
        )

    @asynccontextmanager
    async def lifespan(app):
        if len(cfg.publisher_secret.get_secret_value()) < 24:
            raise RuntimeError("Configure CONTENT_PUBLISHER_SECRET (at least 24 random characters)")
        PublisherBase.metadata.create_all(engine)
        yield

    application = FastAPI(title="Local TEST publisher (mock social and CMS)", lifespan=lifespan)

    @application.post("/api/posts")
    async def post(request: Request):
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > 65000:
            raise HTTPException(413, "Body too large")
        body = await request.body()
        if len(body) > 65000:
            raise HTTPException(413, "Body too large")
        expected = hmac.new(
            cfg.publisher_secret.get_secret_value().encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, request.headers.get("x-signature", "")):
            raise HTTPException(401, "Invalid publisher signature")
        try:
            payload = PostInput.model_validate(json.loads(body))
        except ValueError as exc:
            raise HTTPException(422, "Invalid post") from exc
        if payload.channel not in CHANNELS:
            raise HTTPException(422, "Unsupported channel")
        with Session(engine) as session:
            existing = session.get(Post, payload.key)
            if existing and existing.payload != payload.model_dump():
                raise HTTPException(409, "Idempotency key has different content")
            if not existing:
                session.add(
                    Post(
                        key=payload.key,
                        channel=payload.channel,
                        text=payload.text,
                        payload=payload.model_dump(),
                    )
                )
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    existing = session.get(Post, payload.key)
                    if not existing or existing.payload != payload.model_dump():
                        raise HTTPException(409, "Concurrent post conflict") from None
        return {"url": f"{cfg.publisher_url}/posts/{payload.key}", "destination": "local_test"}

    @application.get("/posts/{key}", response_class=HTMLResponse)
    def page(key: str):
        with Session(engine) as session:
            value = session.get(Post, key)
            if not value:
                raise HTTPException(404)
            return (
                "<!doctype html><html lang='en'><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>Local test publication</title><style>body{max-width:760px;"
                "margin:60px auto;padding:24px;font:18px/1.7 system-ui;color:#163b39}"
                "pre{white-space:pre-wrap;font:inherit}</style>"
                f"<p>LOCAL TEST • {html.escape(value.channel)}</p>"
                f"<h1>Published announcement</h1><pre>{html.escape(value.text)}</pre></html>"
            )

    @application.get("/", response_class=HTMLResponse)
    def index():
        with Session(engine) as session:
            links = "".join(
                f'<li><a href="/posts/{html.escape(p.key)}">'
                f"{html.escape(p.channel)} • {html.escape(p.key)}</a></li>"
                for p in session.scalars(select(Post))
            )
        return (
            "<h1>Local test publications</h1><p>Mock CMS and social destinations.</p>"
            f"<ul>{links}</ul>"
        )

    return application


app = create_publisher()
