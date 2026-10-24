from pathlib import Path

from app.agents.base import RuleBasedDecisionPolicy
from app.agents.cognition import DecisionResponse
from app.domain.definitions import SimulationDefinition
from app.evaluation.objective_scorer import ObjectiveScorer
from app.forecasting.launch_forecast import LaunchForecast
from app.forecasting.registry import ForecastRegistry
from app.simulation.decision_validator import DecisionValidator
from app.simulation.engine import SimulationEngine
from app.simulation.state_transition import evaluate_value


class DeterministicFallbackPolicy(RuleBasedDecisionPolicy):
    """Use the scenario's configured plausible-action rules; never call an LLM."""
    def __init__(self):
        self.policy_decisions = []
        self.contexts = []

    def get_plausible_actions(self, context):
        self.contexts.append(context.model_copy(deep=True))
        return super().get_plausible_actions(context)

    def decide(self, context, actions):
        ids = {action.id for action in actions}
        self.policy_decisions.append((context.agent_id, set(ids)))
        return DecisionResponse(primary_action=actions[0].id,
            rationale="Deterministic test fallback selected the first feasible configured candidate.")


def test_actual_example_runs_auditable_five_agent_decision_path(monkeypatch):
    definition = SimulationDefinition.from_json(
        str(Path(__file__).parents[1] / "examples" / "us_drug_launch.json"))
    definition.settings.time_horizon = 1
    definition.settings.scheduled_events = []
    definition.scenario_generation.max_scenarios = 1

    expected_order = ["company", "competitor", "payer", "physician", "patient"]
    configured_agents = {agent.id: agent for agent in definition.agents}
    assert list(agent.id for agent in definition.agents) == expected_order
    action_map = {action.id: action for action in definition.action_definitions}
    policy = DeterministicFallbackPolicy()
    feasible_by_agent = {}
    preview_by_agent = {}
    scorer_calls = []

    original_filter = DecisionValidator.filter_feasible_actions
    def track_feasible(self, agent, actions, world, trigger, time):
        feasible = original_filter(self, agent, actions, world, trigger, time)
        feasible_by_agent.setdefault(agent.id, []).append({item.id for item in feasible})
        return feasible
    monkeypatch.setattr(DecisionValidator, "filter_feasible_actions", track_feasible)

    original_previews = SimulationEngine._build_action_previews
    def track_previews(world, agent, actions, scenario, transition, time, forecast_model=None,
                       forecast_context=None):
        before = world.model_dump(mode="python")
        result = original_previews(world, agent, actions, scenario, transition, time, forecast_model,
                                   forecast_context)
        assert world.model_dump(mode="python") == before
        candidate_ids = {action.id for action in actions}
        assert set(result) == candidate_ids
        assert candidate_ids.issubset(feasible_by_agent[agent.id][-1])
        preview_by_agent[agent.id] = result
        return result
    monkeypatch.setattr(SimulationEngine, "_build_action_previews", staticmethod(track_previews))

    original_score = ObjectiveScorer.score_actions
    def track_score(self, previews, state, objective):
        scorer_calls.append(set(previews))
        assert previews
        return original_score(self, previews, state, objective)
    monkeypatch.setattr(ObjectiveScorer, "score_actions", track_score)

    registry = ForecastRegistry()
    registry.register("launch_revenue", LaunchForecast())
    result = SimulationEngine(registry, decision_policy=policy).run(definition)

    assert len(result.scenarios) == 1
    trace = result.scenarios[0].decision_trace
    decisions = [item for item in trace if item.event_type == "decision" and item.action]
    assert [item.agent_id for item in decisions] == expected_order
    assert set(preview_by_agent) == set(expected_order)
    assert all(agent_id in feasible_by_agent for agent_id in expected_order)
    scored_agents = {action_map[action_id].agent_id for call in scorer_calls for action_id in call}
    assert scored_agents == set(expected_order)

    decision_indices = {item.agent_id: trace.index(item) for item in decisions}
    assert [decision_indices[item] for item in expected_order] == sorted(
        decision_indices[item] for item in expected_order)

    for decision in decisions:
        agent = configured_agents[decision.agent_id]
        context = decision.decision_context
        visible = context.observations.visible_world_variables
        if agent.observable_state != "all":
            assert set(visible).issubset(set(agent.observable_state))
        assert all(decision.previous_world_state.get(name) == value
                   for name, value in visible.items())
        assert decision.decision_response.validation_status == "valid"
        assert decision.action.action_id in feasible_by_agent[decision.agent_id][-1]

        scores = context.objective_scores
        if scores:
            assert set(scores) == set(context.action_previews)
            if decision.decision_source == "objective_scorer":
                highest = max(scores, key=lambda action_id: scores[action_id]["score"])
                assert decision.action.action_id == highest
        if decision.decision_source == "existing_policy_fallback":
            assert (decision.agent_id, set(context.action_previews)) in policy.policy_decisions
            assert set(context.action_previews).issubset(feasible_by_agent[decision.agent_id][-1])

        selected_action = action_map[decision.action.action_id]
        configured_effects = {effect.variable for effect in selected_action.effects}
        applied = next(item for item in trace
            if item.event_type == "transition" and item.event is not None
            and item.event.event_type == "action_transition"
            and item.event.actor_id == decision.agent_id)
        assert set(applied.state_changes).issubset(configured_effects)
        assert "market_share" not in configured_effects
        assert decision.validity_reason

    # Verify action previews expose configured consequences for each stakeholder.
    assert preview_by_agent["company"]["launch_discounted"]["after_action_changes"]["drug_price"]["to"] == 60000
    assert "market_share" not in preview_by_agent["company"]["launch"]["after_action_changes"]
    competitor_previews = preview_by_agent["competitor"]
    assert competitor_previews["aggressive_price_cut"]["after_action_changes"]["competitor_price"]["to"] == 72000
    assert competitor_previews["increase_promotion"]["after_action_changes"]["competitor_promotion"]["to"] == 1.25
    assert "competitor_promotion_spend" in competitor_previews["increase_promotion"]["after_action_changes"]
    payer_access_targets = {"restricted_access": 0.55, "standard_access": 0.75,
                            "favorable_access": 0.9}
    for action_id, preview in preview_by_agent["payer"].items():
        access_change = preview["after_action_changes"].get("payer_access")
        if payer_access_targets[action_id] == definition.initial_world_state.get("payer_access"):
            assert access_change is None
        else:
            assert access_change["to"] == payer_access_targets[action_id]
    assert all("physician_adoption" in preview["after_action_changes"]
               for preview in preview_by_agent["physician"].values())
    assert all("patient_adherence_rate" in preview["after_action_changes"]
               for preview in preview_by_agent["patient"].values())
    assert all(preview["clinical_outcomes"]["available"]
               and preview["patient_affordability"]["available"]
               for preview in preview_by_agent["patient"].values())
    assert "market_share" not in preview_by_agent["patient"]["high_adherence"]["after_action_changes"]
    assert preview_by_agent["patient"]["high_adherence"]["forecast_metrics"]["market_share"] != \
        preview_by_agent["patient"]["moderate_adherence"]["forecast_metrics"]["market_share"]

    company_transition = next(item for item in trace if item.event is not None
        and item.event.event_type == "action_transition" and item.event.actor_id == "company")
    company_price = company_transition.resulting_world_state.get("drug_price")
    competitor_decision = next(item for item in decisions if item.agent_id == "competitor")
    assert competitor_decision.observations["drug_price"] == company_price
    payer_decision = next(item for item in decisions if item.agent_id == "payer")
    competitor_transition = next(item for item in trace if item.event is not None
        and item.event.event_type == "action_transition" and item.event.actor_id == "competitor")
    assert payer_decision.observations["competitor_price"] == \
        competitor_transition.resulting_world_state.get("competitor_price")
    physician_decision = next(item for item in decisions if item.agent_id == "physician")
    payer_transition = next(item for item in trace if item.event is not None
        and item.event.event_type == "action_transition" and item.event.actor_id == "payer")
    assert physician_decision.observations["payer_access"] == \
        payer_transition.resulting_world_state.get("payer_access")
    patient_decision = next(item for item in decisions if item.agent_id == "patient")
    physician_transition = next(item for item in trace if item.event is not None
        and item.event.event_type == "action_transition" and item.event.actor_id == "physician")
    assert patient_decision.observations["physician_adoption"] == \
        physician_transition.resulting_world_state.get("physician_adoption")

    time_step = next(item for item in trace if item.event is not None
                     and item.event.event_type == "time_step")
    assert "market_share" in time_step.state_changes
    assert "patient_adherence_rate" in time_step.resulting_world_state.variables
    market_share_rule = next(rule for rule in definition.transition_rules
        if "time_step" in [part.strip() for part in rule.event_type.split(",")]
        and any(effect.variable == "market_share" for effect in rule.effects))
    market_share_effect = next(effect for effect in market_share_rule.effects
                               if effect.variable == "market_share")
    expected_delta = evaluate_value(market_share_effect.value, time_step.previous_world_state)
    expected_share = min(market_share_effect.maximum or 1, max(
        market_share_effect.minimum or 0,
        time_step.previous_world_state.get("market_share") + expected_delta))
    assert time_step.resulting_world_state.get("market_share") == expected_share
    forecast = result.scenarios[0].forecast
    assert forecast is not None
    assert {"patients_treated", "peak_sales", "cumulative_sales", "market_share"}.issubset(
        forecast.metrics)
    assert all(item.validation_status == "valid" for item in decisions)
    print("DECISIONS:", [(item.agent_id, item.action.action_id, item.decision_source)
                          for item in decisions])
    print("DECISION_REASONS:", [(item.agent_id, item.decision_context.decision_reason,
                                item.decision_context.objective_scores)
                               for item in decisions])
    print("STATE_TRANSITIONS:", [(item.event.actor_id, item.state_changes)
          for item in trace if item.event is not None and item.event.event_type == "action_transition"])
    print("FINAL_WORLD_STATE:", result.scenarios[0].final_state.model_dump(mode="json"))
    print("FINAL_FORECAST:", forecast.metrics)
