from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.ai import LiveProvider, ProviderError
from app.models import Usage
from app.schemas import Drafts


class Model:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def with_structured_output(self, schema, include_raw):
        return self

    def invoke(self, *args, **kwargs):
        from langsmith.run_helpers import get_tracing_context

        assert get_tracing_context()["enabled"] is False
        self.calls += 1
        if self.fail:
            raise TimeoutError("This raw error must not appear in events")
        return {
            "parsed": Drafts(
                linkedin="LinkedIn update", newsletter="Newsletter update", website="Website update"
            ),
            "raw": SimpleNamespace(usage_metadata={"input_tokens": 100, "output_tokens": 10}),
        }


def configured(cfg):
    return cfg.model_copy(
        update={
            "provider": "openai",
            "model_name": "fake-model",
            "openai_api_key": SecretStr("fake"),
            "input_usd_per_million": "0.10",
            "output_usd_per_million": "0.40",
            "pricing_source_url": "https://example.test/rates",
            "pricing_checked_at": "2026-10-21",
        }
    )


def test_retry_ceiling_and_usage_ledger(runtime, monkeypatch):
    cfg, app, _ = runtime
    model = Model(fail=True)
    with app.state.sessions() as session:
        provider = LiveProvider(configured(cfg), session, "run-test")
        monkeypatch.setattr(provider, "_model", lambda: model)
        with pytest.raises(ProviderError, match="MODEL_CALL_FAILED"):
            provider.draft("The fictional team reviewed a checklist.")
        assert model.calls == 2
        # Second node gets only the third call; no fourth call is possible.
        with pytest.raises(ProviderError):
            provider.draft("The fictional team reviewed a checklist.")
        assert provider.calls == model.calls == 3
        session.commit()
        assert len(session.scalars(select(Usage)).all()) == 3
        assert all(u.estimated_usd is None for u in session.scalars(select(Usage)))


def test_cost_guard_and_unknown_usage(runtime, monkeypatch):
    cfg, app, _ = runtime
    model = Model()
    with app.state.sessions() as session:
        settings = configured(cfg).model_copy(update={"max_job_cost_usd": "0.00001"})
        provider = LiveProvider(settings, session, "guard-test")
        monkeypatch.setattr(provider, "_model", lambda: model)
        with pytest.raises(ProviderError, match="JOB_COST_GUARD"):
            provider.draft("The fictional team reviewed a checklist.")
        assert model.calls == 0
        provider = LiveProvider(configured(cfg), session, "priced-test")
        monkeypatch.setattr(provider, "_model", lambda: model)
        result = provider.draft("The fictional team reviewed a checklist.")
        assert result.website == "Website update"
        session.commit()
        usage = session.scalar(select(Usage))
        assert usage.estimated_usd == Decimal("0.000014")


def test_disabled_traces_override_ambient_export(runtime, monkeypatch):
    from langsmith import tracing_context

    cfg, app, _ = runtime
    model = Model()
    with app.state.sessions() as session:
        provider = LiveProvider(configured(cfg), session, "privacy-test")
        monkeypatch.setattr(provider, "_model", lambda: model)
        with tracing_context(enabled=True):
            provider.draft("The fictional team reviewed a checklist.")
        assert model.calls == 1
