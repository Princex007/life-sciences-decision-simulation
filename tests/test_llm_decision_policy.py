import pytest
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from app.agents.llm import (DecisionPrompt, DecisionPromptBuilder, LLMConfigurationError,
                            LLMDecisionPolicy, MockLLMClient, LLMCompletion,
                            OpenAICompatibleLLMClient)
from app.compare_policies import compare
from app.domain.agent import Belief
from app.domain.definitions import SimulationDefinition
from app.services.simulation_runner import SimulationRunnerService
from app.run_llm_smoke import DEFAULT_DEFINITION, _single_decision_slice
from app.domain.definitions import SimulationDefinition as Definition


def definition_with_evidence():
    return SimulationDefinition.model_validate({
        "metadata": {"id": "llm-test", "name": "LLM Decision Test"},
        "initial_world_state": {"variables": {"count": 0, "secret": "private"}},
        "evidence": [
            {"id": "EVID-PUBLIC", "title": "Visible example", "content": "A supplied fact.",
             "source_type": "synthetic", "timestamp": 1, "reliability_label": "moderate",
             "visible_to_agents": ["worker"]},
            {"id": "EVID-PRIVATE", "title": "Hidden example", "content": "Not for worker.",
             "source_type": "synthetic", "timestamp": 1, "reliability_label": "moderate",
             "visible_to_agents": ["payer"]}],
        "agents": [{"id": "worker", "name": "Worker", "type": "generic",
            "objective": "change count", "observable_state": ["count"],
            "available_actions": ["increment", "double"],
            "decision_policy": {"default_actions": ["increment", "double"]}}],
        "action_definitions": [
            {"id": "increment", "name": "Increment", "agent_id": "worker",
             "strategy": "steady", "effects": [{"variable": "count", "operation": "add", "value": 1}]},
            {"id": "double", "name": "Double", "agent_id": "worker",
             "strategy": "fast", "effects": [{"variable": "count", "operation": "add", "value": 2}]}],
        "trigger_definitions": [{"id": "worker-start", "event_types": ["simulation_start"],
                                 "affected_agents": ["worker"]}],
        "settings": {"time_horizon": 1,
            "initial_events": [{"id": "start", "time": 0, "event_type": "simulation_start",
                                 "description": "Start"}]},
        "scenario_generation": {"policy": "exhaustive", "max_scenarios": None}})


def llm_response(**overrides):
    response = {"primary_action": "increment", "alternative_actions": ["double"],
        "rationale": "Increment is supported by [EVID-PUBLIC].", "key_drivers": ["count"],
        "facts_used": ["count = 0", "EVID-PUBLIC: A supplied fact."],
        "evidence_used": ["EVID-PUBLIC"],
        "assumptions": ["The stated objective remains relevant."],
        "strategy_change": "steady", "belief_updates": []}
    return {**response, **overrides}


def test_valid_structured_response_is_audited_and_engine_branches_over_alternatives():
    client = MockLLMClient(llm_response())
    result, _ = SimulationRunnerService(client).run(definition_with_evidence(), "llm")
    assert len(result.scenarios) == 2
    assert {scenario.actions[0].action_id for scenario in result.scenarios} == {"increment", "double"}
    trace = next(item for item in result.scenarios[0].decision_trace if item.event_type == "decision")
    assert trace.decision_response.primary_action == "increment"
    assert trace.decision_response.alternative_actions == ["double"]
    assert trace.decision_response.facts_used == ["count = 0", "EVID-PUBLIC: A supplied fact."]
    assert trace.decision_response.assumptions == ["The stated objective remains relevant."]
    assert trace.validation_status == "valid"
    assert trace.llm_audit.provider == "mock"
    assert trace.llm_audit.model_version == "mock-v1"
    assert trace.llm_audit.agent_id == "worker"
    assert trace.llm_audit.selected_action == trace.action.action_id
    assert trace.llm_audit.input_context.observations.visible_world_variables == {"count": 0}
    assert not hasattr(client.calls[0][0], "world_state")
    assert [item.id for item in trace.llm_audit.input_context.relevant_evidence] == ["EVID-PUBLIC"]
    assert len(client.calls) == 1


def test_unknown_action_rejected_with_trace_and_no_world_transition():
    response = llm_response(primary_action="invented", alternative_actions=[])
    result, _ = SimulationRunnerService(MockLLMClient(response)).run(definition_with_evidence(), "llm")
    assert len(result.scenarios) == 1
    assert result.scenarios[0].final_state.get("count") == 0
    trace = next(item for item in result.scenarios[0].decision_trace if item.event_type == "decision")
    assert trace.validation_status == "invalid"
    assert "invented" in trace.validity_reason
    assert trace.llm_audit.validation_result == "invalid"
    assert trace.llm_audit.selected_action is None


def test_malformed_response_is_rejected_safely_without_state_change():
    result, _ = SimulationRunnerService(MockLLMClient("not valid JSON")).run(definition_with_evidence(), "llm")
    assert result.scenarios[0].final_state.get("count") == 0
    trace = next(item for item in result.scenarios[0].decision_trace if item.event_type == "decision")
    assert trace.validation_status == "invalid"
    assert "Malformed structured LLM decision" in trace.validity_reason
    assert trace.llm_audit.raw_provider_response == "not valid JSON"


def test_llm_belief_update_requires_visible_evidence_and_variables():
    belief = Belief(id="share-defense", proposition="Worker will protect share",
        basis="Synthetic example", timestamp=1, evidence_ids=["EVID-PUBLIC"],
        strength_label="moderate", last_updated=1, related_variables=["count"])
    response = llm_response(belief_updates=[belief.model_dump()])
    result, _ = SimulationRunnerService(MockLLMClient(response)).run(definition_with_evidence(), "llm")
    assert result.scenarios[0].agent_states[0].belief_state.beliefs[-1].id == "share-defense"
    hidden = belief.model_copy(update={"id": "hidden", "evidence_ids": ["EVID-PRIVATE"]})
    response = llm_response(belief_updates=[hidden.model_dump()])
    result, _ = SimulationRunnerService(MockLLMClient(response)).run(definition_with_evidence(), "llm")
    assert all(item.id != "hidden" for item in result.scenarios[0].agent_states[0].belief_state.beliefs)
    trace = next(item for item in result.scenarios[0].decision_trace if item.event_type == "decision")
    assert trace.validation_status == "partially_valid"
    assert "not visible" in " ".join(trace.llm_audit.validation_errors)


def test_mock_response_and_prompt_are_deterministic_and_separate_instructions_from_data():
    context = SimulationRunnerService(MockLLMClient(llm_response()))
    definition = definition_with_evidence()
    first, _ = context.run(definition, "llm")
    second, _ = context.run(definition, "llm")
    # Runtime audit timestamps differ; simulation decisions and states remain identical.
    assert [[a.action_id for a in s.actions] for s in first.scenarios] == [
        [a.action_id for a in s.actions] for s in second.scenarios]
    trace = next(item for item in first.scenarios[0].decision_trace if item.event_type == "decision")
    prompt = DecisionPromptBuilder().build(trace.decision_context)
    assert "Never invent an action" in prompt.system
    assert "probabilities" in prompt.system
    assert "DecisionContext:" in prompt.user
    assert "EVID-PUBLIC" in prompt.user
    assert "EVID-PRIVATE" not in prompt.user


def test_no_credentials_fails_clearly_only_when_llm_mode_is_selected(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(LLMConfigurationError, match="LLM_API_KEY"):
        OpenAICompatibleLLMClient.from_environment()
    rule_result, _ = SimulationRunnerService().run(definition_with_evidence(), "rule_based")
    assert len(rule_result.scenarios) == 2
    with pytest.raises(LLMConfigurationError, match="LLM_API_KEY"):
        SimulationRunnerService().run(definition_with_evidence(), "llm")


def test_openai_compatible_client_accepts_configured_temperature():
    client = OpenAICompatibleLLMClient(api_key="test-only", base_url="https://example.invalid/v1",
                                      model="configured-model", temperature=0.4)
    assert client.model == "configured-model"
    assert client.temperature == 0.4
    with pytest.raises(LLMConfigurationError, match="LLM_TEMPERATURE"):
        OpenAICompatibleLLMClient(api_key="test-only", base_url="https://example.invalid/v1",
                                  model="configured-model", temperature=2.1)


def test_local_lm_studio_configuration_does_not_require_cloud_api_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "lm-studio")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("LLM_MODEL", "loaded-local-model")

    client = OpenAICompatibleLLMClient.from_environment()

    assert client.provider == "lm-studio"
    assert client.model == "loaded-local-model"
    assert client.base_url == "http://localhost:1234/v1"
    assert client._api_key == ""


def test_local_adapter_posts_to_chat_completions_without_authorization(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"model":"loaded-local-model","choices":[{"message":{"content":"{}"}}]}'

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("app.agents.llm.urlopen", fake_urlopen)
    client = OpenAICompatibleLLMClient(api_key="", base_url="http://localhost:1234/v1/",
        model="loaded-local-model", provider="local")
    completion = client.generate_decision(None, DecisionPrompt(system="test", user="test"))

    assert captured["request"].full_url == "http://localhost:1234/v1/chat/completions"
    assert "Authorization" not in captured["request"].headers
    assert completion.model == "loaded-local-model"
    request_payload = json.loads(captured["request"].data.decode("utf-8"))
    assert "response_format" not in request_payload
    assert "Return ONLY one exact candidate action ID as plain text." in request_payload["messages"][0]["content"]
    assert request_payload.get("max_tokens") == 16


def test_cloud_adapter_keeps_json_object_response_format(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"model":"cloud-model","choices":[{"message":{"content":"{}"}}]}'

    def fake_urlopen(request, timeout):
        captured["request"] = request
        return FakeResponse()

    monkeypatch.setattr("app.agents.llm.urlopen", fake_urlopen)
    client = OpenAICompatibleLLMClient(api_key="test-only", base_url="https://example.invalid/v1",
        model="cloud-model", provider="openai-compatible")
    client.generate_decision(None, DecisionPrompt(system="system", user="user"))
    request_payload = json.loads(captured["request"].data.decode("utf-8"))
    assert request_payload["response_format"] == {"type": "json_object"}
    assert "max_tokens" not in request_payload
    assert request_payload["messages"][0]["content"] == "system"


class LocalActionClient:
    provider = "local"
    model = "local-test-model"

    def __init__(self, content):
        self.content = content
        self.prompt = None

    def generate_decision(self, context, prompt):
        self.prompt = prompt
        return LLMCompletion(content=self.content, provider=self.provider, model=self.model)


def captured_context():
    client = MockLLMClient(llm_response())
    SimulationRunnerService(client).run(definition_with_evidence(), "llm")
    return client.calls[0][0]


def test_local_action_id_is_accepted_and_constructs_existing_response():
    context = captured_context()
    local = LocalActionClient("increment")
    policy = LLMDecisionPolicy(local)
    response = policy.decide(context, [context.available_actions[0]])
    assert response.primary_action == "increment"
    assert response.validation_status == "pending"
    assert response.rationale == "Local model returned action-only."
    assert "No model rationale" in response.assumptions[0]
    assert "plausible candidate action IDs" in local.prompt.system
    assert "Relevant DecisionContext" in local.prompt.user


def test_local_action_id_rejects_invalid_text_without_repair():
    response = LLMDecisionPolicy(LocalActionClient("launch")).decide(
        captured_context(), captured_context().available_actions)
    assert response.primary_action == ""
    assert response.validation_status == "invalid"
    assert "exactly match" in response.validation_errors[0]


def test_local_action_id_strips_surrounding_whitespace_only():
    context = captured_context()
    response = LLMDecisionPolicy(LocalActionClient(" \t increment\r\n")).decide(
        context, context.available_actions)
    assert response.primary_action == "increment"


def test_local_action_id_must_be_in_passed_candidate_set():
    context = captured_context()
    response = LLMDecisionPolicy(LocalActionClient("double")).decide(
        context, [context.available_actions[0]])
    assert response.validation_status == "invalid"
    assert response.primary_action == ""


def test_infeasible_local_action_is_filtered_before_model_selection():
    definition = definition_with_evidence()
    definition.action_definitions[0].constraints = {"compatible_when": [
        {"variable": "count", "operator": "eq", "value": 99}]}
    client = LocalActionClient("double")
    result, _ = SimulationRunnerService(client).run(definition, "llm")
    trace = next(item for item in result.scenarios[0].decision_trace if item.event_type == "decision")
    assert trace.validation_status == "valid"
    assert trace.action.action_id == "double"
    assert 'Plausible candidate action IDs: ["double"]' in client.prompt.user
    assert result.scenarios[0].final_state.get("count") == 2


def test_three_agent_smoke_is_sequential_filtered_and_single_scenario():
    definition = Definition.from_json(str(PROJECT_ROOT / "tests" / "fixtures" / "local_multi_agent_smoke.json"))

    def choose_first(context, _prompt):
        return {"primary_action": context.available_actions[0].id,
                "rationale": "Deterministic test selection."}

    client = MockLLMClient(choose_first)
    result, _ = SimulationRunnerService(client).run(definition, "llm")
    assert len(result.scenarios) == 1
    scenario = result.scenarios[0]
    decisions = [item for item in scenario.decision_trace if item.event_type == "decision"]
    assert [item.agent_id for item in decisions] == ["company", "competitor", "payer"]
    assert len(client.calls) == 3
    assert decisions[0].decision_context.observations.visible_world_variables == {
        "company_launch_status": "pre_launch", "drug_price": 100, "competitor_price": 95}
    assert decisions[1].decision_context.observations.visible_world_variables["company_launch_status"] == "launched"
    assert decisions[2].decision_context.observations.visible_world_variables["competitor_price"] == 85.5
    assert all(item.validation_status == "valid" for item in decisions)
    assert [item.action.action_id for item in decisions] == [
        "launch_at_list_price", "cut_competitor_price", "restrict_access"]


def test_local_compact_prompt_contains_filtered_context_without_schema_dump():
    context = captured_context()
    context.relevant_memory = {
        "previous_actions": ["launch", "increment"],
        "observations": [{"count": 0, "secret": "leaked"}],
        "strategy_changes": [{"strategy": "steady"}]
    }
    prompt = DecisionPromptBuilder().build_local_action_prompt(context, context.available_actions)
    assert "Relevant DecisionContext:" in prompt.user
    assert "Required JSON schema" not in prompt.user
    assert '"secret"' not in prompt.user
    assert "EVID-PRIVATE" not in prompt.user
    assert "policy_configuration" not in prompt.user
    assert "strength_label" not in prompt.user
    assert "current_strategy" not in prompt.user  # None strategy omitted when not relevant
    assert "recent_actions" in prompt.user
    assert "recent_strategy_changes" in prompt.user
    assert "leaked" not in prompt.user  # memory observations not dumped

    # Verify strategy is preserved when set
    context_with_strat = context.model_copy(update={"current_strategy": "market_entry"})
    prompt_with_strat = DecisionPromptBuilder().build_local_action_prompt(context_with_strat, context.available_actions)
    assert '"current_strategy":"market_entry"' in prompt_with_strat.user


def test_smoke_slice_routes_one_mock_decision_through_existing_simulation():
    definition = _single_decision_slice(SimulationDefinition.from_json(str(DEFAULT_DEFINITION)))
    # Isolate the LLM adapter contract from the example's now-configured Company scorer.
    definition.evaluation_objectives.pop("company", None)
    client = MockLLMClient({"primary_action": "launch", "alternative_actions": [],
        "rationale": "Select the configured reference-price launch.",
        "strategy_change": "market_entry_reference_price"})

    result, _ = SimulationRunnerService(client).run(definition, "llm")

    decisions = [trace for scenario in result.scenarios for trace in scenario.decision_trace
        if trace.event_type == "decision"]
    assert len(client.calls) == 1
    assert len(decisions) == 1
    assert decisions[0].validation_status == "valid"
    assert result.scenarios[0].final_state.get("company_launch_status") == "launched"


def test_smoke_slice_does_not_repair_valid_json_with_wrong_decision_schema():
    definition = _single_decision_slice(SimulationDefinition.from_json(str(DEFAULT_DEFINITION)))
    definition.evaluation_objectives.pop("company", None)
    client = MockLLMClient('{"action":"launch"}')

    result, _ = SimulationRunnerService(client).run(definition, "llm")

    decisions = [trace for scenario in result.scenarios for trace in scenario.decision_trace
        if trace.event_type == "decision"]
    assert len(decisions) == 1
    assert decisions[0].validation_status == "invalid"
    assert "primary_action" in decisions[0].validity_reason
    assert not result.scenarios[0].actions
    assert result.scenarios[0].final_state.get("company_launch_status") == "pre_launch"


def test_prompt_includes_no_credentials_even_if_client_has_a_key():
    client = OpenAICompatibleLLMClient("secret-token", "https://example.invalid/v1", "test-model")
    assert not hasattr(client, "key_for_prompt")
    assert client.model == "test-model"


def test_audit_redacts_bearer_tokens_from_raw_model_content():
    client = MockLLMClient(llm_response(rationale="Echo Bearer secret-token"))
    client._api_key = "secret-token"
    result, _ = SimulationRunnerService(client).run(definition_with_evidence(), "llm")
    trace = next(item for item in result.scenarios[0].decision_trace if item.event_type == "decision")
    assert "secret-token" not in trace.llm_audit.raw_provider_response
    assert "[REDACTED]" in trace.llm_audit.raw_provider_response


def test_comparison_runs_both_policies_on_the_same_initial_definition():
    def response(context, _prompt):
        action = next((item for item in context.available_actions
                       if (item.strategy or item.id) == context.current_strategy),
                      context.available_actions[0] if context.available_actions else None)
        if action is None:
            return {"primary_action": "", "rationale": "No actions"}
        return {"primary_action": action.id,
            "alternative_actions": [item.id for item in context.available_actions if item.id != action.id],
            "rationale": "Mock selection", "strategy_change": (action.strategy or action.id)
                if (action.strategy or action.id) != context.current_strategy else None}
    client = MockLLMClient(response)
    report = compare("examples/us_drug_launch.json", client)
    assert "does not claim predictive accuracy" in report["description"]
    # Configured objective scoring can decide some actions without branching.
    assert 1 <= report["rule_based"]["terminal_scenarios"] <= 9
    assert 1 <= report["llm"]["terminal_scenarios"] <= 9
    assert report["rule_based"]["decisions"]
    assert report["llm"]["decisions"]
