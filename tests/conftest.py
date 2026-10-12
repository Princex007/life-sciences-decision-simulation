"""Suite-wide guards: no test may use a real credential or reach a live provider."""
import pytest

from app.agents import llm

PROVIDER_ENVIRONMENT_VARIABLES = (
    "LLM_API_KEY", "LLM_MODEL", "LLM_PROVIDER", "LLM_BASE_URL", "LLM_TEMPERATURE",
    "LLM_TIMEOUT_SECONDS", "LLM_MAX_ATTEMPTS", "LLM_MAX_OUTPUT_TOKENS",
    "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "OPENROUTER_BASE_URL",
    "OPENROUTER_SITE_URL", "OPENROUTER_APP_NAME",
)


@pytest.fixture(autouse=True)
def no_provider_credentials(monkeypatch):
    """Strip ambient credentials so a developer's local `.env` cannot reach a test.

    The suite must run without a live API key, and an exported key must never turn a
    mock-policy test into a billable provider call.
    """
    for name in PROVIDER_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_live_provider_calls(monkeypatch):
    """Block the adapter's transport so a missing monkeypatch fails instead of spending money.

    Tests that exercise the wire protocol patch `app.agents.llm.urlopen` themselves;
    their patch is applied after this one and therefore takes precedence.
    """
    def blocked(*_args, **_kwargs):
        raise AssertionError("A test reached the live LLM transport. "
                             "Monkeypatch app.agents.llm.urlopen with a fake response.")
    monkeypatch.setattr(llm, "urlopen", blocked)
