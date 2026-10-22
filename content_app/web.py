import hmac
import secrets
from collections import defaultdict
from contextlib import asynccontextmanager, contextmanager
from decimal import Decimal
from pathlib import Path
from time import monotonic, perf_counter
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from content_app import content
from content_app.ai import ProviderError
from content_app.config import Settings
from content_app.db import initialize, make_engine, query_metrics
from content_app.errors import Conflict
from content_app.integrations import IntegrationError
from content_app.models import (
    Content,
    Event,
    Publication,
    Revision,
    Usage,
    uid,
)
from content_app.observability import cost_summary, current_request, emit
from content_app.schemas import (
    ApprovalInput,
    ContentInput,
    GenerateInput,
    RejectionInput,
    RevisionInput,
)

ROOT = Path(__file__).parent


def record(value):
    return jsonable_encoder(
        {col.name: getattr(value, col.name) for col in value.__table__.columns},
        custom_encoder={Decimal: str},
    )


def create_app(settings=None, engine=None):
    cfg = settings or Settings()
    if cfg.database_url.get_secret_value():
        cfg.require_runtime()
        engine = engine or make_engine(cfg.database_url.get_secret_value())
    sessions = sessionmaker(engine, expire_on_commit=False) if engine is not None else None
    @asynccontextmanager
    async def lifespan(app):
        if engine is not None:
            initialize(engine)
        yield

    application = FastAPI(title="Content Agent", version="0.1.0", lifespan=lifespan)
    application.state.settings, application.state.engine = cfg, engine
    application.state.sessions = sessions
    application.add_middleware(
        SessionMiddleware,
        secret_key=cfg.session_secret.get_secret_value() or secrets.token_hex(32),
        https_only=cfg.secure_cookies,
        same_site="strict",
        max_age=3600,
        session_cookie="content_session",
    )
    templates = Jinja2Templates(directory=str(ROOT / "templates"))
    application.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
    attempts = defaultdict(list)

    def db():
        if sessions is None:
            raise HTTPException(503, "Configure the database and run the setup command first")
        with sessions() as session:
            try:
                yield session
            except Exception:
                session.rollback()
                raise

    def authenticated(request: Request):
        expected = cfg.reviewer_token.get_secret_value()
        if not expected:
            raise HTTPException(503, "Reviewer authentication is not configured")
        authorization = request.headers.get("authorization", "")
        if authorization.startswith("Bearer "):
            if hmac.compare_digest(authorization[7:], expected):
                return "demo-reviewer" if cfg.mode == "demo" else "internal-reviewer"
            raise HTTPException(401, "Invalid API token")
        if not request.session.get("reviewer"):
            raise HTTPException(401, "Sign in to continue")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if not hmac.compare_digest(
                request.headers.get("x-csrf-token", ""), request.session.get("csrf", "invalid")
            ):
                raise HTTPException(403, "Invalid CSRF token")
        return request.session["reviewer"]

    DB = Annotated[Session, Depends(db)]
    Actor = Annotated[str, Depends(authenticated)]

    @application.middleware("http")
    async def activity(request: Request, call_next):
        request_id, started = uid(), perf_counter()
        request.state.request_id = request_id
        metrics = {"count": 0, "duration_ms": 0, "slow_count": 0}
        token = query_metrics.set(metrics)
        correlation = current_request.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["Cache-Control"] = "no-store"
            if sessions:
                with sessions() as session:
                    emit(
                        session,
                        "http",
                        request.method,
                        str(response.status_code),
                        request_id=request_id,
                        duration_ms=int((perf_counter() - started) * 1000),
                        path=request.url.path,
                        db_queries=metrics["count"],
                        db_duration_ms=round(metrics["duration_ms"], 2),
                        slow_queries=metrics["slow_count"],
                    )
                    if metrics["slow_count"]:
                        emit(
                            session,
                            "database",
                            "slow_query",
                            "warning",
                            request_id=request_id,
                            count=metrics["slow_count"],
                        )
                    session.commit()
            return response
        finally:
            query_metrics.reset(token)
            current_request.reset(correlation)

    @application.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @application.exception_handler(ProviderError)
    @application.exception_handler(IntegrationError)
    async def provider_failure(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @application.exception_handler(httpx.HTTPError)
    async def transport_failure(request, exc):
        return JSONResponse(
            {"detail": "External service unavailable; check Operations"}, status_code=503
        )

    @application.get("/health")
    def health():
        return {"status": "ok", "service": "content-agent", "configured": sessions is not None}

    @application.get("/api/v1/readiness")
    def readiness(actor: Actor, session: DB):
        session.execute(text("SELECT 1"))
        return {
            "database": "reachable",
            "mode": cfg.mode,
            "provider": cfg.provider,
            "tracing": "disabled" if cfg.tracing_backends == "none" else "unverified",
        }

    @application.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        return templates.TemplateResponse(request, "login.html", {"mode": cfg.mode})

    @application.post("/login")
    def login(request: Request, token: Annotated[str, Form()]):
        host = request.client.host if request.client else "unknown"
        attempts[host] = [t for t in attempts[host] if monotonic() - t < 60]
        if len(attempts[host]) >= 10:
            raise HTTPException(429, "Too many attempts; wait one minute")
        attempts[host].append(monotonic())
        expected = cfg.reviewer_token.get_secret_value()
        if not expected or not hmac.compare_digest(token, expected):
            raise HTTPException(401, "Invalid reviewer token")
        request.session.clear()
        request.session.update(
            reviewer="demo-reviewer" if cfg.mode == "demo" else "internal-reviewer",
            csrf=secrets.token_urlsafe(32),
        )
        return RedirectResponse("/", status_code=303)

    @application.post("/logout")
    def logout(request: Request, actor: Actor):
        request.session.clear()
        return {"status": "signed_out"}

    @contextmanager
    def page_session(request):
        if not request.session.get("reviewer"):
            raise HTTPException(401)
        if sessions is None:
            raise HTTPException(503, "Database is not configured")
        with sessions() as session:
            yield session

    def render(request, template, **context):
        context.update(
            mode=cfg.mode,
            provider=cfg.provider,
            csrf=request.session.get("csrf", ""),
            path=request.url.path,
        )
        return templates.TemplateResponse(request, template, context)

    @application.get("/content", response_class=HTMLResponse)
    def content_page(request: Request):
        if not request.session.get("reviewer"):
            return RedirectResponse("/login", 303)
        with page_session(request) as session:
            return render(
                request,
                "content.html",
                items=session.scalars(select(Content).order_by(Content.created_at.desc())).all(),
            )

    @application.get("/content/{content_id}", response_class=HTMLResponse)
    def content_detail(request: Request, content_id: str):
        if not request.session.get("reviewer"):
            return RedirectResponse("/login", 303)
        with page_session(request) as session:
            item = session.get(Content, content_id)
            if not item:
                raise HTTPException(404)
            revision = session.get(Revision, content.revision_id(item.id, item.revision))
            return render(
                request,
                "content_detail.html",
                item=item,
                revision=revision,
                publications=session.scalars(
                    select(Publication).where(Publication.revision_id == revision.id)
                ).all(),
                history=session.scalars(
                    select(Revision)
                    .where(Revision.content_id == content_id)
                    .order_by(Revision.number.desc())
                ).all(),
            )

    @application.get("/operations", response_class=HTMLResponse)
    def operations(request: Request, q: str = ""):
        if not request.session.get("reviewer"):
            return RedirectResponse("/login", 303)
        with page_session(request) as session:
            query = select(Event).order_by(Event.timestamp.desc()).limit(200)
            if q:
                query = query.where(
                    or_(Event.run_id == q, Event.resource_id == q, Event.request_id == q)
                )
            usage_query = select(Usage)
            if q:
                usage_query = usage_query.where(Usage.run_id == q)
            usage_rows = session.scalars(usage_query).all()
            return render(
                request,
                "operations.html",
                events=session.scalars(query).all(),
                usage=usage_rows,
                costs=cost_summary(usage_rows),
                q=q,
                tracing=cfg.tracing_backends,
            )

    @application.post("/api/v1/content")
    def draft(body: ContentInput, session: DB, actor: Actor):
        return record(content.generate(session, cfg, body.source, actor))

    @application.get("/api/v1/content/{content_id}")
    def content_status(content_id: str, session: DB, actor: Actor):
        item = session.get(Content, content_id)
        if not item:
            raise HTTPException(404)
        return {
            "content": record(item),
            "revisions": [
                record(r)
                for r in session.scalars(select(Revision).where(Revision.content_id == content_id))
            ],
            "publications": [
                record(p)
                for p in session.scalars(
                    select(Publication)
                    .join(Revision, Publication.revision_id == Revision.id)
                    .where(Revision.content_id == content_id)
                )
            ],
        }

    @application.post("/api/v1/content/{content_id}/generate")
    def generate_again(content_id: str, body: GenerateInput, session: DB, actor: Actor):
        return record(content.regenerate(session, cfg, content_id, body.revision, actor))

    @application.put("/api/v1/content/{content_id}")
    def save_drafts(content_id: str, body: RevisionInput, session: DB, actor: Actor):
        return record(
            content.revise(session, content_id, body.revision, body.drafts, body.channels, actor)
        )

    @application.post("/api/v1/content/{content_id}/approve-and-publish")
    def approve(content_id: str, body: ApprovalInput, session: DB, actor: Actor):
        return [
            record(p)
            for p in content.approve_publish(
                session, cfg, content_id, body.revision, body.digest, actor
            )
        ]

    @application.post("/api/v1/content/{content_id}/retry")
    def retry(content_id: str, body: ApprovalInput, session: DB, actor: Actor):
        return [
            record(p)
            for p in content.approve_publish(
                session, cfg, content_id, body.revision, body.digest, actor, retry=True
            )
        ]

    @application.post("/api/v1/content/{content_id}/reject")
    def reject_content(content_id: str, body: RejectionInput, session: DB, actor: Actor):
        return record(content.reject(session, content_id, body.revision, body.justification, actor))

    @application.get("/")
    def home():
        return RedirectResponse("/content", 303)

    return application
