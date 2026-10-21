"""Content-only configuration. Neither root .env nor financial variables are loaded."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=APP_ROOT / ".env", env_prefix="CONTENT_", extra="ignore"
    )

    mode: Literal["cloud", "demo"] = "cloud"
    database_url: SecretStr = SecretStr("")
    reviewer_token: SecretStr = SecretStr("")
    session_secret: SecretStr = SecretStr("")
    secure_cookies: bool = True
    local_data_dir: Path = APP_ROOT / "data"
    provider: Literal["none", "gemini", "openai", "xai", "fixture"] = "none"
    model_name: str = ""
    openai_api_key: SecretStr = SecretStr("")
    google_api_key: SecretStr = SecretStr("")
    xai_api_key: SecretStr = SecretStr("")
    provider_timeout: int = 45
    max_llm_calls: int = 3
    max_job_cost_usd: str = "0.10"
    input_usd_per_million: str = ""
    output_usd_per_million: str = ""
    pricing_source_url: str = ""
    pricing_checked_at: str = ""
    max_input_tokens: int = 32000
    publisher_url: str = "http://127.0.0.1:8011"
    publisher_secret: SecretStr = SecretStr("")
    tracing_backends: Literal["none", "langfuse", "langsmith", "both"] = "none"

    @model_validator(mode="after")
    def guard(self):
        if self.provider == "fixture" and self.mode != "demo":
            raise ValueError("Fixture provider is restricted to explicit demo mode")
        if self.database_url.get_secret_value().startswith("sqlite") and self.mode != "demo":
            raise ValueError("SQLite is restricted to explicit offline demo mode")
        if not 1 <= self.max_llm_calls <= 3:
            raise ValueError("max_llm_calls must be 1..3")
        if not self.local_data_dir.is_absolute():
            self.local_data_dir = APP_ROOT / self.local_data_dir
        return self

    def require_runtime(self):
        for name in ("database_url", "reviewer_token", "session_secret"):
            value = getattr(self, name).get_secret_value()
            if len(value) < (24 if name != "database_url" else 1):
                raise RuntimeError(f"Configure CONTENT_{name.upper()} before starting")
        if self.mode == "cloud" and not self.database_url.get_secret_value().startswith(
            "postgresql+psycopg://"
        ):
            raise RuntimeError("Cloud mode requires Supabase PostgreSQL")
