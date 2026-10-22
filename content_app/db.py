"""Existing query instrumentation with an independent, schema-qualified content store."""

from contextvars import ContextVar
from time import perf_counter

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url

from content_app.config import APP_ROOT
from content_app.models import Base

query_metrics: ContextVar[dict | None] = ContextVar("content_query_metrics", default=None)


def make_engine(url):
    parsed = make_url(url)
    kwargs = {"pool_pre_ping": True}
    if parsed.get_backend_name() == "sqlite":
        from pathlib import Path

        if (
            parsed.database
            and parsed.database != ":memory:"
            and not Path(parsed.database).is_absolute()
        ):
            parsed = parsed.set(database=str(APP_ROOT / parsed.database))
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["execution_options"] = {"schema_translate_map": {"content_ops": None}}
    engine = create_engine(parsed, **kwargs)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        if parsed.get_backend_name() == "sqlite":
            connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "before_cursor_execute")
    def before(conn, cursor, statement, parameters, context, executemany):
        context.started_at = perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def after(conn, cursor, statement, parameters, context, executemany):
        metrics = query_metrics.get()
        if metrics is not None:
            elapsed = (perf_counter() - context.started_at) * 1000
            metrics["count"] += 1
            metrics["duration_ms"] += elapsed
            metrics["slow_count"] += int(elapsed > 200)

    return engine


def initialize(engine):
    schema = "content_ops" if engine.dialect.name == "postgresql" else None
    if schema:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS content_ops"))
    else:
        engine = engine.execution_options(schema_translate_map={"content_ops": None})
    Base.metadata.create_all(engine)
    columns = {
        column["name"] for column in inspect(engine).get_columns("content_revisions", schema=schema)
    }
    table = "content_ops.content_revisions" if schema else "content_revisions"
    if "decision" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"ALTER TABLE {table} ADD COLUMN decision VARCHAR(20) NOT NULL DEFAULT 'draft'"
                )
            )
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN decision_reason TEXT"))
            connection.execute(
                text(f"UPDATE {table} SET decision='approved' WHERE approved_at IS NOT NULL")
            )
    if schema:
        publication_columns = {
            column["name"] for column in inspect(engine).get_columns("publications", schema=schema)
        }
        with engine.begin() as connection:
            if "destination" not in publication_columns:
                connection.execute(
                    text(
                        "ALTER TABLE content_ops.publications "
                        "ADD COLUMN destination VARCHAR(80) NOT NULL DEFAULT 'local_test'"
                    )
                )
            if "external_id" not in publication_columns:
                connection.execute(
                    text("ALTER TABLE content_ops.publications ADD COLUMN external_id VARCHAR(150)")
                )
        with engine.begin() as connection:
            for table in Base.metadata.sorted_tables:
                connection.execute(
                    text(f'ALTER TABLE content_ops."{table.name}" ENABLE ROW LEVEL SECURITY')
                )
