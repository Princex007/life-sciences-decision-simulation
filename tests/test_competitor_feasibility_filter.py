import json
from pathlib import Path

from app.domain.agent import AgentState
from app.domain.definitions import SimulationDefinition
from app.domain.event import SimulationEvent
from app.domain.world import WorldState
from app.agents.cognition import AgentObservation, DecisionContext, ObservedEvent
from app.agents.llm import DecisionPromptBuilder
from app.simulation.decision_validator import DecisionValidator
from app.simulation.engine import SimulationEngine
from app.simulation.scheduler import EventScheduler
from app.simulation.state_transition import StateTransitionSystem


def test_competitor_candidates_are_filtered_by_configured_economic_constraints():
    definition = SimulationDefinition.from_json(
        str(Path(__file__).parents[1] / "examples" / "us_drug_launch.json"))
    agent = next(item for item in definition.agents if item.id == "competitor")
    actions = {item.id: item for item in definition.action_definitions
               if item.agent_id == agent.id}
    candidates = [actions["increase_promotion"], actions["aggressive_price_cut"]]
    event = SimulationEvent(event_id="launch", time=0, event_type="company_launch",
        description="Company launches product", actor_id="company")
    validator = DecisionValidator()

    def feasible_at(competitor_price, promotion_spend=0):
        variables = dict(definition.initial_world_state.variables)
        variables["drug_price"] = 100000
        variables["competitor_price"] = competitor_price
        variables["competitor_promotion_spend"] = promotion_spend
        world = WorldState(time=0, variables=variables)
        memory = AgentState(agent_id=agent.id, current_strategy=agent.initial_strategy)
        trigger = EventScheduler(definition).dispatch(agent, memory, world, [event], None, 0)
        assert trigger is not None
        return {action.id for action in validator.filter_feasible_actions(
            agent, candidates, world, trigger, 0)}

    assert feasible_at(110000) == {"increase_promotion", "aggressive_price_cut"}
    assert feasible_at(70000) == {"increase_promotion"}
    assert feasible_at(110000, promotion_spend=900000) == {"aggressive_price_cut"}


def test_action_previews_are_isolated_configured_and_attached_to_candidates():
    definition = SimulationDefinition.from_json(
        str(Path(__file__).parents[1] / "examples" / "us_drug_launch.json"))
    agent = next(item for item in definition.agents if item.id == "competitor")
    actions = {item.id: item for item in definition.action_definitions
               if item.agent_id == agent.id}
    candidates = [actions["increase_promotion"], actions["aggressive_price_cut"]]
    world = definition.initial_world_state.model_copy(deep=True)
    world.set("drug_price", 100000)
    world.set("competitor_price", 110000)
    original_world = world.model_copy(deep=True)
    event = SimulationEvent(event_id="launch", time=0, event_type="company_launch",
        description="Company launches product", actor_id="company")
    trigger_match = EventScheduler(definition).dispatch(agent,
        AgentState(agent_id=agent.id, current_strategy=agent.initial_strategy),
        world, [event], None, 0)
    assert trigger_match is not None

    validator = DecisionValidator()
    feasible = validator.filter_feasible_actions(agent, candidates, world, trigger_match, 0)
    previews = SimulationEngine._build_action_previews(
        world, agent, feasible, definition, StateTransitionSystem(), 0)

    assert world.model_dump() == original_world.model_dump()
    assert set(previews) == {"increase_promotion", "aggressive_price_cut"}
    price_preview = previews["aggressive_price_cut"]
    promotion_preview = previews["increase_promotion"]
    assert price_preview["after_action_changes"]["competitor_price"] == {
        "from": 110000, "to": 88000, "delta": -22000}
    assert price_preview["configured_derived_metrics"]["competitor_unit_contribution_after_action"] == 28000
    assert promotion_preview["after_action_changes"]["competitor_promotion"]["to"] == 1.25
    assert promotion_preview["after_action_changes"]["competitor_promotion_spend"]["delta"] == 250000
    assert promotion_preview["configured_derived_metrics"]["competitor_unit_contribution_after_action"] == 50000
    assert price_preview["after_next_time_step"]["market_share"] != \
        promotion_preview["after_next_time_step"]["market_share"]

    context = DecisionContext(agent_id=agent.id, agent_name=agent.name, agent_type=agent.type,
        time=0, trigger=ObservedEvent(event_id="launch", time=0, event_type="company_launch",
            description="Company launches product", actor_id="company"),
        objective=agent.objective,
        observations=AgentObservation(timestamp=0,
            visible_world_variables=world.as_variables()),
        available_actions=feasible, action_previews=previews)
    prompt = DecisionPromptBuilder().build_local_action_prompt(context, feasible)
    compact_context = prompt.user.split("\n\nPlausible candidate action IDs:", 1)[0]
    payload = json.loads(compact_context.split("Relevant DecisionContext:\n", 1)[1])
    assert [item["preview"] for item in payload["candidate_actions"]] == [
        previews["increase_promotion"], previews["aggressive_price_cut"]]

    # At an infeasible price, filtering happens before the preview builder is called.
    world.set("competitor_price", 70000)
    feasible_b = validator.filter_feasible_actions(agent, candidates, world, trigger_match, 0)
    previews_b = SimulationEngine._build_action_previews(
        world, agent, feasible_b, definition, StateTransitionSystem(), 0)
    assert set(previews_b) == {"increase_promotion"}
