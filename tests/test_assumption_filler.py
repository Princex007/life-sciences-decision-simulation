"""The LLM gap filler may only complete blanks, and only with validated values."""
import json

import pytest

from app.agents.assumptions import (
    MAX_ACTIONS_PER_AGENT, AssumptionFillError, build_prompt, fill_assumptions, find_gaps)
from app.agents.llm import DecisionPrompt, LLMCompletion
from app.domain.definitions import SimulationDefinition
from app.simulation.engine import SimulationEngine


def definition(payload=None):
    base = {
        "metadata": {"id": "mfn", "name": "MFN on revenue", "description": "Model MFN pricing"},
        "initial_world_state": {"variables": {"patients": "100 million", "price": 680}},
        "world_variable_metadata": {"patients": {"type": "string", "description": "Treated patients"}},
        "agents": [
            {"id": "lilly", "name": "Eli Lilly", "type": "company", "objective": "Maximize revenue",
             "available_actions": [], "decision_policy": {"type": "rule_based", "default_actions": []}},
            {"id": "government", "name": "Government", "objective": "Protect access",
             "available_actions": [], "decision_policy": {"type": "rule_based", "default_actions": []}}],
        "action_definitions": [], "trigger_definitions": [
            {"id": "start", "event_types": ["simulation_start"], "affected_agents": ["lilly"]}],
        "settings": {"time_horizon": 2, "step_duration": 1, "step_unit": "round",
                     "initial_events": [{"id": "start", "time": 0, "event_type": "simulation_start"}],
                     "scheduled_events": []},
        "forecast_model_id": None,
        "scenario_generation": {"policy": "limited", "max_scenarios": 4}}
    return SimulationDefinition.model_validate(payload or base)


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.prompts: list[DecisionPrompt] = []

    def generate_json(self, prompt: DecisionPrompt) -> LLMCompletion:
        self.prompts.append(prompt)
        content = self.response if isinstance(self.response, str) else json.dumps(self.response)
        return LLMCompletion(content=content, provider="fake", model="fake-model",
                             token_usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30})


def good_response():
    return {"variables": {"patients": {"value": 1000000, "rationale": "about a million treated"}},
            "actions": {"government": [{"name": "Set MFN ceiling", "variable": "price",
                                        "operation": "multiply", "value": 0.6,
                                        "rationale": "cap the list price"}]},
            "triggers": {"government": "every_round"}}


def test_find_gaps_flags_text_quantity_missing_actions_and_missing_trigger():
    gaps = {(gap.kind, gap.key) for gap in find_gaps(definition())}
    assert ("variable_value", "patients") in gaps
    assert ("agent_actions", "lilly") in gaps and ("agent_actions", "government") in gaps
    assert ("agent_trigger", "government") in gaps
    # `price` is already a number and lilly already has a trigger.
    assert ("variable_value", "price") not in gaps
    assert ("agent_trigger", "lilly") not in gaps


def test_a_complete_definition_never_reaches_the_provider():
    payload = definition().model_dump(mode="json")
    payload["initial_world_state"]["variables"]["patients"] = 1000000
    payload["action_definitions"] = [
        {"id": "lilly_act", "name": "Act", "agent_id": "lilly",
         "effects": [{"variable": "price", "operation": "subtract", "value": 10}]},
        {"id": "gov_act", "name": "Act", "agent_id": "government",
         "effects": [{"variable": "price", "operation": "subtract", "value": 5}]}]
    for agent in payload["agents"]:
        agent["available_actions"] = [action["id"] for action in payload["action_definitions"]
                                      if action["agent_id"] == agent["id"]]
        agent["decision_policy"]["default_actions"] = agent["available_actions"]
    payload["trigger_definitions"].append({"id": "gov-start", "event_types": ["simulation_start"],
                                           "affected_agents": ["government"]})
    complete = SimulationDefinition.model_validate(payload)
    assert find_gaps(complete) == []
    client = FakeClient(good_response())
    result = fill_assumptions(complete, client)
    assert result.filled == [] and client.prompts == []
    assert result.definition is not complete


def test_only_detected_gaps_are_filled_and_entered_values_survive():
    response = good_response()
    response["variables"]["price"] = {"value": 1, "rationale": "overwrite the user's number"}
    response["objectives"] = {"lilly": "Maximize shareholder value instead"}
    result = fill_assumptions(definition(), FakeClient(response))
    assert result.definition.initial_world_state.get("price") == 680
    assert next(a for a in result.definition.agents if a.id == "lilly").objective == "Maximize revenue"
    reasons = {(item.kind, item.key) for item in result.rejected}
    assert ("variable_value", "price") in reasons and ("agent_objective", "lilly") in reasons
    assert all("not a detected gap" in item.reason for item in result.rejected)


def test_values_that_fail_validation_never_reach_the_definition():
    response = {"variables": {"patients": {"value": "about a million", "rationale": "vague"}},
                "actions": {"lilly": [
                    {"name": "Bad variable", "variable": "revenue", "operation": "set", "value": 5},
                    {"name": "Bad operation", "variable": "price", "operation": "explode", "value": 5},
                    {"name": "Divide by zero", "variable": "price", "operation": "divide", "value": 0},
                    {"name": "Not a number", "variable": "price", "operation": "set", "value": True}]},
                "triggers": {"government": "whenever"}}
    result = fill_assumptions(definition(), FakeClient(response))
    assert result.filled == []
    assert isinstance(result.definition.initial_world_state.get("patients"), str)
    assert result.definition.action_definitions == []
    assert len(result.rejected) == 6


def test_more_than_the_allowed_number_of_actions_is_truncated():
    response = {"actions": {"lilly": [{"name": f"Option {index}", "variable": "price",
                                      "operation": "subtract", "value": 1}
                                     for index in range(MAX_ACTIONS_PER_AGENT + 2)]}}
    result = fill_assumptions(definition(), FakeClient(response))
    assert len(result.definition.action_definitions) == MAX_ACTIONS_PER_AGENT
    assert any("only the first" in item.reason for item in result.rejected)


def test_filled_values_are_labeled_as_model_assumptions():
    result = fill_assumptions(definition(), FakeClient(good_response()))
    metadata = result.definition.world_variable_metadata["patients"]
    assert metadata["evidence_grade"] == "llm_assumption"
    assert metadata["type"] == "number"
    assert metadata["assumption_labels"]
    action = result.definition.action_definitions[0]
    assert action.description.startswith("LLM assumption:")
    assert action.id in next(a for a in result.definition.agents
                             if a.id == "government").available_actions


def test_the_report_phrases_each_effect_in_english():
    response = good_response()
    response["actions"]["government"] = [
        {"name": "Set MFN ceiling", "variable": "price", "operation": "set", "value": 480,
         "rationale": "cap the list price"},
        {"name": "Cut price", "variable": "price", "operation": "multiply", "value": 0.9,
         "rationale": "a smaller discount"}]
    phrases = [item.value for item in fill_assumptions(definition(), FakeClient(response)).filled
               if item.kind == "agent_actions"]
    assert any("(set price to 480)" in phrase for phrase in phrases)
    assert any("(multiply price by 0.9)" in phrase for phrase in phrases)


def test_a_per_round_trigger_also_gets_the_scheduled_round_events():
    result = fill_assumptions(definition(), FakeClient(good_response()))
    trigger = next(t for t in result.definition.trigger_definitions if "government" in t.affected_agents)
    assert trigger.event_types == ["simulation_start", "decision_round"]
    assert [event.time for event in result.definition.settings.scheduled_events] == [1, 2]


def test_the_filled_definition_runs_and_the_model_action_changes_the_world():
    result = fill_assumptions(definition(), FakeClient(good_response()))
    terminal = SimulationEngine().run(result.definition).scenarios[0]
    # The model gave `government` a per-round trigger, so its effect applies once per tick.
    assert terminal.final_state.get("price") == pytest.approx(680 * 0.6 ** 3)
    assert terminal.final_state.get("patients") == 1000000
    assert [trace.time for trace in terminal.decision_trace
            if trace.event_type == "decision" and trace.agent_id == "government"] == [0, 1, 2]


def test_an_unreadable_response_applies_nothing():
    with pytest.raises(AssumptionFillError) as error:
        fill_assumptions(definition(), FakeClient("the model wrote prose instead of JSON"))
    assert "No values were applied" in str(error.value)


def test_prompt_lists_only_the_detected_gaps_and_existing_names():
    built = build_prompt(definition(), find_gaps(definition()))
    body = json.loads(built.user)
    assert {gap["key"] for gap in body["gaps"]} == {"patients", "lilly", "government"}
    assert set(body["world_variables"]) == {"patients", "price"}
    assert all(gap["key"] != "price" for gap in body["gaps"] if gap["kind"] == "variable_value")


def test_the_endpoint_returns_a_completed_definition_without_storing_it(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import api
    from app.main import app
    from app.services.simulation_builder import SimulationBuilderService

    monkeypatch.setattr(api.routes, "builder", SimulationBuilderService(tmp_path, api.routes.builder.examples_dir))
    api.routes._results.clear()
    monkeypatch.setattr(api.routes.runner, "llm_client", FakeClient(good_response()))
    with TestClient(app) as client:
        response = client.post("/simulations/complete-gaps", json=definition().model_dump(mode="json"))
        stored = client.get("/simulations").json()
    api.routes._results.clear()
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["definition"]["initial_world_state"]["variables"]["patients"] == 1000000
    assert payload["provider_call"]["model"] == "fake-model"
    assert stored == []  # gap filling is a proposal; nothing is written to local storage


def test_the_endpoint_reports_400_when_no_provider_is_configured(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import api
    from app.main import app
    from app.services.simulation_builder import SimulationBuilderService

    monkeypatch.setattr(api.routes, "builder", SimulationBuilderService(tmp_path, api.routes.builder.examples_dir))
    monkeypatch.setattr(api.routes.runner, "llm_client", None)
    with TestClient(app) as client:
        response = client.post("/simulations/complete-gaps", json=definition().model_dump(mode="json"))
    assert response.status_code == 400
    assert "LLM_API_KEY" in response.json()["detail"]
