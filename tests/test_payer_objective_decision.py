import pytest

from app.agents.base import RuleBasedDecisionPolicy
from app.agents.cognition import DecisionResponse
from app.domain.definitions import SimulationDefinition
from app.evaluation.objective_scorer import ObjectiveScorer
from app.forecasting.launch_forecast import LaunchForecast
from app.forecasting.registry import ForecastRegistry
from app.simulation.decision_validator import DecisionValidator
from app.simulation.engine import SimulationEngine


ACCESS_ACTIONS = ("restricted_access", "standard_access", "favorable_access")


def payer_slice(*, forecast=True):
    definition = SimulationDefinition.from_json("examples/us_drug_launch.json")
    definition.agents = [agent for agent in definition.agents if agent.id == "payer"]
    definition.action_definitions = [action for action in definition.action_definitions
                                     if action.agent_id == "payer"]
    definition.trigger_definitions = [trigger for trigger in definition.trigger_definitions
                                      if "payer" in trigger.affected_agents]
    definition.settings.time_horizon = 1
    definition.settings.initial_events = [event.model_copy(update={
        "id": "payer-review-start", "event_type": "payer_review", "description": "Payer review"})
        for event in definition.settings.initial_events]
    definition.settings.scheduled_events = []
    if not forecast:
        definition.forecast_model_id = None
    return definition


def build_engine(policy):
    registry = ForecastRegistry()
    registry.register("launch_revenue", LaunchForecast())
    return SimulationEngine(registry, decision_policy=policy)


class PayerPolicy(RuleBasedDecisionPolicy):
    def __init__(self, selected="standard_access"):
        self.selected = selected
        self.decide_calls = 0

    def get_plausible_actions(self, context):
        return context.available_actions

    def decide(self, context, actions):
        self.decide_calls += 1
        return DecisionResponse(primary_action=self.selected)


def scores_for(values):
    return {action_id: {"score": score, "components": {"controlled": {
        "raw_value": score, "normalized_value": score, "preference_value": score,
        "weight": 1.0, "weighted_contribution": score}}} for action_id, score in values.items()}


def payer_trace(result):
    return next(item for item in result.scenarios[0].decision_trace
                if item.event_type == "decision" and item.agent_id == "payer")


def test_payer_configuration_loads_and_other_stakeholder_scores_are_unchanged():
    definition = SimulationDefinition.from_json("examples/us_drug_launch.json")
    objective = definition.evaluation_objectives["payer"]
    assert sum(component["weight"] for component in objective["components"]) == pytest.approx(1)
    assert [(item["name"], item["preference"], item["weight"])
            for item in objective["components"]] == [
        ("payer_access", "maximize", 0.5),
        ("modeled_drug_expenditure_proxy", "minimize", 0.5),
    ]
    assert objective["score_tie_tolerance"] == 0.005
    assert objective["components"][0]["normalization"]["minimum"] == 0
    assert objective["components"][0]["normalization"]["maximum"] == 1
    assert objective["components"][1]["normalization"]["minimum"] == 0
    assert objective["components"][1]["normalization"]["maximum"] == 2_000_000_000
    assert "illustrative" in objective["label"].lower()
    assert "not actual payer net expenditure" in objective["limitations"]
    company = definition.evaluation_objectives["company"]["components"]
    competitor = definition.evaluation_objectives["competitor"]["components"]
    assert [(item["name"], item["weight"]) for item in company] == [
        ("one_step_cumulative_sales", 1.0)]
    assert [(item["name"], item["weight"]) for item in competitor] == [
        ("competitor_market_share", 0.4), ("unit_contribution_rate", 0.4),
        ("promotion_budget_used", 0.2)]


def test_feasible_payer_actions_get_valid_scores_and_access_expenditure_components():
    result = build_engine(PayerPolicy()).run(payer_slice())
    trace = payer_trace(result)
    assert set(trace.decision_context.action_previews) == set(ACCESS_ACTIONS)
    scores = trace.decision_context.objective_scores
    assert set(scores) == set(ACCESS_ACTIONS)
    access = {action: scores[action]["components"]["payer_access"]["raw_value"]
              for action in ACCESS_ACTIONS}
    expenditure = {action: scores[action]["components"]["modeled_drug_expenditure_proxy"]["raw_value"]
                   for action in ACCESS_ACTIONS}
    assert access == {"restricted_access": 0.55, "standard_access": 0.75,
                      "favorable_access": 0.9}
    assert expenditure["restricted_access"] < expenditure["standard_access"] < expenditure["favorable_access"]
    assert scores["favorable_access"]["components"]["payer_access"]["weighted_contribution"] > \
        scores["standard_access"]["components"]["payer_access"]["weighted_contribution"]
    assert scores["favorable_access"]["components"]["modeled_drug_expenditure_proxy"]["weighted_contribution"] < \
        scores["standard_access"]["components"]["modeled_drug_expenditure_proxy"]["weighted_contribution"]


def test_decisive_payer_score_selects_highest_feasible_without_policy(monkeypatch):
    monkeypatch.setattr(ObjectiveScorer, "score_actions",
        lambda self, previews, state, objective: scores_for({
            "restricted_access": 0.1, "standard_access": 0.2, "favorable_access": 0.8}))
    policy = PayerPolicy()
    result = build_engine(policy).run(payer_slice())
    trace = payer_trace(result)
    assert trace.action.action_id == "favorable_access"
    assert trace.decision_source == "objective_scorer"
    assert policy.decide_calls == 0


def test_ambiguous_payer_scores_use_existing_policy_and_keep_validation(monkeypatch):
    monkeypatch.setattr(ObjectiveScorer, "score_actions",
        lambda self, previews, state, objective: scores_for({action: 0.5 for action in ACCESS_ACTIONS}))
    state = {"policy_returned": False, "post_policy_validation": []}
    original_validate = DecisionValidator.validate
    def track(self, agent, action, world, trigger, time):
        if state["policy_returned"]:
            state["post_policy_validation"].append(action.id)
        return original_validate(self, agent, action, world, trigger, time)
    monkeypatch.setattr(DecisionValidator, "validate", track)
    policy = PayerPolicy(selected="restricted_access")
    original_decide = policy.decide
    def tracked_decide(context, actions):
        response = original_decide(context, actions)
        state["policy_returned"] = True
        return response
    policy.decide = tracked_decide
    result = build_engine(policy).run(payer_slice())
    trace = payer_trace(result)
    assert policy.decide_calls == 1
    assert trace.action.action_id == "restricted_access"
    assert trace.decision_source == "existing_policy_fallback"
    assert state["post_policy_validation"] == ["restricted_access", "restricted_access"]


@pytest.mark.parametrize("scenario", ["missing_forecast", "invalid_bounds"])
def test_unavailable_or_invalid_payer_metric_uses_existing_policy(scenario):
    definition = payer_slice(forecast=scenario != "missing_forecast")
    if scenario == "invalid_bounds":
        definition.evaluation_objectives["payer"]["components"][1]["normalization"]["maximum"] = 1
    policy = PayerPolicy(selected="standard_access")
    result = build_engine(policy).run(definition)
    trace = payer_trace(result)
    assert policy.decide_calls == 1
    assert trace.action.action_id == "standard_access"
    assert trace.decision_source == "existing_policy_fallback"
    assert trace.decision_context.objective_scores == {}


def test_infeasible_payer_action_is_filtered_before_scoring(monkeypatch):
    definition = payer_slice()
    favorable = next(action for action in definition.action_definitions
                     if action.id == "favorable_access")
    favorable.constraints = {"next_state": {"payer_access": {"max": 0.8}}}
    scored_candidates = []
    original_score = ObjectiveScorer.score_actions
    def recording_score(self, previews, state, objective):
        scored_candidates.append(set(previews))
        return original_score(self, previews, state, objective)
    monkeypatch.setattr(ObjectiveScorer, "score_actions", recording_score)
    result = build_engine(PayerPolicy()).run(definition)
    trace = payer_trace(result)
    assert scored_candidates == [{"restricted_access", "standard_access"}]
    assert set(trace.decision_context.objective_scores) == scored_candidates[0]
