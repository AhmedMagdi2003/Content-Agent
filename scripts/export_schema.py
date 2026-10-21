"""Export the existing content models as an isolated PostgreSQL initial schema."""

from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateIndex, CreateTable

from content_app.config import APP_ROOT
from content_app.models import Base

if __name__ == "__main__":
    lines = [
        "-- Independent content application; apply only to a dedicated content schema.",
        "CREATE SCHEMA IF NOT EXISTS content_ops;",
    ]
    for table in Base.metadata.sorted_tables:
        lines.append(str(CreateTable(table).compile(dialect=dialect())) + ";")
        for index in sorted(table.indexes, key=lambda item: item.name):
            lines.append(str(CreateIndex(index).compile(dialect=dialect())) + ";")
        lines.append(f'ALTER TABLE content_ops."{table.name}" ENABLE ROW LEVEL SECURITY;')
    output = APP_ROOT / "migrations/001_initial.sql"
    output.parent.mkdir(exist_ok=True)
    rendered = "\n\n".join(lines)
    output.write_text(
        "\n".join(line.rstrip() for line in rendered.splitlines()) + "\n", encoding="utf-8"
    )
    print("Content-only PostgreSQL schema exported; no cloud migration executed.")
