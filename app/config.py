"""Application configuration for Content Generation & Automated Publishing Agent."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(APP_ROOT / ".env", APP_ROOT / ".env.make"), extra="ignore"
    )

    mode: Literal["cloud", "demo"] = Field(
        default="cloud", validation_alias=AliasChoices("MODE", "CONTENT_MODE")
    )
    database_url: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("DATABASE_URL", "CONTENT_DATABASE_URL"),
    )
    reviewer_token: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("REVIEWER_TOKEN", "CONTENT_REVIEWER_TOKEN"),
    )
    session_secret: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("SESSION_SECRET", "CONTENT_SESSION_SECRET"),
    )
    secure_cookies: bool = Field(
        default=True,
        validation_alias=AliasChoices("SECURE_COOKIES", "CONTENT_SECURE_COOKIES"),
    )
    local_data_dir: Path = Field(
        default=APP_ROOT / "data",
        validation_alias=AliasChoices("LOCAL_DATA_DIR", "CONTENT_LOCAL_DATA_DIR"),
    )
    provider: Literal["none", "gemini", "openai", "xai", "fixture"] = Field(
        default="none",
        validation_alias=AliasChoices("PROVIDER", "CONTENT_PROVIDER"),
    )
    model_name: str = Field(
        default="",
        validation_alias=AliasChoices("MODEL_NAME", "CONTENT_MODEL_NAME"),
    )
    openai_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("OPENAI_API_KEY", "CONTENT_OPENAI_API_KEY"),
    )
    google_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("GOOGLE_API_KEY", "CONTENT_GOOGLE_API_KEY"),
    )
    xai_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("XAI_API_KEY", "CONTENT_XAI_API_KEY"),
    )
    provider_timeout: int = Field(
        default=45,
        validation_alias=AliasChoices("PROVIDER_TIMEOUT", "CONTENT_PROVIDER_TIMEOUT"),
    )
    max_llm_calls: int = Field(
        default=3,
        validation_alias=AliasChoices("MAX_LLM_CALLS", "CONTENT_MAX_LLM_CALLS"),
    )
    max_job_cost_usd: str = Field(
        default="0.10",
        validation_alias=AliasChoices("MAX_JOB_COST_USD", "CONTENT_MAX_JOB_COST_USD"),
    )
    input_usd_per_million: str = Field(
        default="",
        validation_alias=AliasChoices("INPUT_USD_PER_MILLION", "CONTENT_INPUT_USD_PER_MILLION"),
    )
    output_usd_per_million: str = Field(
        default="",
        validation_alias=AliasChoices("OUTPUT_USD_PER_MILLION", "CONTENT_OUTPUT_USD_PER_MILLION"),
    )
    pricing_source_url: str = Field(
        default="",
        validation_alias=AliasChoices("PRICING_SOURCE_URL", "CONTENT_PRICING_SOURCE_URL"),
    )
    pricing_checked_at: str = Field(
        default="",
        validation_alias=AliasChoices("PRICING_CHECKED_AT", "CONTENT_PRICING_CHECKED_AT"),
    )
    max_input_tokens: int = Field(
        default=32000,
        validation_alias=AliasChoices("MAX_INPUT_TOKENS", "CONTENT_MAX_INPUT_TOKENS"),
    )
    publisher_url: str = Field(
        default="http://127.0.0.1:8011",
        validation_alias=AliasChoices("PUBLISHER_URL", "CONTENT_PUBLISHER_URL"),
    )
    publisher_secret: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("PUBLISHER_SECRET", "CONTENT_PUBLISHER_SECRET"),
    )
    publisher_backend: Literal["local_test", "make"] = "local_test"
    public_base_url: str = ""
    make_api_token: SecretStr = SecretStr("")
    make_channels: str = "linkedin,website"
    tracing_backends: Literal["none", "langfuse", "langsmith", "both"] = Field(
        default="none",
        validation_alias=AliasChoices("TRACING_BACKENDS", "CONTENT_TRACING_BACKENDS"),
    )

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
        if self.public_base_url:
            parsed = urlsplit(self.public_base_url)
            if (
                parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ("", "/")
            ):
                raise ValueError("PUBLIC_BASE_URL must be an HTTPS origin without a path")
            self.public_base_url = self.public_base_url.rstrip("/")
        channels = [value.strip() for value in self.make_channels.split(",")]
        if not channels or any(c not in {"linkedin", "website", "newsletter"} for c in channels):
            raise ValueError("MAKE_CHANNELS must contain supported comma-separated channels")
        return self

    def require_runtime(self):
        for name in ("database_url", "reviewer_token", "session_secret"):
            value = getattr(self, name).get_secret_value()
            if len(value) < (24 if name != "database_url" else 1):
                raise RuntimeError(f"Configure {name.upper()} before starting")
        if self.mode == "cloud" and not self.database_url.get_secret_value().startswith(
            "postgresql+psycopg://"
        ):
            raise RuntimeError("Cloud mode requires Supabase PostgreSQL")
        if self.publisher_backend == "make":
            if not self.public_base_url or not self.secure_cookies:
                raise RuntimeError("Make requires PUBLIC_BASE_URL and SECURE_COOKIES=true")
            token = self.make_api_token.get_secret_value()
            if len(token) < 32 or token in {
                self.reviewer_token.get_secret_value(), self.session_secret.get_secret_value()
            }:
                raise RuntimeError("Configure a distinct MAKE_API_TOKEN (at least 32 characters)")
