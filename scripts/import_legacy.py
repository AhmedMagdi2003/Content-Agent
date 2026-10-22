"""Non-destructive transfer of legacy local content records. No finance module imports."""

import argparse
import json
import sqlite3
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, select

from app.config import Settings
from app.db import initialize, make_engine
from app.models import Base


def readonly_engine(path):
    path = Path(path).resolve(strict=True)
    return create_engine(
        "sqlite://",
        creator=lambda: sqlite3.connect(
            path.as_uri() + "?mode=ro", uri=True, check_same_thread=False
        ),
    )


def copy_record(connection, table, row):
    values = {column.name: row[column.name] for column in table.columns if column.name in row}
    if table.name == "content_revisions" and "decision" not in values:
        values["decision"] = "approved" if values.get("approved_at") else "draft"
    primary = list(table.primary_key.columns)[0]
    existing = (
        connection.execute(select(table).where(primary == values[primary.name])).mappings().first()
    )
    if existing:
        if any(existing[name] != value for name, value in values.items()):
            raise ValueError(f"Destination record differs in {table.name}; no overwrite performed")
        return 0
    connection.execute(table.insert().values(**values))
    return 1


def import_content(source_path, target):
    source = readonly_engine(source_path)
    initialize(target)
    counts = {}
    try:
        with source.connect() as source_connection, target.begin() as destination:
            metadata = MetaData()
            tables = {
                name: Table(name, metadata, autoload_with=source_connection)
                for name in (
                    "content_items",
                    "content_revisions",
                    "publications",
                    "events",
                    "llm_usage",
                )
            }
            rows = {
                name: list(source_connection.execute(select(table)).mappings())
                for name, table in tables.items()
            }
            content_ids = {row["id"] for row in rows["content_items"]}
            usage = [row for row in rows["llm_usage"] if row["operation"] == "draft"]
            run_ids = {row["run_id"] for row in usage}
            run_ids |= {
                row["run_id"]
                for row in rows["events"]
                if row["resource_id"] in content_ids and row["run_id"]
            }
            events = [
                row
                for row in rows["events"]
                if row["resource_id"] in content_ids
                or row["run_id"] in run_ids
                or row["stage"] == "content"
                or (row["safe_metadata"] or {})
                .get("path", "")
                .startswith(("/api/v1/content", "/content"))
            ]
            rows["events"], rows["llm_usage"] = events, usage
            for name in (
                "content_items",
                "content_revisions",
                "publications",
                "events",
                "llm_usage",
            ):
                table = Base.metadata.tables[f"content_ops.{name}"]
                counts[name] = {
                    "selected": len(rows[name]),
                    "inserted": sum(copy_record(destination, table, row) for row in rows[name]),
                }
    finally:
        source.dispose()
    return counts


def import_publisher(source_path, target_path):
    from app.publisher import Post, PublisherBase

    source_path = Path(source_path).resolve(strict=True)
    target_path = Path(target_path).resolve()
    if source_path == target_path:
        raise ValueError("Source and destination publisher DB must be different")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source = readonly_engine(source_path)
    target = create_engine(f"sqlite:///{target_path}")
    try:
        PublisherBase.metadata.create_all(target)
        with source.connect() as original, target.begin() as destination:
            table = Table("test_posts", MetaData(), autoload_with=original)
            rows = list(original.execute(select(table)).mappings())
            return {
                "selected": len(rows),
                "inserted": sum(copy_record(destination, Post.__table__, row) for row in rows),
            }
    finally:
        source.dispose()
        target.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sqlite", type=Path, required=True)
    parser.add_argument("--publisher-sqlite", type=Path)
    args = parser.parse_args()
    cfg = Settings()
    cfg.require_runtime()
    target = make_engine(cfg.database_url.get_secret_value())
    if target.url.database and Path(target.url.database).resolve() == args.source_sqlite.resolve():
        raise RuntimeError("Source and destination content databases must be different")
    report = {"content": import_content(args.source_sqlite, target), "source_modified": False}
    if args.publisher_sqlite:
        report["publisher"] = import_publisher(
            args.publisher_sqlite, cfg.local_data_dir / "publisher.db"
        )
    target.dispose()
    print(json.dumps(report, indent=2))
