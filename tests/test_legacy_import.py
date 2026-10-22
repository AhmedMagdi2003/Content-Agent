import hashlib

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.db import initialize, make_engine
from app.models import Content, Event, Publication, Revision, Usage, now
from scripts.import_legacy import import_content, import_publisher


def test_transfer_preserves_records_and_leaves_source_read_only(tmp_path):
    source_path = tmp_path / "legacy.db"
    original = make_engine(f"sqlite:///{source_path}")
    initialize(original)
    with original.begin() as connection:
        connection.execute(text("CREATE TABLE unrelated_records (id TEXT PRIMARY KEY, value TEXT)"))
        connection.execute(
            text("INSERT INTO unrelated_records VALUES ('keep-legacy', 'preserved')")
        )
    with Session(original) as session:
        session.add(Content(id="legacy", source="Preserved fictional update", revision=1))
        session.flush()
        session.add(
            Revision(
                id="legacy:1",
                content_id="legacy",
                number=1,
                drafts={"website": "Original draft"},
                digest="a" * 64,
                channels=["website"],
                decision="approved",
                approved_by="reviewer",
                approved_at=now(),
            )
        )
        session.flush()
        session.add(
            Publication(
                id="legacy:1:website",
                revision_id="legacy:1",
                channel="website",
                status="published",
                attempts=1,
                url="http://127.0.0.1:8011/posts/legacy:1:website",
            )
        )
        session.add(
            Event(
                stage="content",
                operation="generate",
                status="draft",
                resource_id="legacy",
                run_id="content-run",
                safe_metadata={},
            )
        )
        session.add(
            Event(
                stage="archive",
                operation="confirm",
                status="RECORDED",
                resource_id="unrelated",
                run_id="archive-run",
                safe_metadata={},
            )
        )
        for operation, run in [("draft", "content-run"), ("archive", "archive-run")]:
            session.add(Usage(run_id=run, provider="fake", model="test", operation=operation))
        session.commit()
    original.dispose()
    before = hashlib.sha256(source_path.read_bytes()).hexdigest()
    destination = make_engine(f"sqlite:///{tmp_path / 'content.db'}")
    report = import_content(source_path, destination)
    assert all(entry["inserted"] == 1 for entry in report.values())
    repeated = import_content(source_path, destination)
    assert all(entry["inserted"] == 0 for entry in repeated.values())
    with Session(destination) as session:
        assert session.get(Revision, "legacy:1").approved_by == "reviewer"
        assert session.get(Publication, "legacy:1:website").url.endswith("legacy:1:website")
        assert len(session.scalars(select(Event)).all()) == 1
        assert session.scalar(select(Usage)).operation == "draft"
        session.get(Content, "legacy").source = "New independent content edit"
        session.commit()
    with pytest.raises(ValueError, match="no overwrite"):
        import_content(source_path, destination)
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == before
    with create_engine(f"sqlite:///{source_path}").connect() as connection:
        assert (
            connection.execute(text("SELECT value FROM unrelated_records")).scalar()
            == "preserved"
        )
    destination.dispose()


def test_legacy_test_posts_are_preserved_and_idempotent(tmp_path):
    from app.publisher import Post, PublisherBase

    path = tmp_path / "old-publisher.db"
    original = create_engine(f"sqlite:///{path}")
    PublisherBase.metadata.create_all(original)
    with Session(original) as session:
        session.add(
            Post(
                key="legacy:1:website",
                channel="website",
                text="Preserved post",
                payload={"key": "legacy:1:website"},
            )
        )
        session.commit()
    original.dispose()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    destination = tmp_path / "new-publisher.db"
    assert import_publisher(path, destination) == {"selected": 1, "inserted": 1}
    assert import_publisher(path, destination) == {"selected": 1, "inserted": 0}
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
