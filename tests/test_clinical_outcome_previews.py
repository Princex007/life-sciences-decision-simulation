import math
from pathlib import Path

import pytest

from app.domain.definitions import SimulationDefinition
from app.domain.world import WorldState
from app.forecasting.clinical_outcomes import expected_clinical_outcomes
from app.forecasting.launch_forecast import LaunchForecast
from app.simulation.engine import SimulationEngine
from app.simulation.state_transition import StateTransitionSystem


SCENARIO = Path(__file__).parents[1] / "examples" / "us_drug_launch.json"


def test_expected_counts_use_configured_rates_and_keep_outcomes_separate():
    result = expected_clinical_outcomes(100, {
        "treatment_response_rate": 0.6,
        "adverse_event_rate": 0.1,
        "forecast_horizon": "current plus next step",
        "label": "synthetic illustrative uncalibrated",
    })
    assert result["available"] is True
    assert result["expected_responders"] == 60
    assert result["expected_adverse_events"] == 10
    assert result["forecast_horizon"] == "current plus next step"


@pytest.mark.parametrize("assumptions", [
    {},
    {"treatment_response_rate": 0.5},
    {"treatment_response_rate": math.nan, "adverse_event_rate": 0.1},
    {"treatment_response_rate": 1.01, "adverse_event_rate": 0.1},
    {"treatment_response_rate": 0.5, "adverse_event_rate": -0.1},
])
def test_missing_or_invalid_rates_mark_outcomes_unavailable(assumptions):
    result = expected_clinical_outcomes(100, assumptions)
    assert result["available"] is False
    assert "reason" in result
    assert "expected_responders" not in result
    assert "expected_adverse_events" not in result


def test_valid_rates_without_forecast_treated_count_are_unavailable():
    result = expected_clinical_outcomes(None, {
        "treatment_response_rate": 0.6,
        "adverse_event_rate": 0.1,
    })
    assert result["available"] is False
    assert "patients_treated" in result["reason"]


def test_action_previews_add_clinical_counts_without_mutating_world():
    definition = SimulationDefinition.from_json(str(SCENARIO))
    agent = next(item for item in definition.agents if item.id == "competitor")
    actions = [item for item in definition.action_definitions
               if item.id in {"increase_promotion", "aggressive_price_cut"}]
    world = definition.initial_world_state.model_copy(deep=True)
    world.set("competitor_price", 110000)
    original = world.model_copy(deep=True)

    previews = SimulationEngine._build_action_previews(
        world, agent, actions, definition, StateTransitionSystem(), 0, LaunchForecast())

    assert world.model_dump() == original.model_dump()
    assert set(previews) == {"increase_promotion", "aggressive_price_cut"}
    outcomes = [previews[action.id]["clinical_outcomes"] for action in actions]
    assert all(outcome["available"] for outcome in outcomes)
    assert all(outcome["expected_responders"] ==
               outcome["patients_treated"] * 0.60 for outcome in outcomes)
    assert all(outcome["expected_adverse_events"] ==
               outcome["patients_treated"] * 0.10 for outcome in outcomes)
    assert outcomes[0]["patients_treated"] != outcomes[1]["patients_treated"]
    assert outcomes[0]["expected_responders"] != outcomes[1]["expected_responders"]


def test_scenario_rates_are_explicitly_labeled_synthetic_and_forecast_scoped():
    definition = SimulationDefinition.from_json(str(SCENARIO))
    assumptions = definition.clinical_outcome_assumptions
    assert assumptions["treatment_response_rate"] == 0.60
    assert assumptions["adverse_event_rate"] == 0.10
    assert "synthetic" in assumptions["label"].lower()
    assert "uncalibrated" in assumptions["label"].lower()
    assert "two-snapshot" in assumptions["forecast_horizon"]
