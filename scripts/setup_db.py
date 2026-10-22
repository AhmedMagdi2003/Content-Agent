from app.config import Settings
from app.db import initialize, make_engine

if __name__ == "__main__":
    settings = Settings()
    settings.require_runtime()
    initialize(make_engine(settings.database_url.get_secret_value()))
    print("Independent content schema initialized; no finance tables or storage bucket required.")
