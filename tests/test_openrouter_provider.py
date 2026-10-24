"""Phase 4 provider-adapter tests. Mock-only: no test may reach a live endpoint."""
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from app.agents import llm as llm_module
from app.agents.llm import (DecisionPrompt, LLMCallBudget, LLMClientError, LLMCompletion,
                            OpenAICompatibleLLMClient)
from app.config import (OPENROUTER_DEFAULT_BASE_URL, LLMConfigurationError, load_env_file,
                        parse_env_text, resolve_llm_settings)
from app.domain.definitions import SimulationDefinition
from app.services.simulation_runner import SimulationRunnerService

PROJECT = Path(__file__).resolve().parents[1]
SMOKE_EXAMPLE = PROJECT / "tests" / "fixtures" / "local_multi_agent_smoke.json"


class FakeHTTPResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._payload


def install_transport(monkeypatch, outcomes):
    """Replay `outcomes` from the patched transport; an Exception entry is raised instead."""
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        outcome = outcomes[min(len(requests) - 1, len(outcomes) - 1)]
        if isinstance(outcome, BaseException):
            raise outcome
        return FakeHTTPResponse(outcome)

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    return requests


def envelope(content: str, usage: dict | None = None, model: str = "served-model") -> bytes:
    body = {"model": model, "choices": [{"message": {"content": content}}]}
    if usage is not None:
        body["usage"] = usage
    return json.dumps(body).encode("utf-8")


def openrouter_env(monkeypatch, **overrides):
    values = {"LLM_PROVIDER": "openrouter", "OPENROUTER_API_KEY": "sk-or-v1-test-only",
              "OPENROUTER_MODEL": "test/router-model"}
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


class RecordingClient:
    """Counts calls and reports token usage so budgets can be exercised deterministically.

    Returns no alternatives, so the example yields exactly one decision per agent and
    the number of provider calls stays predictable.
    """
    provider = "mock"
    model = "mock-decision-model"

    def __init__(self, total_tokens: int = 15):
        self.calls = 0
        self.total_tokens = total_tokens

    def generate_decision(self, context, _prompt) -> LLMCompletion:
        self.calls += 1
        content = json.dumps({"primary_action": context.available_actions[0].id,
                              "rationale": "Deterministic test selection."})
        return LLMCompletion(content=content, provider=self.provider, model=self.model,
                             latency_ms=12.5, attempts=1,
                             token_usage={"prompt_tokens": 10, "completion_tokens": 5,
                                          "total_tokens": self.total_tokens})


def smoke_definition() -> SimulationDefinition:
    return SimulationDefinition.from_json(str(SMOKE_EXAMPLE))


def captured_context():
    """One real DecisionContext, so adapter tests do not have to hand-build one."""
    from app.agents.llm import MockLLMClient
    client = MockLLMClient({"primary_action": "launch_at_list_price",
                            "rationale": "Deterministic test selection."})
    SimulationRunnerService(client).run(smoke_definition(), "llm")
    return client.calls[0][0]


def decisions_of(result):
    return [item for scenario in result.scenarios for item in scenario.decision_trace
            if item.event_type == "decision"]


# --- dotenv loading ---------------------------------------------------------

def test_dotenv_parser_handles_exports_quotes_and_comments(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# a comment\n"
        "\n"
        "PLAIN=value\n"
        "export EXPORTED=exported-value\n"
        'QUOTED="  spaced  "\n'
        "SINGLE='single'\n"
        "INLINE=value # trailing note\n"
        "EMPTY=\n"
        "NO_EQUALS_LINE\n",
        encoding="utf-8")
    assert parse_env_text(path.read_text(encoding="utf-8")) == {
        "PLAIN": "value", "EXPORTED": "exported-value", "QUOTED": "  spaced  ",
        "SINGLE": "single", "INLINE": "value", "EMPTY": ""}


def test_load_env_file_never_overrides_a_real_environment_variable(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("FROM_FILE=from-file\nALREADY_SET=from-file\n", encoding="utf-8")
    monkeypatch.setenv("ALREADY_SET", "from-process")
    assert load_env_file(path) == 1
    assert os.environ["FROM_FILE"] == "from-file"
    assert os.environ["ALREADY_SET"] == "from-process"
    monkeypatch.delenv("FROM_FILE", raising=False)


def test_load_env_file_ignores_a_missing_file(tmp_path):
    assert load_env_file(tmp_path / "absent.env") == 0


# --- configuration resolution ----------------------------------------------

def test_openrouter_settings_use_the_openrouter_variable_names(monkeypatch):
    openrouter_env(monkeypatch, OPENROUTER_SITE_URL="https://example.test",
                   OPENROUTER_APP_NAME="Simulation Workbench")
    settings = resolve_llm_settings()
    assert settings.provider == "openrouter"
    assert settings.is_openrouter and not settings.is_local
    assert settings.model == "test/router-model"
    assert settings.base_url == OPENROUTER_DEFAULT_BASE_URL
    assert settings.api_key == "sk-or-v1-test-only"
    assert settings.referer == "https://example.test"
    assert settings.application == "Simulation Workbench"


def test_openrouter_base_url_is_configurable(monkeypatch):
    openrouter_env(monkeypatch, OPENROUTER_BASE_URL="https://gateway.example.test/v1/")
    assert resolve_llm_settings().base_url == "https://gateway.example.test/v1/"


def test_openrouter_falls_back_to_the_generic_llm_variables(monkeypatch):
    openrouter_env(monkeypatch, OPENROUTER_MODEL="", LLM_MODEL="generic/model")
    assert resolve_llm_settings().model == "generic/model"


def test_missing_openrouter_key_names_the_openrouter_variable(monkeypatch):
    openrouter_env(monkeypatch, OPENROUTER_API_KEY="")
    with pytest.raises(LLMConfigurationError, match="OPENROUTER_API_KEY"):
        resolve_llm_settings()


def test_settings_describe_never_includes_the_key(monkeypatch):
    openrouter_env(monkeypatch)
    described = resolve_llm_settings().describe()
    assert described["api_key_configured"] is True
    assert "sk-or-v1-test-only" not in json.dumps(described)
    assert "api_key" not in described


def test_bundled_env_example_carries_placeholders_only():
    text = (PROJECT / ".env.example").read_text(encoding="utf-8")
    keys = {key: value for key, value in
            (line.split("=", 1) for line in text.splitlines()
             if "=" in line and not line.strip().startswith("#"))}
    assert keys["OPENROUTER_API_KEY"] == "sk-or-v1-REPLACE_WITH_YOUR_KEY"
    assert "REPLACE_WITH" in keys["OPENROUTER_MODEL"]
    gitignore = (PROJECT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in gitignore


# --- wire behaviour ---------------------------------------------------------

def test_client_posts_to_openrouter_with_attribution_headers(monkeypatch):
    requests = install_transport(monkeypatch, [envelope("{}")])
    openrouter_env(monkeypatch, OPENROUTER_SITE_URL="https://example.test",
                   OPENROUTER_APP_NAME="Simulation Workbench")
    client = OpenAICompatibleLLMClient.from_environment()
    client.generate_decision(None, DecisionPrompt(system="system", user="user"))

    request, timeout = requests[0]
    assert request.full_url == OPENROUTER_DEFAULT_BASE_URL + "/chat/completions"
    assert timeout == 45
    assert request.get_header("Authorization") == "Bearer sk-or-v1-test-only"
    assert request.get_header("Http-referer") == "https://example.test"
    assert request.get_header("X-title") == "Simulation Workbench"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["model"] == "test/router-model"
    assert payload["response_format"] == {"type": "json_object"}


def test_client_captures_token_usage_and_latency(monkeypatch):
    install_transport(monkeypatch, [envelope("{}", usage={
        "prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150,
        "cost": 0.004, "unexpected": "ignored"})])
    openrouter_env(monkeypatch)
    completion = OpenAICompatibleLLMClient.from_environment().generate_decision(
        None, DecisionPrompt(system="s", user="u"))
    assert completion.token_usage == {"prompt_tokens": 120, "completion_tokens": 30,
                                      "total_tokens": 150}
    assert completion.latency_ms is not None and completion.attempts == 1


def test_transport_failure_is_retried_and_then_succeeds(monkeypatch):
    requests = install_transport(monkeypatch, [URLError("dns"), envelope("{}")])
    openrouter_env(monkeypatch, LLM_MAX_ATTEMPTS="3")
    client = OpenAICompatibleLLMClient.from_environment()
    client.retry_backoff_seconds = 0
    completion = client.generate_decision(None, DecisionPrompt(system="s", user="u"))
    assert len(requests) == 2
    assert completion.attempts == 2


def test_non_retryable_http_status_is_not_retried(monkeypatch):
    requests = install_transport(monkeypatch, [
        HTTPError("https://openrouter.ai", 401, "Unauthorized", {}, None)])
    openrouter_env(monkeypatch, LLM_MAX_ATTEMPTS="3")
    client = OpenAICompatibleLLMClient.from_environment()
    client.retry_backoff_seconds = 0
    with pytest.raises(LLMClientError, match="HTTP 401"):
        client.generate_decision(None, DecisionPrompt(system="s", user="u"))
    assert len(requests) == 1


def test_retryable_status_stops_at_the_attempt_cap(monkeypatch):
    requests = install_transport(monkeypatch, [
        HTTPError("https://openrouter.ai", 500, "Server Error", {}, None)])
    openrouter_env(monkeypatch, LLM_MAX_ATTEMPTS="2")
    client = OpenAICompatibleLLMClient.from_environment()
    client.retry_backoff_seconds = 0
    with pytest.raises(LLMClientError, match="HTTP 500"):
        client.generate_decision(None, DecisionPrompt(system="s", user="u"))
    assert len(requests) == 2


def test_throttled_request_outlasts_the_attempt_cap_without_spending(monkeypatch):
    """A 429 never reached the model, so waiting it out cannot increase cost."""
    sleeps = []
    monkeypatch.setattr(llm_module.time, "sleep", sleeps.append)
    requests = install_transport(monkeypatch, [
        HTTPError("https://openrouter.ai", 429, "Too Many Requests", {}, None)])
    openrouter_env(monkeypatch, LLM_MAX_ATTEMPTS="2")
    client = OpenAICompatibleLLMClient.from_environment()
    with pytest.raises(LLMClientError, match="rate limiting this model"):
        client.generate_decision(None, DecisionPrompt(system="s", user="u"))
    assert len(requests) == llm_module.RATE_LIMIT_MAX_ATTEMPTS
    assert sleeps == [2.0, 4.0, 8.0, 16.0]


def test_provider_retry_after_header_sets_the_wait(monkeypatch):
    sleeps = []
    monkeypatch.setattr(llm_module.time, "sleep", sleeps.append)
    requests = install_transport(monkeypatch, [
        HTTPError("https://openrouter.ai", 429, "Too Many Requests",
                  {"Retry-After": "3"}, None),
        envelope("{}")])
    openrouter_env(monkeypatch)
    completion = OpenAICompatibleLLMClient.from_environment().generate_decision(
        None, DecisionPrompt(system="s", user="u"))
    assert len(requests) == 2
    assert sleeps == [3.0]
    assert completion.attempts == 2


def test_retry_after_header_is_read_safely():
    def header(value):
        return HTTPError("https://openrouter.ai", 429, "Too Many Requests", value, None)

    assert llm_module._retry_after_seconds(header({"Retry-After": "7.5"})) == 7.5
    assert llm_module._retry_after_seconds(
        header({"Retry-After": "600"})) == llm_module.RATE_LIMIT_MAX_WAIT_SECONDS
    for unusable in ({}, {"Retry-After": ""}, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
                     {"Retry-After": "-4"}):
        assert llm_module._retry_after_seconds(header(unusable)) is None


def test_attempt_cap_is_bounded_by_configuration(monkeypatch):
    openrouter_env(monkeypatch, LLM_MAX_ATTEMPTS="99")
    assert resolve_llm_settings().max_attempts == 5
    with pytest.raises(LLMConfigurationError, match="LLM_MAX_ATTEMPTS"):
        OpenAICompatibleLLMClient("k", "https://example.invalid/v1", "m", max_attempts=0)


def test_invalid_model_output_is_never_resubmitted(monkeypatch):
    install_transport(monkeypatch, [envelope("not json")])
    openrouter_env(monkeypatch, LLM_MAX_ATTEMPTS="4")
    client = OpenAICompatibleLLMClient.from_environment()
    completion = client.generate_decision(None, DecisionPrompt(system="s", user="u"))
    assert completion.attempts == 1
    response = llm_module.LLMDecisionPolicy(client).decide(captured_context(), [])
    assert response.validation_status == "invalid"


# --- call and token budgets -------------------------------------------------

def test_call_cap_degrades_to_the_rule_based_policy_without_a_provider_call():
    definition = smoke_definition()
    definition.settings.llm_max_calls = 1
    client = RecordingClient()
    result, _ = SimulationRunnerService(client).run(definition, "llm")

    assert client.calls == 1
    decisions = decisions_of(result)
    assert [item.decision_source for item in decisions] == [
        "llm", "existing_policy_fallback", "existing_policy_fallback"]
    assert all(item.validation_status == "valid" for item in decisions)
    skipped = decisions[1]
    assert "LLM call cap of 1 reached" in skipped.llm_audit.skip_reason
    assert skipped.llm_audit.provider_attempts == 0
    assert "rule-based policy chose this action instead" in " ".join(
        skipped.decision_response.assumptions)
    assert result.llm_usage["provider_calls"] == 1
    assert result.llm_usage["skipped_calls"] >= 1
    assert result.llm_usage["exhausted_reason"] == "LLM call cap of 1 reached."


def test_uncapped_budget_exhaustion_matches_a_plain_rule_based_run():
    capped = smoke_definition()
    capped.settings.llm_max_calls = 0
    client = RecordingClient()
    capped_result, _ = SimulationRunnerService(client).run(capped, "llm")
    plain_result, _ = SimulationRunnerService().run(smoke_definition(), "rule_based")

    assert client.calls == 0
    assert [[item.action_id for item in scenario.actions] for scenario in capped_result.scenarios] == \
           [[item.action_id for item in scenario.actions] for scenario in plain_result.scenarios]
    assert capped_result.scenarios[0].final_state.as_variables() == \
           plain_result.scenarios[0].final_state.as_variables()
    assert all(item.decision_source == "existing_policy_fallback"
               for item in decisions_of(capped_result))


def test_token_budget_stops_provider_calls_once_spent():
    definition = smoke_definition()
    definition.settings.llm_max_total_tokens = 20
    client = RecordingClient(total_tokens=15)
    result, _ = SimulationRunnerService(client).run(definition, "llm")

    assert client.calls == 2
    assert result.llm_usage["provider_calls"] == 2
    assert result.llm_usage["skipped_calls"] == 1
    assert result.llm_usage["total_tokens"] == 30
    assert "token budget of 20" in result.llm_usage["exhausted_reason"]


def test_budget_is_per_run_and_not_shared_between_runs():
    definition = smoke_definition()
    definition.settings.llm_max_calls = 2
    service = SimulationRunnerService(RecordingClient())
    first, _ = service.run(definition, "llm")
    second, _ = service.run(definition, "llm")
    assert first.llm_usage["provider_calls"] == 2
    assert second.llm_usage["provider_calls"] == 2


def test_rule_based_runs_report_no_llm_usage():
    result, _ = SimulationRunnerService().run(smoke_definition(), "rule_based")
    assert result.llm_usage is None


def test_budget_rejects_negative_limits():
    with pytest.raises(ValueError, match="llm_max_calls"):
        LLMCallBudget(max_calls=-1)
    with pytest.raises(ValueError, match="llm_max_total_tokens"):
        LLMCallBudget(max_total_tokens=-1)
    with pytest.raises(ValueError):
        SimulationDefinition.model_validate({
            **json.loads(SMOKE_EXAMPLE.read_text(encoding="utf-8")),
            "settings": {**smoke_definition().settings.model_dump(), "llm_max_calls": -3}})


# --- secret hygiene ---------------------------------------------------------

def test_credentials_never_reach_the_trace_or_usage_summary():
    definition = smoke_definition()
    definition.settings.llm_max_calls = 1
    client = RecordingClient()
    result, _ = SimulationRunnerService(client).run(definition, "llm")
    serialized = result.model_dump_json()
    assert "sk-or-v1" not in serialized
    assert "Bearer" not in serialized
    usage = result.llm_usage
    assert usage["providers"] == ["mock"] and usage["models"] == ["mock-decision-model"]
    assert "api_key" not in json.dumps(usage)


def test_audit_redacts_a_key_echoed_by_the_provider(monkeypatch):
    install_transport(monkeypatch, [envelope(
        json.dumps({"primary_action": "launch_at_list_price",
                    "rationale": "Echo Bearer sk-or-v1-test-only"}))])
    openrouter_env(monkeypatch)
    client = OpenAICompatibleLLMClient.from_environment()
    policy = llm_module.LLMDecisionPolicy(client)
    context = captured_context()
    response = policy.decide(context, context.available_actions)
    audit = policy.audit_for(context, response, "valid", [], "launch_at_list_price")
    assert "sk-or-v1-test-only" not in audit.raw_provider_response
    assert "[REDACTED]" in audit.raw_provider_response
    assert audit.decision_source == "llm"
    assert audit.provider == "openrouter"
    assert "sk-or-v1-test-only" not in audit.model_dump_json()
