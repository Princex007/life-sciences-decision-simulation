import pytest

from app.agents.base import RuleBasedDecisionPolicy
from app.agents.cognition import DecisionResponse
from app.domain.definitions import SimulationDefinition
from app.evaluation.objective_scorer import ObjectiveScorer
from app.forecasting.clinical_outcomes import expected_clinical_outcomes
from app.forecasting.launch_forecast import LaunchForecast
from app.forecasting.registry import ForecastRegistry
from app.simulation.engine import SimulationEngine


class PhysicianPolicy(RuleBasedDecisionPolicy):
    def __init__(self, selected="maintain_adoption"):
        self.selected = selected
        self.decide_calls = 0

    def get_plausible_actions(self, context):
        return context.available_actions

    def decide(self, context, actions):
        self.decide_calls += 1
        return DecisionResponse(primary_action=self.selected)


def physician_definition():
    definition = SimulationDefinition.from_json("examples/us_drug_launch.json")
    definition.agents = [agent for agent in definition.agents if agent.id == "physician"]
    definition.action_definitions = [action for action in definition.action_definitions
                                     if action.agent_id == "physician"]
    definition.trigger_definitions = [trigger for trigger in definition.trigger_definitions
                                      if "physician" in trigger.affected_agents]
    definition.settings.time_horizon = 1
    definition.settings.initial_events = [event.model_copy(update={
        "id": "launch-for-physician", "event_type": "company_launch",
        "description": "Configured launch event"})
        for event in definition.settings.initial_events]
    definition.settings.scheduled_events = []
    return definition


def engine(policy):
    registry = ForecastRegistry()
    registry.register("launch_revenue", LaunchForecast())
    return SimulationEngine(registry, decision_policy=policy)


def physician_trace(result):
    return next(item for item in result.scenarios[0].decision_trace
                if item.event_type == "decision" and item.agent_id == "physician")


def test_physician_objective_loads_with_configured_metric_directions_and_weights():
    definition = SimulationDefinition.from_json("examples/us_drug_launch.json")
    objective = definition.evaluation_objectives["physician"]
    assert sum(item["weight"] for item in objective["components"]) == pytest.approx(1)
    assert [(item["metric"], item["preference"], item["weight"])
            for item in objective["components"]] == [
        ("expected_responders", "maximize", 0.5),
        ("expected_adverse_events", "minimize", 0.5),
    ]
    assert all(item["source"] == "clinical_outcomes" for item in objective["components"])
    assert "synthetic" in objective["label"].lower()
    assert "uncalibrated" in objective["label"].lower()
    assert "clinical equivalence" in objective["normalization_assumption"]


def test_generic_scorer_applies_responder_and_adverse_event_directions():
    objective = {
        "components": [
            {"name": "responders", "source": "clinical_outcomes",
             "metric": "expected_responders", "normalization": {
                 "method": "min_max", "minimum": 0, "maximum": 1000},
             "preference": "maximize", "weight": 0.5},
            {"name": "adverse_events", "source": "clinical_outcomes",
             "metric": "expected_adverse_events", "normalization": {
                 "method": "min_max", "minimum": 0, "maximum": 1000},
             "preference": "minimize", "weight": 0.5},
        ]
    }
    scores = ObjectiveScorer().score_actions({
        "more_responders": {"clinical_outcomes": {
            "expected_responders": 200, "expected_adverse_events": 100}},
        "fewer_adverse_events": {"clinical_outcomes": {
            "expected_responders": 100, "expected_adverse_events": 50}},
    }, {}, objective)
    assert scores["more_responders"]["components"]["responders"]["preference_value"] == 0.2
    assert scores["more_responders"]["components"]["adverse_events"]["preference_value"] == 0.9
    assert scores["fewer_adverse_events"]["components"]["adverse_events"]["preference_value"] == 0.95


def test_physician_decisive_scores_use_preview_metrics_and_validate_selected_action():
    definition = physician_definition()
    # A controlled test-only scale makes the real preview score margin decisive.
    for component in definition.evaluation_objectives["physician"]["components"]:
        component["normalization"]["maximum"] = 100_000
    definition.evaluation_objectives["physician"]["score_tie_tolerance"] = 0
    policy = PhysicianPolicy(selected="slow_adoption")
    result = engine(policy).run(definition)
    trace = physician_trace(result)
    previews = trace.decision_context.action_previews
    scores = trace.decision_context.objective_scores
    assert set(previews) == {"slow_adoption", "adopt", "maintain_adoption"}
    assert all(preview["clinical_outcomes"]["available"] for preview in previews.values())
    assert scores
    assert trace.action.action_id == max(scores, key=lambda action_id: scores[action_id]["score"])
    assert trace.decision_source == "objective_scorer"
    assert trace.validation_status == "valid"
    assert policy.decide_calls == 0


def test_ambiguous_physician_scores_use_existing_policy(monkeypatch):
    monkeypatch.setattr(ObjectiveScorer, "score_actions", lambda self, previews, state, objective: {
        action_id: {"score": 0.5, "components": {}} for action_id in previews
    })
    policy = PhysicianPolicy(selected="maintain_adoption")
    result = engine(policy).run(physician_definition())
    trace = physician_trace(result)
    assert policy.decide_calls == 1
    assert trace.action.action_id == "maintain_adoption"
    assert trace.decision_source == "existing_policy_fallback"


@pytest.mark.parametrize("invalid_kind", ["missing_rate", "invalid_rate", "missing_forecast"])
def test_unavailable_clinical_metrics_fall_back(invalid_kind):
    definition = physician_definition()
    if invalid_kind == "missing_rate":
        definition.clinical_outcome_assumptions.pop("treatment_response_rate")
    elif invalid_kind == "invalid_rate":
        definition.clinical_outcome_assumptions["adverse_event_rate"] = float("nan")
    else:
        definition.forecast_model_id = None
    policy = PhysicianPolicy(selected="maintain_adoption")
    result = engine(policy).run(definition)
    trace = physician_trace(result)
    assert policy.decide_calls == 1
    assert trace.action.action_id == "maintain_adoption"
    assert trace.decision_source == "existing_policy_fallback"
    assert trace.decision_context.objective_scores == {}


def test_infeasible_physician_action_is_filtered_before_scoring_and_selection():
    definition = physician_definition()
    adopt = next(action for action in definition.action_definitions if action.id == "adopt")
    adopt.constraints = {"next_state": {"physician_adoption": {"lte": 0.05}}}
    policy = PhysicianPolicy()
    result = engine(policy).run(definition)
    trace = physician_trace(result)
    scored_candidate_ids = set(trace.decision_context.objective_scores)
    assert "adopt" not in scored_candidate_ids
    assert set(trace.decision_context.action_previews) == scored_candidate_ids
    assert trace.action.action_id in scored_candidate_ids


def test_non_physician_objective_configurations_and_outcome_formulas_unchanged():
    definition = SimulationDefinition.from_json("examples/us_drug_launch.json")
    objectives = definition.evaluation_objectives
    assert [(item["name"], item["weight"]) for item in objectives["company"]["components"]] == [
        ("one_step_cumulative_sales", 1.0)]
    assert [(item["name"], item["weight"]) for item in objectives["competitor"]["components"]] == [
        ("competitor_market_share", 0.4), ("unit_contribution_rate", 0.4),
        ("promotion_budget_used", 0.2)]
    assert [(item["name"], item["weight"]) for item in objectives["payer"]["components"]] == [
        ("payer_access", 0.5), ("modeled_drug_expenditure_proxy", 0.5)]
    outcomes = expected_clinical_outcomes(100, {
        "treatment_response_rate": 0.60, "adverse_event_rate": 0.10,
    })
    assert outcomes["expected_responders"] == 60
    assert outcomes["expected_adverse_events"] == 10
