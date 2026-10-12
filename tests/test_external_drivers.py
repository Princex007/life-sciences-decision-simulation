"""Bounded integration tests for the external environment / macro-driver layer."""
from pathlib import Path

import pytest

from app.domain.definitions import SimulationDefinition
from app.forecasting.registry import ForecastRegistry
from app.forecasting.state_metrics import StateMetricsForecast
from app.simulation.engine import SimulationEngine
from app.simulation.external_drivers import (apply_external_drivers,
                                             compile_external_drivers,
                                             scale_value,
                                             validate_external_drivers)

EXAMPLE = str(Path(__file__).parents[1] / "examples" / "ai_drug_discovery.json")


def engine():
    registry = ForecastRegistry()
    registry.register("state_metrics", StateMetricsForecast())
    return SimulationEngine(registry)


def load(variant=None):
    definition = SimulationDefinition.from_json(EXAMPLE)
    if variant:
        definition.external_drivers[0].active_variant = variant
    return definition


def run(variant=None):
    return engine().run(load(variant))


def test_driver_compiles_into_scheduled_events_and_transition_rules_only():
    """Drivers reuse the existing deterministic machinery; they add no new path."""
    definition = load()
    working, plan = apply_external_drivers(definition)

    assert plan.active_driver_ids == ["ai_discovery"]
    assert working is not definition
    assert not definition.settings.scheduled_events
    assert not any(rule.id.startswith("driver-rule:") for rule in definition.transition_rules)
    assert working.settings.scheduled_events
    assert all(rule.id.startswith("driver-rule:") for rule in plan.transition_rules)

    # Every compiled event has exactly one matching rule set, and the stable
    # signal event type carries no numeric rule so it stays information-only.
    signal_events = [item for item in plan.scheduled_events
                     if item.event_type == "external_driver_ai_discovery"]
    assert len(signal_events) == 5
    assert not any(rule.event_type == "external_driver_ai_discovery"
                   for rule in plan.transition_rules)


def test_indicator_variable_is_initialized_and_observable_by_configured_agents():
    working, plan = apply_external_drivers(load())
    assert working.initial_world_state.get("ai_discovery_adoption_index") == 0.1

    metadata = plan.indicator_metadata["ai_discovery_adoption_index"]
    assert metadata["source"] == "external_driver"
    assert metadata["evidence_grade"] == "synthetic_illustrative"
    assert metadata["assumption_labels"]

    observable = {agent.id: agent.observable_state for agent in working.agents}
    assert "ai_discovery_adoption_index" in observable["company"]
    assert "ai_discovery_adoption_index" in observable["competitor"]


def test_information_pathway_respects_observable_from():
    """observable_from is 1, so period 0 must not carry an indicator write."""
    result = run("accelerated")
    writes = [item for item in result.driver_impacts if item.pathway == "information"]
    assert [item.effect_time for item in writes] == [1, 2, 3, 4, 5]
    assert [item.applied_value for item in writes] == [0.25, 0.4, 0.55, 0.65, 0.72]


def test_agents_observe_the_driver_signal_and_decide_after_it():
    result = run("accelerated")
    decisions = [trace for trace in result.scenarios[0].decision_trace
                 if trace.event_type == "decision" and trace.agent_id == "company"]
    assert decisions[0].time == 0
    assert all(item.time in {1, 2, 3, 4, 5} for item in decisions[1:])
    assert all("signal observed" in item.trigger for item in decisions[1:])
    later = decisions[-1]
    assert later.observations["ai_discovery_adoption_index"] == 0.72


def test_world_state_pathway_honors_configured_lag():
    result = run("accelerated")
    by_target = {}
    for impact in result.driver_impacts:
        if impact.pathway == "world_state":
            by_target.setdefault(impact.target_variable, []).append(impact)

    assert {impact.lag for impact in by_target["discovery_candidates"]} == {0}
    assert {impact.lag for impact in by_target["rd_cycle_time_years"]} == {1}
    assert {impact.lag for impact in by_target["competitor_pipeline_years"]} == {2}

    for impacts in by_target.values():
        for impact in impacts:
            assert impact.effect_time == impact.source_time + impact.lag
            assert impact.effect_time <= 5


def test_qualitative_pathway_is_reported_and_never_applied():
    result = run("accelerated")
    assert len(result.driver_hypotheses) == 1
    hypothesis = result.driver_hypotheses[0]
    assert hypothesis.target_variable == "probability_of_technical_success"
    assert hypothesis.status == "qualitative_hypothesis_not_applied"
    assert hypothesis.evidence_grade == "model_hypothesis"

    assert "probability_of_technical_success" not in result.scenarios[0].final_state.as_variables()
    assert not any(impact.target_variable == "probability_of_technical_success"
                   for impact in result.driver_impacts)


def test_transition_bounds_are_enforced_on_driver_effects():
    """Competitive intensity and candidate counts stay inside configured bounds."""
    for variant in ("conservative", "accelerated", "disruptive"):
        state = run(variant).scenarios[0].final_state.as_variables()
        assert 0 <= state["competitive_intensity"] <= 1
        assert state["discovery_candidates"] >= 0
        assert state["rd_cycle_time_years"] >= 1.0
        assert state["competitor_pipeline_years"] >= 1.0
        assert state["rd_cost_index"] >= 40


def test_variants_change_only_configured_pathways_and_are_monotonic():
    outcomes = {variant: run(variant).scenarios[0].final_state.as_variables()
                for variant in ("conservative", "accelerated", "disruptive")}

    for variable in ("discovery_candidates", "competitive_intensity"):
        assert outcomes["conservative"][variable] < outcomes["accelerated"][variable] \
            < outcomes["disruptive"][variable], variable
    for variable in ("rd_cycle_time_years", "rd_cost_index", "competitor_pipeline_years"):
        assert outcomes["conservative"][variable] > outcomes["accelerated"][variable] \
            > outcomes["disruptive"][variable], variable

    # The driver must not reach variables it has no configured pathway to.
    assert {outcomes[variant]["company_ai_allocation"] for variant in outcomes} == \
        {outcomes["accelerated"]["company_ai_allocation"]}


def test_driver_runs_are_reproducible_and_branches_stay_isolated():
    first = run("accelerated")
    second = run("accelerated")
    assert first.model_dump() == second.model_dump()

    states = [id(scenario.final_state) for scenario in first.scenarios]
    assert len(set(states)) == len(states)
    assert all(scenario.key_drivers == ["ai_discovery"] for scenario in first.scenarios)


def test_disabled_driver_contributes_nothing():
    definition = load("disruptive")
    definition.external_drivers[0].enabled = False
    working, plan = apply_external_drivers(definition)
    assert working is definition
    assert plan.is_empty()

    result = engine().run(definition)
    assert result.driver_impacts == []
    assert result.scenarios[0].key_drivers == []
    assert "ai_discovery_adoption_index" not in result.scenarios[0].final_state.as_variables()


def test_definition_without_drivers_is_unchanged():
    definition = SimulationDefinition.from_json(
        str(Path(__file__).parents[1] / "examples" / "us_drug_launch.json"))
    working, plan = apply_external_drivers(definition)
    assert working is definition
    assert plan.is_empty()
    assert validate_external_drivers(definition) == []


def test_scale_value_only_scales_numeric_relative_operations():
    assert scale_value("add", 4, 0.5) == 2.0
    assert scale_value("subtract", 0.3, 2.0) == pytest.approx(0.6)
    assert scale_value("multiply", 0.97, 0.0) == pytest.approx(1.0)
    assert scale_value("multiply", 0.97, 1.0) == pytest.approx(0.97)
    assert scale_value("set", 7, 0.5) == 7
    assert scale_value("divide", 2, 0.5) == 2
    assert scale_value("add", "rd_cost_index * 0.1", 0.5) == "rd_cost_index * 0.1"


def test_validation_reports_driver_configuration_problems():
    definition = load()
    assert validate_external_drivers(definition) == []

    broken = load()
    driver = broken.external_drivers[0]
    driver.active_variant = "missing_variant"
    driver.observable_by = ["company", "ghost_agent"]
    driver.pathways[0].target_variable = "not_a_world_variable"
    driver.pathways[1].minimum = 10
    driver.pathways[1].maximum = 1
    errors = validate_external_drivers(broken)
    assert any("unknown variant 'missing_variant'" in item for item in errors)
    assert any("ghost_agent" in item for item in errors)
    assert any("not_a_world_variable" in item for item in errors)
    assert any("maximum below its minimum" in item for item in errors)

    with pytest.raises(ValueError, match="External driver configuration is invalid"):
        compile_external_drivers(broken)


def test_indicator_collision_with_existing_variable_is_rejected():
    definition = load()
    definition.external_drivers[0].indicator_variable = "rd_cost_index"
    errors = validate_external_drivers(definition)
    assert any("collides with an existing world variable" in item for item in errors)


def test_unknown_interaction_reference_is_rejected():
    definition = load()
    definition.external_drivers[0].interacts_with = ["tariff_shock"]
    errors = validate_external_drivers(definition)
    assert any("unknown driver 'tariff_shock'" in item for item in errors)
