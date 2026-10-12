import pytest

from app.agents.base import RuleBasedDecisionPolicy
from app.agents.cognition import (AgentObservation, DecisionContext, DecisionResponse,
                                  ObservationModel, ObservedEvent, build_decision_context)
from app.domain.action import ActionDefinition
from app.domain.agent import AgentDefinition, AgentState, Belief
from app.domain.definitions import SimulationDefinition
from app.domain.event import SimulationEvent
from app.domain.world import WorldState
from app.simulation.decision_validator import DecisionValidationError, DecisionValidator
from app.simulation.engine import SimulationEngine
from app.simulation.scheduler import TriggerMatch


def branching_definition():
    return SimulationDefinition.model_validate({
        "metadata": {"id": "cognitive", "name": "Cognitive Test"},
        "initial_world_state": {"variables": {"count": 0, "secret": "classified"}},
        "agents": [{"id": "worker", "name": "Worker", "objective": "change count",
            "secondary_objectives": ["record outcome"], "observable_state": ["count"],
            "available_actions": ["increment", "double"],
            "decision_policy": {"default_actions": ["increment", "double"]}}],
        "action_definitions": [
            {"id": "increment", "name": "Increment", "agent_id": "worker",
             "strategy": "steady_growth", "effects": [{"variable": "count", "operation": "add", "value": 1}]},
            {"id": "double", "name": "Double", "agent_id": "worker",
             "strategy": "rapid_growth", "effects": [{"variable": "count", "operation": "add", "value": 2}]},
        ],
        "trigger_definitions": [{"id": "start-worker", "event_types": ["simulation_start"],
                                 "affected_agents": ["worker"]}],
        "settings": {"time_horizon": 1,
            "initial_events": [{"id": "start", "time": 0, "event_type": "simulation_start",
                                 "description": "Simulation begins"}]},
        "scenario_generation": {"policy": "exhaustive", "max_scenarios": None}})


def test_observation_model_filters_world_variables_events_and_state_changes():
    agent = AgentDefinition(id="payer", name="Payer", objective="manage cost",
                            observable_state=["payer_access"])
    world = WorldState(time=3, variables={"payer_access": .75, "competitor_internal_strategy": "price_cut"})
    event = SimulationEvent(event_id="e1", time=3, event_type="review", description="Review",
        data={"payer_access": .75, "competitor_internal_strategy": "price_cut", "trigger_id": "review"})
    observation = ObservationModel().observe(agent, world, [event],
        {"payer_access": .55, "competitor_internal_strategy": "price_cut"})
    assert observation.visible_world_variables == {"payer_access": .75}
    assert observation.relevant_state_changes == {"payer_access": .55}
    assert observation.relevant_events[0].data == {"payer_access": .75, "trigger_id": "review"}
    assert "competitor_internal_strategy" not in observation.model_dump_json()
    object_world = WorldState(variables={"settings": {"choices": [1, 2]}})
    object_agent = AgentDefinition(id="x", name="X", objective="x", observable_state=["settings"])
    object_observation = ObservationModel().observe(object_agent, object_world)
    object_observation.visible_world_variables["settings"]["choices"].append(3)
    assert object_world.get("settings") == {"choices": [1, 2]}


def test_context_only_contains_relevant_observations_beliefs_and_memory():
    agent = AgentDefinition(id="worker", name="Worker", objective="grow",
                            observable_state=["count"], available_actions=["increment"])
    state = AgentState(agent_id="worker")
    state.belief_state.beliefs.extend([
        Belief(id="b1", proposition="count is 1", basis="observed", timestamp=1,
               related_variables=["count"]),
        Belief(id="b2", proposition="secret is known", basis="leak", timestamp=1,
               related_variables=["secret"])])
    state.memory.observations.append({"count": 1, "secret": "classified"})
    state.memory.previous_decisions.append({"observations": {"count": 1, "secret": "classified"}})
    obs = AgentObservation(timestamp=1, visible_world_variables={"count": 1})
    context = build_decision_context(agent, state, obs,
        ObservedEvent(event_id="e", time=1, event_type="go", description="Go"),
        [ActionDefinition(id="increment", name="Increment", agent_id="worker")])
    assert [belief.id for belief in context.relevant_beliefs] == ["b1"]
    assert context.relevant_memory["observations"] == [{"count": 1}]
    assert context.relevant_memory["previous_decisions"][0]["observations"] == {"count": 1}


def test_memory_persists_decisions_observations_events_and_strategy_changes():
    result = SimulationEngine().run(branching_definition())
    state = result.scenarios[0].agent_states[0]
    assert state.memory.previous_actions == ["increment"]
    assert state.memory.decision_times == [0]
    assert state.memory.observations == [{"count": 0}]
    assert state.memory.important_events[0]["event_type"] == "simulation_start"
    assert state.memory.strategy_changes == [{"time": 0, "from": None,
        "to": "steady_growth", "action_id": "increment"}]


def test_scenario_branches_have_independent_mutable_memory():
    result = SimulationEngine().run(branching_definition())
    assert len(result.scenarios) == 2
    first, second = [scenario.agent_states[0] for scenario in result.scenarios]
    assert first.memory is not second.memory
    first.memory.important_events.append({"event_type": "branch_only"})
    assert all(event.get("event_type") != "branch_only" for event in second.memory.important_events)
    first.belief_state.beliefs.append(Belief(id="branch", proposition="branch-only",
        basis="test", timestamp=1))
    assert all(belief.id != "branch" for belief in second.belief_state.beliefs)
    assert first.current_strategy != second.current_strategy


def test_objective_strategy_and_action_are_distinct_and_strategy_changes_explicitly():
    definition = branching_definition()
    result = SimulationEngine().run(definition)
    scenario = next(item for item in result.scenarios if item.actions[0].action_id == "increment")
    trace = next(item for item in scenario.decision_trace if item.event_type == "decision")
    state = scenario.agent_states[0]
    assert trace.objective == "change count"
    assert trace.action.name == "Increment"
    assert state.current_strategy == "steady_growth"
    assert state.current_strategy != trace.action.name


def test_policy_receives_no_world_state_and_cannot_mutate_simulation_state():
    class MutatingObservationPolicy(RuleBasedDecisionPolicy):
        def get_plausible_actions(self, context):
            assert not hasattr(context, "world_state")
            assert "secret" not in context.observations.visible_world_variables
            context.observations.visible_world_variables["count"] = 900
            proposed = super().get_plausible_actions(context)
            proposed[0].effects[0].value = 900
            return proposed

    result = SimulationEngine(decision_policy=MutatingObservationPolicy()).run(branching_definition())
    assert {item.final_state.get("count") for item in result.scenarios} == {1, 2}
    assert all("secret" not in trace.observations for scenario in result.scenarios
               for trace in scenario.decision_trace if trace.event_type == "decision")


def test_invalid_policy_action_is_rejected_and_traced_without_transition():
    class InvalidPolicy(RuleBasedDecisionPolicy):
        def decide(self, context, actions):
            return DecisionResponse(primary_action="invented-action", rationale="Not configured")

    result = SimulationEngine(decision_policy=InvalidPolicy()).run(branching_definition())
    assert len(result.scenarios) == 1
    assert result.scenarios[0].final_state.get("count") == 0
    trace = next(item for item in result.scenarios[0].decision_trace if item.event_type == "decision")
    assert trace.action is None
    assert trace.validation_status == "invalid"
    assert "not in the plausible candidate set" in trace.validity_reason


def test_policy_cannot_select_configured_but_infeasible_action():
    definition = branching_definition()
    double = next(action for action in definition.action_definitions if action.id == "double")
    double.effects[0].operation = "set"
    double.effects[0].value = -1
    double.constraints = {"next_state": [{"variable": "count", "operator": "gte", "value": 0}]}

    class InfeasibleActionPolicy(RuleBasedDecisionPolicy):
        received_action_ids = None

        def decide(self, context, actions):
            self.received_action_ids = [action.id for action in actions]
            return DecisionResponse(primary_action="double", rationale="Deliberately invalid choice")

    policy = InfeasibleActionPolicy()
    result = SimulationEngine(decision_policy=policy).run(definition)
    scenario = result.scenarios[0]
    trace = next(item for item in scenario.decision_trace
                 if item.event_type == "decision" and item.agent_id == "worker")

    assert policy.received_action_ids == ["increment"]
    assert scenario.final_state.get("count") == 0
    assert trace.action is None
    assert trace.validation_status == "invalid"
    assert "not in the plausible candidate set" in trace.validity_reason
    assert not any(item.event_type == "transition" and item.agent_id == "worker"
                   for item in scenario.decision_trace)


def test_selected_action_is_revalidated_after_policy_selection(monkeypatch):
    definition = branching_definition()
    validation_state = {"policy_returned": False, "calls_after_policy": []}
    original_validate = DecisionValidator.validate

    def track_validation(self, agent, action, world, trigger, time):
        if validation_state["policy_returned"]:
            validation_state["calls_after_policy"].append(action.id)
        return original_validate(self, agent, action, world, trigger, time)

    monkeypatch.setattr(DecisionValidator, "validate", track_validation)

    class SelectingPolicy(RuleBasedDecisionPolicy):
        def decide(self, context, actions):
            validation_state["policy_returned"] = True
            return DecisionResponse(primary_action="increment")

    result = SimulationEngine(decision_policy=SelectingPolicy()).run(definition)
    assert result.scenarios[0].actions[0].action_id == "increment"
    # The engine checks the selected action, then the scenario generator checks it again before applying it.
    assert validation_state["calls_after_policy"] == ["increment", "increment"]


def test_no_feasible_actions_records_failure_without_calling_policy():
    definition = branching_definition()
    increment = next(action for action in definition.action_definitions if action.id == "increment")
    increment.constraints = {"next_state": [{"variable": "count", "operator": "gte", "value": 100}]}
    double = next(action for action in definition.action_definitions if action.id == "double")
    double.effects[0].operation = "set"
    double.effects[0].value = -1
    double.constraints = {"next_state": [{"variable": "count", "operator": "gte", "value": 0}]}

    class MustNotDecidePolicy(RuleBasedDecisionPolicy):
        decide_calls = 0

        def decide(self, context, actions):
            self.decide_calls += 1
            raise AssertionError("policy must not be called without feasible actions")

    policy = MustNotDecidePolicy()
    result = SimulationEngine(decision_policy=policy).run(definition)
    scenario = result.scenarios[0]
    trace = next(item for item in scenario.decision_trace
                 if item.event_type == "decision" and item.agent_id == "worker")

    assert policy.decide_calls == 0
    assert scenario.final_state.get("count") == 0
    assert trace.action is None
    assert trace.validation_status == "invalid"
    assert "No feasible actions remain" in trace.validity_reason
    assert not any(item.event_type == "transition" and item.agent_id == "worker"
                   for item in scenario.decision_trace)


def test_validator_rejects_invalid_action_and_missing_required_parameter():
    definition = branching_definition()
    agent = definition.agents[0]
    action = definition.action_definitions[0]
    event = SimulationEvent(event_id="start", time=0, event_type="simulation_start", description="Start")
    match = TriggerMatch(definition=definition.trigger_definitions[0], event=event)
    with pytest.raises(DecisionValidationError, match="not available"):
        DecisionValidator().validate(agent, ActionDefinition(id="unknown", name="Unknown", agent_id="worker"),
                                     definition.initial_world_state, match, 0)
    parameterized = action.model_copy(deep=True)
    parameterized.constraints["required_parameters"] = ["mode"]
    with pytest.raises(DecisionValidationError, match="missing required parameter 'mode'"):
        DecisionValidator().validate(agent, parameterized, definition.initial_world_state, match, 0)


def test_rule_policy_is_deterministic_and_trace_contains_response_context():
    definition = branching_definition()
    policy = RuleBasedDecisionPolicy()
    result_a = SimulationEngine(decision_policy=policy).run(definition)
    result_b = SimulationEngine(decision_policy=policy).run(definition)
    assert result_a.model_dump() == result_b.model_dump()
    trace = next(item for item in result_a.scenarios[0].decision_trace if item.event_type == "decision")
    assert trace.agent_id == "worker"
    assert trace.trigger == "Simulation begins"
    assert trace.observations == {"count": 0}
    assert trace.objective == "change count"
    assert {action.action_id for action in trace.plausible_actions} == {"increment", "double"}
    assert trace.action.action_id == "increment"
    assert trace.decision_response.primary_action == "increment"
    assert trace.decision_response.alternative_actions == ["double"]
    assert trace.decision_response.validation_status == "valid"
    assert trace.validation_status == "valid"
    assert trace.decision_response.strategy_change == "steady_growth"
