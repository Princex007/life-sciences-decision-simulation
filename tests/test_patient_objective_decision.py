import math

import pytest

from app.agents.base import RuleBasedDecisionPolicy
from app.agents.cognition import DecisionResponse
from app.domain.definitions import SimulationDefinition
from app.evaluation.objective_scorer import ObjectiveScorer
from app.forecasting.clinical_outcomes import expected_clinical_outcomes
from app.forecasting.launch_forecast import LaunchForecast
from app.forecasting.patient_affordability import estimate_patient_cost
from app.forecasting.registry import ForecastRegistry
from app.simulation.engine import SimulationEngine


class PatientPolicy(RuleBasedDecisionPolicy):
    def __init__(self, selected="moderate_adherence"):
        self.selected = selected
        self.decide_calls = {}

    def get_plausible_actions(self, context):
        return context.available_actions if context.agent_id == "patient" else context.available_actions[:1]

    def decide(self, context, actions):
        self.decide_calls[context.agent_id] = self.decide_calls.get(context.agent_id, 0) + 1
        action_ids = {action.id for action in actions}
        selected = self.selected if context.agent_id == "patient" and self.selected in action_ids else actions[0].id
        return DecisionResponse(primary_action=selected)


def patient_definition():
    definition = SimulationDefinition.from_json("examples/us_drug_launch.json")
    definition.settings.time_horizon = 1
    definition.settings.scheduled_events = []
    definition.scenario_generation.max_scenarios = 1
    return definition


def build_engine(policy):
    registry = ForecastRegistry()
    registry.register("launch_revenue", LaunchForecast())
    return SimulationEngine(registry, decision_policy=policy)


def patient_trace(result):
    return next(item for item in result.scenarios[0].decision_trace
                if item.event_type == "decision" and item.agent_id == "patient")


def test_patient_cost_assumptions_load_and_proxy_uses_configured_price_and_share():
    definition = SimulationDefinition.from_json("examples/us_drug_launch.json")
    assumptions = definition.patient_affordability_assumptions
    assert assumptions["patient_cost_share_fraction"] == 0.20
    assert "synthetic" in assumptions["label"].lower()
    assert "uncalibrated" in assumptions["label"].lower()
    assert "per treatment unit" in assumptions["unit"]
    result = estimate_patient_cost(60000, assumptions)
    assert result["available"] is True
    assert result["estimated_patient_cost"] == 12000
    assert result["projected_drug_price"] == 60000


@pytest.mark.parametrize("fraction", [None, -0.1, 1.01, math.inf, math.nan, True])
def test_missing_or_invalid_cost_share_marks_metric_unavailable(fraction):
    result = estimate_patient_cost(100000, {"patient_cost_share_fraction": fraction})
    assert result["available"] is False
    assert "reason" in result
    assert "estimated_patient_cost" not in result


def test_missing_or_invalid_projected_price_marks_metric_unavailable():
    assumptions = {"patient_cost_share_fraction": 0.2}
    assert estimate_patient_cost(None, assumptions)["available"] is False
    assert estimate_patient_cost(-1, assumptions)["available"] is False


def test_patient_objective_configuration_has_valid_weights_and_directions():
    definition = SimulationDefinition.from_json("examples/us_drug_launch.json")
    objective = definition.evaluation_objectives["patient"]
    assert sum(item["weight"] for item in objective["components"]) == pytest.approx(1)
    assert [(item["metric"], item["preference"], item["weight"])
            for item in objective["components"]] == [
        ("expected_responders", "maximize", 0.4),
        ("expected_adverse_events", "minimize", 0.3),
        ("estimated_patient_cost", "minimize", 0.3),
    ]
    assert all(item["source"] in {"clinical_outcomes", "patient_affordability"}
               for item in objective["components"])
    assert "uncalibrated" in objective["label"].lower()
    assert "clinical equivalence" in objective["normalization_assumption"]


def test_generic_scorer_rewards_lower_cost_and_uses_clinical_outcome_metrics():
    definition = SimulationDefinition.from_json("examples/us_drug_launch.json")
    objective = definition.evaluation_objectives["patient"]
    scores = ObjectiveScorer().score_actions({
        "lower_cost": {
            "clinical_outcomes": {"expected_responders": 100, "expected_adverse_events": 20},
            "patient_affordability": {"estimated_patient_cost": 10000},
        },
        "higher_cost": {
            "clinical_outcomes": {"expected_responders": 100, "expected_adverse_events": 20},
            "patient_affordability": {"estimated_patient_cost": 20000},
        },
    }, {}, objective)
    assert scores["lower_cost"]["score"] > scores["higher_cost"]["score"]
    assert scores["lower_cost"]["components"]["estimated_patient_cost"]["preference_value"] > \
        scores["higher_cost"]["components"]["estimated_patient_cost"]["preference_value"]


def test_generic_scorer_rejects_weights_that_do_not_sum_to_one():
    definition = SimulationDefinition.from_json("examples/us_drug_launch.json")
    objective = definition.evaluation_objectives["patient"].copy()
    objective["components"] = [dict(item) for item in objective["components"]]
    objective["components"][0]["weight"] = 0.9
    with pytest.raises(ValueError, match="sum to 1"):
        ObjectiveScorer().score_actions({}, {}, objective)


def test_patient_objective_selects_highest_scoring_feasible_action_and_validates():
    definition = patient_definition()
    # Test-only tolerance makes any nonzero production-configured score margin decisive.
    definition.evaluation_objectives["patient"]["score_tie_tolerance"] = 0
    policy = PatientPolicy()
    result = build_engine(policy).run(definition)
    trace = patient_trace(result)
    previews = trace.decision_context.action_previews
    scores = trace.decision_context.objective_scores
    assert set(previews) == {"high_adherence", "moderate_adherence"}
    assert all(preview["clinical_outcomes"]["available"] for preview in previews.values())
    assert all(preview["patient_affordability"]["available"] for preview in previews.values())
    assert all(preview["patient_affordability"]["estimated_patient_cost"] == 20000
               for preview in previews.values())
    assert all("market_share" not in preview["after_action_changes"] for preview in previews.values())
    assert trace.previous_world_state.get("patient_adherence_rate") == 0.60
    assert previews["high_adherence"]["after_action_changes"]["patient_adherence_rate"]["to"] == 0.75
    assert previews["high_adherence"]["forecast_metrics"]["market_share"] > \
        previews["moderate_adherence"]["forecast_metrics"]["market_share"]
    assert scores["high_adherence"]["score"] > scores["moderate_adherence"]["score"]
    assert trace.action.action_id == "high_adherence"
    assert trace.decision_source == "objective_scorer"
    assert trace.decision_response.validation_status == "valid"
    assert len(result.scenarios) == 1
    assert result.scenarios[0].final_state.get("patient_adherence_rate") == 0.75
    assert policy.decide_calls.get("patient", 0) == 0


def test_ambiguous_patient_scores_use_existing_policy(monkeypatch):
    monkeypatch.setattr(ObjectiveScorer, "score_actions", lambda self, previews, state, objective: {
        action_id: {"score": 0.5, "components": {}} for action_id in previews
    })
    policy = PatientPolicy(selected="moderate_adherence")
    trace = patient_trace(build_engine(policy).run(patient_definition()))
    assert policy.decide_calls.get("patient", 0) == 1
    assert trace.action.action_id == "moderate_adherence"
    assert trace.decision_source == "existing_policy_fallback"
    assert trace.decision_response.validation_status == "valid"


@pytest.mark.parametrize("missing", ["cost_share", "clinical_rate"])
def test_unavailable_objective_metrics_use_existing_policy_fallback(missing):
    definition = patient_definition()
    if missing == "cost_share":
        definition.patient_affordability_assumptions = {}
    else:
        definition.clinical_outcome_assumptions.pop("adverse_event_rate")
    policy = PatientPolicy(selected="moderate_adherence")
    trace = patient_trace(build_engine(policy).run(definition))
    assert policy.decide_calls.get("patient", 0) == 1
    assert trace.action.action_id == "moderate_adherence"
    assert trace.decision_source == "existing_policy_fallback"
    assert trace.decision_context.objective_scores == {}


def test_infeasible_action_is_excluded_before_patient_scoring():
    definition = patient_definition()
    moderate = next(item for item in definition.action_definitions
                    if item.id == "moderate_adherence")
    moderate.constraints = {"next_state": {"patient_adherence_rate": {"min": 0.7}}}
    policy = PatientPolicy(selected="high_adherence")
    trace = patient_trace(build_engine(policy).run(definition))
    assert set(trace.decision_context.action_previews) == {"high_adherence"}
    assert set(trace.decision_context.objective_scores) == {"high_adherence"}
    assert trace.action.action_id == "high_adherence"
    assert trace.decision_response.validation_status == "valid"


def test_other_stakeholder_scores_and_clinical_formula_are_unchanged():
    definition = SimulationDefinition.from_json("examples/us_drug_launch.json")
    objectives = definition.evaluation_objectives
    assert [(item["name"], item["weight"]) for item in objectives["company"]["components"]] == [
        ("one_step_cumulative_sales", 1.0)]
    assert [(item["name"], item["weight"]) for item in objectives["competitor"]["components"]] == [
        ("competitor_market_share", 0.4), ("unit_contribution_rate", 0.4),
        ("promotion_budget_used", 0.2)]
    assert [(item["name"], item["weight"]) for item in objectives["payer"]["components"]] == [
        ("payer_access", 0.5), ("modeled_drug_expenditure_proxy", 0.5)]
    assert [(item["name"], item["weight"]) for item in objectives["physician"]["components"]] == [
        ("expected_responders", 0.5), ("expected_adverse_events", 0.5)]
    outcomes = expected_clinical_outcomes(100, {
        "treatment_response_rate": 0.60, "adverse_event_rate": 0.10,
    })
    assert outcomes["expected_responders"] == 60
    assert outcomes["expected_adverse_events"] == 10
    patient = next(agent for agent in definition.agents if agent.id == "patient")
    assert patient.available_actions == ["high_adherence", "moderate_adherence"]
    patient_trigger = next(trigger for trigger in definition.trigger_definitions
                           if trigger.id == "patient-launch-response")
    assert patient_trigger.event_types == ["company_launch"]
