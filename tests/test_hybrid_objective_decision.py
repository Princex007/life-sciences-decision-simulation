import json
import pytest

from app.agents.base import RuleBasedDecisionPolicy
from app.agents.cognition import DecisionResponse
from app.agents.llm import LLMDecisionPolicy, MockLLMClient
from app.domain.definitions import SimulationDefinition
from app.evaluation.objective_scorer import ObjectiveScorer
from app.simulation.decision_validator import DecisionValidator
from app.simulation.engine import SimulationEngine


def definition(*, scored=True, tolerance=0.005):
    result = SimulationDefinition.model_validate({
        "metadata": {"id": "hybrid-test", "name": "Hybrid Test"},
        "initial_world_state": {"variables": {"count": 0}},
        "evaluation_objectives": ({"worker": {
            "score_tie_tolerance": tolerance,
            "components": [{"name": "count", "source": "after_next_time_step",
                "metric": "count", "normalization": {"method": "min_max", "minimum": 0,
                "maximum": 10}, "preference": "maximize", "weight": 1.0}]}}
            if scored else {}),
        "agents": [{"id": "worker", "name": "Worker", "objective": "change count",
            "observable_state": ["count"], "available_actions": ["left", "right"],
            "decision_policy": {"default_actions": ["left", "right"]}}],
        "action_definitions": [
            {"id": "left", "name": "Left", "agent_id": "worker", "description": "Left action",
             "effects": [{"variable": "count", "operation": "add", "value": 1}]},
            {"id": "right", "name": "Right", "agent_id": "worker", "description": "Right action",
             "effects": [{"variable": "count", "operation": "add", "value": 2}]},
        ],
        "trigger_definitions": [{"id": "start", "event_types": ["simulation_start"],
                                  "affected_agents": ["worker"]}],
        "transition_rules": [{"id": "clock", "event_type": "time_step",
                               "effects": [{"variable": "count", "operation": "add", "value": 0}]}],
        "settings": {"time_horizon": 1, "initial_events": [{"id": "start-event", "time": 0,
            "event_type": "simulation_start", "description": "Start"}]},
        "scenario_generation": {"policy": "exhaustive", "max_scenarios": None},
    })
    return result


def score_rows(ids, values):
    return {action_id: {"score": values[action_id], "components": {
        "test_metric": {"raw_value": values[action_id], "normalized_value": values[action_id],
                        "preference_value": values[action_id], "weight": 1.0,
                        "weighted_contribution": values[action_id]}}} for action_id in ids}


class CountingPolicy(RuleBasedDecisionPolicy):
    def __init__(self, selected="left"):
        self.selected = selected
        self.decide_calls = 0
        self.received = None

    def decide(self, context, actions):
        self.decide_calls += 1
        self.received = (context.model_copy(deep=True), list(actions))
        return DecisionResponse(primary_action=self.selected)


def test_decisive_score_selects_highest_without_calling_policy(monkeypatch):
    monkeypatch.setattr(ObjectiveScorer, "score_actions",
        lambda self, previews, state, objective: score_rows(previews, {"left": 0.2, "right": 0.8}))
    policy = CountingPolicy()
    result = SimulationEngine(decision_policy=policy).run(definition())
    trace = next(item for item in result.scenarios[0].decision_trace if item.event_type == "decision")
    assert trace.action.action_id == "right"
    assert policy.decide_calls == 0
    assert trace.decision_source == "objective_scorer"
    assert trace.objective_score_margin == pytest.approx(0.6)


def test_close_scores_use_llm_policy_and_prompt_contains_scores_and_components(monkeypatch):
    monkeypatch.setattr(ObjectiveScorer, "score_actions",
        lambda self, previews, state, objective: score_rows(previews, {"left": 0.7, "right": 0.702}))
    client = MockLLMClient(DecisionResponse(primary_action="left"))
    policy = LLMDecisionPolicy(client)
    result = SimulationEngine(decision_policy=policy).run(definition())
    trace = next(item for item in result.scenarios[0].decision_trace if item.event_type == "decision")
    assert trace.action.action_id == "left"
    assert trace.decision_source == "llm"
    assert trace.objective_score_margin == pytest.approx(0.002)
    assert len(client.calls) == 1
    sent_context, prompt = client.calls[0]
    assert sent_context.objective_scores["left"]["score"] == pytest.approx(0.7)
    payload_text = prompt.user.split("DecisionContext:\n", 1)[1]
    payload = json.loads(payload_text.split("\n\nCandidate consequences and objective components:\n", 1)[0])
    assert payload["objective_scores"]["left"]["components"]["test_metric"]["weighted_contribution"] == pytest.approx(0.7)
    candidate_payload = json.loads(prompt.user.split(
        "Candidate consequences and objective components:\n", 1)[1])
    assert {item["action_id"] for item in candidate_payload} == {"left", "right"}
    assert all(item["preview"] for item in candidate_payload)
    assert candidate_payload[0]["objective_components"]["test_metric"]["weighted_contribution"] == pytest.approx(0.7)


def test_missing_scores_fall_back_once_to_existing_policy(monkeypatch):
    def fail(*args):
        raise ValueError("required preview metric is missing")
    monkeypatch.setattr(ObjectiveScorer, "score_actions", fail)
    policy = CountingPolicy(selected="right")
    result = SimulationEngine(decision_policy=policy).run(definition())
    trace = next(item for item in result.scenarios[0].decision_trace if item.event_type == "decision")
    assert trace.action.action_id == "right"
    assert policy.decide_calls == 1
    assert trace.decision_source == "existing_policy_fallback"
    assert trace.decision_context.objective_scores == {}


@pytest.mark.parametrize("invalid_result", [
    {"left": score_rows(["left"], {"left": 0.5})["left"]},
    score_rows(["left", "right"], {"left": 0.5, "right": float("nan")}),
])
def test_incomplete_or_nonfinite_scores_fall_back(monkeypatch, invalid_result):
    monkeypatch.setattr(ObjectiveScorer, "score_actions",
        lambda self, previews, state, objective: invalid_result)
    policy = CountingPolicy(selected="right")
    result = SimulationEngine(decision_policy=policy).run(definition())
    trace = next(item for item in result.scenarios[0].decision_trace if item.event_type == "decision")
    assert trace.action.action_id == "right"
    assert policy.decide_calls == 1
    assert trace.decision_context.objective_scores == {}


def test_only_feasible_candidates_reach_scorer_and_selection(monkeypatch):
    sim = definition()
    right = next(action for action in sim.action_definitions if action.id == "right")
    right.constraints = {"next_state": [{"variable": "count", "operator": "lte", "value": 0}]}
    seen = []
    def score(self, previews, state, objective):
        seen.append(set(previews))
        return score_rows(previews, {"left": 0.3})
    monkeypatch.setattr(ObjectiveScorer, "score_actions", score)
    policy = CountingPolicy()
    result = SimulationEngine(decision_policy=policy).run(sim)
    trace = next(item for item in result.scenarios[0].decision_trace if item.event_type == "decision")
    assert seen == [{"left"}]
    assert [action.action_id for action in trace.plausible_actions] == ["left"]
    assert trace.action.action_id == "left"
    assert policy.decide_calls == 0


def test_score_tie_uses_ambiguity_path_and_validator_runs_after_selection(monkeypatch):
    monkeypatch.setattr(ObjectiveScorer, "score_actions",
        lambda self, previews, state, objective: score_rows(previews, {"left": 0.5, "right": 0.5}))
    state = {"after_policy": False, "post_selection_validations": []}
    original = DecisionValidator.validate
    def track(self, agent, action, world, trigger, time):
        if state["after_policy"]:
            state["post_selection_validations"].append(action.id)
        return original(self, agent, action, world, trigger, time)
    monkeypatch.setattr(DecisionValidator, "validate", track)
    client = MockLLMClient(lambda context, prompt: DecisionResponse(primary_action="left"))
    policy = LLMDecisionPolicy(client)
    original_decide = policy.decide
    def tracked_decide(context, actions):
        response = original_decide(context, actions)
        state["after_policy"] = True
        return response
    policy.decide = tracked_decide
    result = SimulationEngine(decision_policy=policy).run(definition())
    trace = next(item for item in result.scenarios[0].decision_trace if item.event_type == "decision")
    assert trace.action.action_id == "left"
    assert trace.decision_source == "llm"
    assert state["post_selection_validations"] == ["left", "left"]


def test_agents_without_objective_configuration_keep_policy_behavior():
    policy = CountingPolicy(selected="right")
    result = SimulationEngine(decision_policy=policy).run(definition(scored=False))
    trace = next(item for item in result.scenarios[0].decision_trace if item.event_type == "decision")
    assert policy.decide_calls == 1
    assert trace.action.action_id == "right"
    assert trace.decision_source == "existing_policy_fallback"
    assert trace.decision_context.objective_scores == {}
