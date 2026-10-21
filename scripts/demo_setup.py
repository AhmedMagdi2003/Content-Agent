"""Separate demo credentials and SQLite database; never edits the financial configuration."""

import secrets

from content_app.config import APP_ROOT, Settings
from content_app.db import initialize, make_engine


def setup():
    path = APP_ROOT / ".env"
    if path.exists():
        print(
            "Existing content .env preserved; run scripts.setup_db for an existing configuration."
        )
        return
    (APP_ROOT / "data").mkdir(exist_ok=True)
    path.write_text(
        "CONTENT_MODE=demo\nCONTENT_DATABASE_URL=sqlite:///data/content.db\n"
        "CONTENT_PROVIDER=fixture\nCONTENT_SECURE_COOKIES=false\n"
        f"CONTENT_REVIEWER_TOKEN={secrets.token_urlsafe(32)}\n"
        f"CONTENT_SESSION_SECRET={secrets.token_urlsafe(32)}\n"
        f"CONTENT_PUBLISHER_SECRET={secrets.token_urlsafe(32)}\n",
        encoding="utf-8",
    )
    cfg = Settings()
    initialize(make_engine(cfg.database_url.get_secret_value()))
    print("Independent content demo configured. Copy CONTENT_REVIEWER_TOKEN from .env locally.")
    print("Start content_app.main on 8001 and content_app.publisher on 8011.")


if __name__ == "__main__":
    setup()
