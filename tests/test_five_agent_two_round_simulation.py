"""Tests for the 5-agent 2-round life-science decision simulation milestone with emergent market share."""
from pathlib import Path

from app.domain.definitions import SimulationDefinition
from app.services.simulation_runner import SimulationRunnerService


ROOT = Path(__file__).resolve().parents[1]
DEFINITION_PATH = ROOT / "examples" / "local_5agent_2round_smoke.json"
EXPECTED_AGENTS = ["company", "competitor", "payer", "physician", "patient"]


def test_no_agent_action_directly_modifies_market_share():
    """Verify that no action definition has market_share in its effects."""
    definition = SimulationDefinition.from_json(str(DEFINITION_PATH))
    for action in definition.action_definitions:
        for effect in action.effects:
            assert effect.variable != "market_share", (
                f"Action '{action.id}' directly modifies 'market_share', violating domain isolation."
            )


def test_five_agents_participate_and_ten_decisions_occur_validated():
    definition = SimulationDefinition.from_json(str(DEFINITION_PATH))
    result, _ = SimulationRunnerService().run(definition, "rule_based")

    assert len(result.scenarios) == 1
    scenario = result.scenarios[0]
    decisions = [t for t in scenario.decision_trace if t.event_type == "decision"]

    assert len(decisions) == 10
    round_1_agents = [d.agent_id for d in decisions[:5]]
    round_2_agents = [d.agent_id for d in decisions[5:]]

    assert round_1_agents == EXPECTED_AGENTS
    assert round_2_agents == EXPECTED_AGENTS

    for decision in decisions:
        assert decision.validation_status == "valid"
        assert decision.action is not None
        assert decision.action.action_id


def test_market_share_changes_when_upstream_variables_change_indirectly():
    """Verify market_share recalculates after physician and patient behavioral actions."""
    definition = SimulationDefinition.from_json(str(DEFINITION_PATH))
    result, _ = SimulationRunnerService().run(definition, "rule_based")
    scenario = result.scenarios[0]
    decisions = [t for t in scenario.decision_trace if t.event_type == "decision"]

    payer_r1 = decisions[2]
    physician_r1 = decisions[3]
    patient_r1 = decisions[4]

    # Physician's action changes physician_prescribing_rate
    phys_pos = scenario.decision_trace.index(physician_r1)
    phys_trans = next(t for t in scenario.decision_trace[phys_pos + 1:]
                      if t.event_type == "transition" and t.agent_id == "physician")
    assert "physician_prescribing_rate" in phys_trans.state_changes
    assert "market_share" not in phys_trans.state_changes

    # Downstream patient receives the recalculated market_share caused by physician's prescribing
    patient_obs = patient_r1.decision_context.observations.visible_world_variables
    phys_obs = physician_r1.decision_context.observations.visible_world_variables
    assert patient_obs["market_share"] > phys_obs["market_share"]

    # Patient's action changes patient_adherence_rate
    pat_pos = scenario.decision_trace.index(patient_r1)
    pat_trans = next(t for t in scenario.decision_trace[pat_pos + 1:]
                     if t.event_type == "transition" and t.agent_id == "patient")
    assert "patient_adherence_rate" in pat_trans.state_changes
    assert "market_share" not in pat_trans.state_changes


def test_round_two_receives_recalculated_market_share():
    """Verify that Round 2 starts from the accumulated Round 1 market_share without reset."""
    definition = SimulationDefinition.from_json(str(DEFINITION_PATH))
    result, _ = SimulationRunnerService().run(definition, "rule_based")
    scenario = result.scenarios[0]
    decisions = [t for t in scenario.decision_trace if t.event_type == "decision"]

    company_r1 = decisions[0]
    patient_r1 = decisions[4]
    company_r2 = decisions[5]

    r1_initial_ms = company_r1.decision_context.observations.visible_world_variables["market_share"]
    r2_company_ms = company_r2.decision_context.observations.visible_world_variables["market_share"]

    # Round 2 Company observes the market_share resulting from Round 1 patient adherence
    assert r2_company_ms > r1_initial_ms
    assert r2_company_ms == 0.0943


def test_information_isolation_and_forecast_computation():
    definition = SimulationDefinition.from_json(str(DEFINITION_PATH))
    agent_defs = {a.id: set(a.observable_state) for a in definition.agents}

    result, _ = SimulationRunnerService().run(definition, "rule_based")
    scenario = result.scenarios[0]
    decisions = [t for t in scenario.decision_trace if t.event_type == "decision"]

    for decision in decisions:
        observed_keys = set(decision.decision_context.observations.visible_world_variables.keys())
        allowed_keys = agent_defs[decision.agent_id]
        assert observed_keys.issubset(allowed_keys)

        if decision.agent_id == "physician":
            assert "competitor_promotion" not in observed_keys
            assert "patient_adherence_rate" not in observed_keys
        elif decision.agent_id == "patient":
            assert "competitor_price" not in observed_keys
            assert "competitor_promotion" not in observed_keys
            assert "company_launch_status" not in observed_keys

    assert scenario.forecast is not None
    assert scenario.forecast.metrics["peak_sales"] > 0
    assert scenario.forecast.metrics["cumulative_sales"] > 0
    assert scenario.forecast.metrics["market_share"] == scenario.final_state.get("market_share")
    assert scenario.forecast.metrics["patients_treated"] > 0
