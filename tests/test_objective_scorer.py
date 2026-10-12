from copy import deepcopy
from pathlib import Path

import pytest

from app.domain.definitions import SimulationDefinition
from app.domain.world import WorldState
from app.evaluation.objective_scorer import ObjectiveScorer


def test_competitor_objective_score_uses_configured_normalization_and_weights():
    definition = SimulationDefinition.from_json(
        str(Path(__file__).parents[1] / "examples" / "us_drug_launch.json"))
    objective = definition.evaluation_objectives["competitor"]
    assert "Illustrative" in objective["label"]
    assert "not modeled" in objective["limitations"]
    assert sum(item["weight"] for item in objective["components"]) == pytest.approx(1.0)
    assert {item["name"] for item in objective["components"]} == {
        "competitor_market_share", "unit_contribution_rate", "promotion_budget_used"}

    state = WorldState(variables={
        "competitor_price": 90000,
        "competitor_promotion_spend": 0,
        "competitor_promotion_budget_assumption": 1000000,
    })
    original = state.model_copy(deep=True)
    previews = {"sample-action": {
        "after_action_changes": {
            "competitor_price": {"from": 90000, "to": 100000},
            "competitor_promotion_spend": {"from": 0, "to": 400000},
        },
        "configured_derived_metrics": {"competitor_unit_contribution_after_action": 25000},
        "after_next_time_step": {"competitor_market_share": 0.5},
    }}

    score = ObjectiveScorer().score_actions(previews, state, objective)["sample-action"]
    assert score["components"]["competitor_market_share"]["normalized_value"] == pytest.approx(0.6)
    assert score["components"]["unit_contribution_rate"]["normalized_value"] == pytest.approx(0.25)
    assert score["components"]["promotion_budget_used"]["preference_value"] == pytest.approx(0.6)
    assert score["score"] == pytest.approx(0.46)
    assert state.model_dump() == original.model_dump()


def test_objective_scorer_rejects_uncalibrated_weight_sum_mismatch():
    definition = SimulationDefinition.from_json(
        str(Path(__file__).parents[1] / "examples" / "us_drug_launch.json"))
    objective = deepcopy(definition.evaluation_objectives["competitor"])
    objective["components"][0]["weight"] = 0.5

    with pytest.raises(ValueError, match="sum to 1"):
        ObjectiveScorer().score_actions({}, {}, objective)
