"""Check configuration; optionally probe DB, public URL, or one paid LLM call.

No posts are published. DB probes are read-only; LLM usage is stored in memory only.
"""

import argparse
import json
from decimal import Decimal
from time import perf_counter

import httpx
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.ai import LiveProvider
from app.config import Settings
from app.content import check_grounding
from app.db import initialize, make_engine
from app.models import Base, Usage


def database_check(settings):
    engine = create_engine(
        settings.database_url.get_secret_value(), connect_args={"connect_timeout": 8}
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            inspector = inspect(connection)
            missing = []
            for table in Base.metadata.sorted_tables:
                if not inspector.has_table(table.name, schema="content_ops"):
                    missing.append(table.name)
                    continue
                columns = {
                    column["name"] for column in
                    inspector.get_columns(table.name, schema="content_ops")
                }
                missing.extend(
                    f"{table.name}.{column.name}" for column in table.columns
                    if column.name not in columns
                )
            if missing:
                raise RuntimeError("Database schema is incomplete; run scripts.setup_db")
        return {"status": "passed", "schema": "content_ops", "read_only": True}
    finally:
        engine.dispose()


def live_check(settings):
    if settings.provider in {"none", "fixture"}:
        raise RuntimeError("Configure a live LLM provider first")
    configured_budget = Decimal(settings.max_job_cost_usd)
    cfg = settings.model_copy(update={
        "max_llm_calls": 1, "provider_timeout": 30,
        "max_job_cost_usd": str(min(configured_budget, Decimal("0.01"))),
    })
    source = (
        "Fictional testing update: River Research volunteers reviewed a water sampling "
        "checklist. Field testing is planned. No research findings are available yet."
    )
    engine = make_engine("sqlite:///:memory:")
    initialize(engine)
    started = perf_counter()
    try:
        with Session(engine) as session:
            result = LiveProvider(cfg, session, "live-readiness").draft(source)
            drafts = {key: getattr(result, key) for key in ("linkedin", "newsletter", "website")}
            check_grounding(source, drafts)
            session.flush()
            rows = session.scalars(select(Usage)).all()
            return {
                "status": "passed", "provider": cfg.provider, "model": cfg.model_name,
                "elapsed_seconds": round(perf_counter() - started, 2),
                "drafts": drafts, "citation_count": len(result.citations),
                "usage": [{
                    "input_tokens": row.input_tokens, "output_tokens": row.output_tokens,
                    "estimated_usd": str(row.estimated_usd),
                } for row in rows],
                "publication_attempted": False, "storage": "in-memory test database",
            }
    finally:
        engine.dispose()


def public_check(settings):
    if not settings.public_base_url:
        raise RuntimeError("Set PUBLIC_BASE_URL first")
    with httpx.Client(timeout=15, follow_redirects=False) as client:
        response = client.get(
            f"{settings.public_base_url}/api/v1/integrations/make/jobs?limit=1",
            headers={
                "Authorization": f"Bearer {settings.make_api_token.get_secret_value()}",
                "ngrok-skip-browser-warning": "true",
            },
        )
        response.raise_for_status()
        if not isinstance(response.json().get("jobs"), list):
            raise RuntimeError("Public endpoint did not return the Make jobs contract")
    return {"status": "passed", "make_authentication": "verified"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", action="store_true", help="Read-only Supabase schema check")
    parser.add_argument("--public", action="store_true", help="Check the authenticated ngrok URL")
    parser.add_argument("--live", action="store_true", help="One paid LLM call; $0.01 app budget")
    args = parser.parse_args()
    results = {}
    try:
        settings = Settings()
        settings.require_runtime()
        if settings.public_base_url and "YOUR-" in settings.public_base_url.upper():
            raise RuntimeError("Replace the PUBLIC_BASE_URL placeholder with your ngrok origin")
        if settings.publisher_backend == "make" and (
            "REPLACE-" in settings.make_api_token.get_secret_value().upper()
        ):
            raise RuntimeError("Replace the MAKE_API_TOKEN placeholder with a random secret")
        results["configuration"] = {
            "status": "passed", "provider": settings.provider, "model": settings.model_name,
            "publisher_backend": settings.publisher_backend,
            "secure_cookies": settings.secure_cookies,
        }
        if args.database:
            results["database"] = database_check(settings)
        if args.live:
            results["llm"] = live_check(settings)
        if args.public:
            results["public_endpoint"] = public_check(settings)
    except Exception as exc:
        # Never print connection strings, provider response bodies, keys, or stack traces.
        results["failure"] = {"type": type(exc).__name__, "status": "failed"}
        if isinstance(exc, RuntimeError) and type(exc) is RuntimeError:
            results["failure"]["detail"] = str(exc)
        print(json.dumps(results, indent=2))
        return 1
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
