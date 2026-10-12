import pytest

from app.agents.base import RuleBasedDecisionPolicy
from app.agents.cognition import DecisionResponse
from app.domain.definitions import SimulationDefinition
from app.evaluation.objective_scorer import ObjectiveScorer
from app.forecasting.launch_forecast import LaunchForecast
from app.forecasting.registry import ForecastRegistry
from app.simulation.decision_validator import DecisionValidator
from app.simulation.engine import SimulationEngine


def company_definition(*, forecast=True):
    data = {
        "metadata": {"id": "company-score-test", "name": "Company Scorer Test"},
        "initial_world_state": {"variables": {"drug_price": 100, "market_share": 0.1,
            "addressable_patients": 1000, "diagnosis_rate": 1, "treatment_rate": 1,
            "payer_access": 1}},
        "evaluation_objectives": {"company": {
            "label": "Illustrative test configuration",
            "score_tie_tolerance": 0.005,
            "components": [{"name": "one_step_cumulative_sales", "source": "forecast_metrics",
                "metric": "cumulative_sales", "normalization": {"method": "min_max",
                "minimum": 0, "maximum": 1000000}, "preference": "maximize", "weight": 1.0}]}},
        "agents": [{"id": "company", "name": "Company", "objective": "maximize forecast sales",
            "observable_state": ["drug_price", "market_share", "addressable_patients",
                "diagnosis_rate", "treatment_rate", "payer_access"],
            "available_actions": ["raise_price", "lower_price"],
            "decision_policy": {"default_actions": ["raise_price", "lower_price"]}}],
        "action_definitions": [
            {"id": "raise_price", "name": "Raise price", "agent_id": "company",
             "effects": [{"variable": "drug_price", "operation": "set", "value": 200}]},
            {"id": "lower_price", "name": "Lower price", "agent_id": "company",
             "effects": [{"variable": "drug_price", "operation": "set", "value": 80}]},
        ],
        "trigger_definitions": [{"id": "start", "event_types": ["simulation_start"],
                                  "affected_agents": ["company"]}],
        "transition_rules": [{"id": "share-step", "event_type": "time_step",
            "effects": [{"variable": "market_share", "operation": "add", "value": 0.05,
                         "maximum": 0.8}]}],
        "settings": {"time_horizon": 1, "initial_events": [{"id": "start", "time": 0,
            "event_type": "simulation_start", "description": "Start"}]},
        "scenario_generation": {"policy": "exhaustive", "max_scenarios": None},
    }
    if forecast:
        data["forecast_model_id"] = "launch_revenue"
    return SimulationDefinition.model_validate(data)


def engine(policy):
    registry = ForecastRegistry()
    registry.register("launch_revenue", LaunchForecast())
    return SimulationEngine(registry, decision_policy=policy)


def configured_company_slice():
    definition = SimulationDefinition.from_json("examples/us_drug_launch.json")
    definition.agents = [agent for agent in definition.agents if agent.id == "company"]
    definition.action_definitions = [action for action in definition.action_definitions
                                     if action.agent_id == "company"]
    definition.trigger_definitions = [trigger for trigger in definition.trigger_definitions
                                      if "company" in trigger.affected_agents]
    definition.settings.time_horizon = 1
    definition.settings.scheduled_events = []
    return definition


class CountingPolicy(RuleBasedDecisionPolicy):
    def __init__(self, selected="lower_price"):
        self.selected = selected
        self.decide_calls = 0

    def decide(self, context, actions):
        self.decide_calls += 1
        return DecisionResponse(primary_action=self.selected)


def decision_trace(result):
    return next(item for item in result.scenarios[0].decision_trace if item.event_type == "decision")


def test_company_preview_scores_existing_forecast_metric_and_decisive_choice():
    definition = company_definition()
    policy = CountingPolicy()
    result = engine(policy).run(definition)
    trace = decision_trace(result)

    previews = trace.decision_context.action_previews
    scores = trace.decision_context.objective_scores
    assert set(previews) == {"raise_price", "lower_price"}
    assert all("cumulative_sales" in preview["forecast_metrics"] for preview in previews.values())
    assert all(scores[action]["score"] == pytest.approx(
        scores[action]["components"]["one_step_cumulative_sales"]["normalized_value"])
        for action in scores)
    assert scores["raise_price"]["score"] > scores["lower_price"]["score"]
    assert trace.action.action_id == "raise_price"
    assert trace.decision_source == "objective_scorer"
    assert policy.decide_calls == 0


def test_configured_company_actions_are_feasible_and_forecast_differentiates_them():
    definition = configured_company_slice()
    policy = CountingPolicy(selected="launch_discounted")
    result = engine(policy).run(definition)
    trace = decision_trace(result)
    previews = trace.decision_context.action_previews
    assert set(previews) == {"launch", "launch_discounted"}
    scores = trace.decision_context.objective_scores
    reference = previews["launch"]["forecast_metrics"]["cumulative_sales"]
    discounted = previews["launch_discounted"]["forecast_metrics"]["cumulative_sales"]
    assert reference != discounted
    assert scores["launch"]["score"] != scores["launch_discounted"]["score"]
    assert trace.action.action_id == "launch"
    assert trace.decision_source == "objective_scorer"
    assert policy.decide_calls == 0


def test_infeasible_discounted_price_is_removed_before_scoring():
    definition = configured_company_slice()
    definition.initial_world_state.set("company_discounted_price_assumption", 0)
    policy = CountingPolicy()
    result = engine(policy).run(definition)
    trace = decision_trace(result)
    assert [action.action_id for action in trace.plausible_actions] == ["launch"]
    assert set(trace.decision_context.action_previews) == {"launch"}
    assert set(trace.decision_context.objective_scores) == {"launch"}
    assert trace.action.action_id == "launch"
    assert policy.decide_calls == 0


def test_company_ambiguous_scores_delegate_to_existing_policy(monkeypatch):
    original = ObjectiveScorer.score_actions
    def tied(self, previews, state, objective):
        scores = original(self, previews, state, objective)
        for item in scores.values():
            item["score"] = 0.5
        return scores
    monkeypatch.setattr(ObjectiveScorer, "score_actions", tied)
    policy = CountingPolicy(selected="lower_price")
    result = engine(policy).run(company_definition())
    trace = decision_trace(result)
    assert policy.decide_calls == 1
    assert trace.action.action_id == "lower_price"
    assert trace.decision_source == "existing_policy_fallback"
    assert trace.objective_score_margin == pytest.approx(0)


@pytest.mark.parametrize("kind", ["missing", "invalid"])
def test_missing_or_invalid_company_forecast_metrics_fall_back(kind):
    definition = company_definition(forecast=kind != "missing")
    if kind == "invalid":
        definition.evaluation_objectives["company"]["components"][0]["normalization"]["maximum"] = 1
    policy = CountingPolicy(selected="lower_price")
    result = engine(policy).run(definition)
    trace = decision_trace(result)
    assert policy.decide_calls == 1
    assert trace.action.action_id == "lower_price"
    assert trace.decision_source == "existing_policy_fallback"
    assert trace.decision_context.objective_scores == {}


def test_company_policy_selection_still_receives_post_selection_validation(monkeypatch):
    original_score = ObjectiveScorer.score_actions
    def tied(self, previews, state, objective):
        scores = original_score(self, previews, state, objective)
        for item in scores.values():
            item["score"] = 0.5
        return scores
    monkeypatch.setattr(ObjectiveScorer, "score_actions", tied)
    state = {"policy_returned": False, "validated_after_policy": []}
    original_validate = DecisionValidator.validate
    def track(self, agent, action, world, trigger, time):
        if state["policy_returned"]:
            state["validated_after_policy"].append(action.id)
        return original_validate(self, agent, action, world, trigger, time)
    monkeypatch.setattr(DecisionValidator, "validate", track)
    policy = CountingPolicy(selected="lower_price")
    original_decide = policy.decide
    def tracked_decide(context, actions):
        response = original_decide(context, actions)
        state["policy_returned"] = True
        return response
    policy.decide = tracked_decide
    result = engine(policy).run(company_definition())
    assert decision_trace(result).action.action_id == "lower_price"
    assert state["validated_after_policy"] == ["lower_price", "lower_price"]


def test_competitor_objective_configuration_and_weights_are_unchanged():
    definition = SimulationDefinition.from_json("examples/us_drug_launch.json")
    objective = definition.evaluation_objectives["competitor"]
    assert [(item["name"], item["weight"]) for item in objective["components"]] == [
        ("competitor_market_share", 0.4),
        ("unit_contribution_rate", 0.4),
        ("promotion_budget_used", 0.2),
    ]
    company_objective = definition.evaluation_objectives["company"]
    component = company_objective["components"][0]
    assert company_objective["score_tie_tolerance"] == 0.005
    assert component["source"] == "forecast_metrics"
    assert component["metric"] == "cumulative_sales"
    assert component["weight"] == 1.0
    assert component["normalization"]["maximum"] == 2_000_000_000
    assert "illustrative" in company_objective["normalization_assumption"]
    company = next(agent for agent in definition.agents if agent.id == "company")
    assert {"addressable_patients", "diagnosis_rate", "treatment_rate", "net_price"}.issubset(
        set(company.observable_state))
