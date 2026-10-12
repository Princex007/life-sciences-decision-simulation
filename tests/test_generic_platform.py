"""Contract tests for the data-defined simulation platform."""
from app.domain.definitions import SimulationDefinition
from app.domain.scenario import ScenarioNode
from app.forecasting.registry import ForecastRegistry
from app.run_simulation import run
from app.simulation.engine import SimulationEngine
from app.simulation.scenario_pruning import create_pruner
from app.simulation.decision_validator import DecisionValidationError, DecisionValidator
from app.domain.action import ActionDefinition
from app.domain.agent import AgentDefinition
from app.domain.world import WorldState

def tiny_definition():
    return SimulationDefinition.model_validate({
        "metadata": {"id":"generic-test","name":"Generic Test"},
        "initial_world_state": {"variables":{"count":0,"status":"new"}},
        "agents": [{"id":"worker","name":"Worker","objective":"change count",
            "available_actions":["increment"],"decision_policy":{"default_actions":["increment"]}},
            {"id":"reviewer","name":"Reviewer","objective":"review completion",
             "available_actions":["approve"],"decision_policy":{"default_actions":["approve"]}}],
        "action_definitions": [
            {"id":"increment","name":"Increment","agent_id":"worker","effects":[
                {"variable":"count","operation":"add","value":1}],"generated_events":[{"event_type":"changed"}]},
            {"id":"approve","name":"Approve","agent_id":"reviewer","effects":[
                {"variable":"status","operation":"set","value":"approved"}]}
        ],
        "trigger_definitions": [
            {"id":"start-worker","event_types":["simulation_start"],"affected_agents":["worker"],"priority":5},
            {"id":"changed-review","event_types":["changed"],"affected_agents":["reviewer"],"priority":4}],
        "settings":{"time_horizon":1,"initial_events":[{"id":"start","time":0,"event_type":"simulation_start"}]},
        "scenario_generation":{"policy":"exhaustive","max_scenarios":None}})

def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)

def test_json_definition_generic_agents_scheduler_transitions_and_lineage():
    definition = tiny_definition()
    result = SimulationEngine().run(definition)
    assert len(result.scenarios) == 1
    terminal = result.scenarios[0]
    assert terminal.final_state.get("count") == 1
    assert terminal.final_state.get("status") == "approved"
    nodes = {node.node_id: node for node in walk(result.root)}
    assert terminal.terminal_node_id in nodes
    assert all(node.parent_node_id is None or node.parent_node_id in nodes for node in nodes.values())
    assert any(trace.event_type == "decision" and trace.agent_id == "reviewer" for trace in terminal.decision_trace)
    assert len(terminal.agent_states) == 2
    assert next(a for a in terminal.agent_states if a.agent_id == "worker").current_strategy == "increment"

def test_pruning_policies_are_selectable():
    settings = SimulationDefinition.model_validate({"metadata":{"id":"x","name":"x"},
       "initial_world_state":{"variables":{}},"agents":[],"scenario_generation":{"policy":"top_n","max_scenarios":2}}).scenario_generation
    assert create_pruner(settings).__class__.__name__ == "LimitedPolicy"
    settings.policy = "exhaustive"
    assert create_pruner(settings).__class__.__name__ == "ExhaustivePolicy"

def test_json_launch_example_reproducible_and_forecast_is_plugin():
    definition, first = run("examples/us_drug_launch.json")
    _, second = run("examples/us_drug_launch.json")
    assert definition.metadata.domain == "life_sciences"
    assert first.model_dump() == second.model_dump()
    assert len(first.scenarios) == 9
    assert all(s.forecast is not None for s in first.scenarios)
    class FixedForecast:
        def forecast(self, final_state, snapshots, scenario):
            from app.domain.outcome import Outcome
            return Outcome(metrics={"custom": 42})
    registry = ForecastRegistry()
    registry.register("custom", FixedForecast())
    generic = tiny_definition()
    generic.forecast_model_id = "custom"
    outcome = SimulationEngine(registry).run(generic).scenarios[0].forecast
    assert outcome.metrics == {"custom": 42}

def test_terminal_path_ids_and_parent_links_are_unique():
    _, result = run("examples/us_drug_launch.json")
    nodes = list(walk(result.root))
    assert len({node.node_id for node in nodes}) == len(nodes)
    node_ids = {node.node_id for node in nodes}
    assert all(s.terminal_node_id in node_ids for s in result.scenarios)
    assert all(node.parent_node_id is None or node.parent_node_id in node_ids for node in nodes)

def test_agent_memory_persists_without_redeciding_each_step():
    definition = tiny_definition()
    result = SimulationEngine().run(definition)
    worker = next(a for a in result.scenarios[0].agent_states if a.agent_id == "worker")
    decisions = [t for t in result.scenarios[0].decision_trace if t.event_type == "decision" and t.agent_id == "worker"]
    assert len(decisions) == 1
    assert worker.current_strategy == "increment"
    assert worker.last_decision_time == 0
    assert worker.memory[0]["trigger"] == "start-worker"

def test_scheduler_advances_time_and_records_transition_node():
    result = SimulationEngine().run(tiny_definition())
    terminal = result.scenarios[0]
    assert terminal.final_state.time == 1
    assert any(trace.event_type == "transition" and trace.event.event_type == "time_step"
               for trace in terminal.decision_trace)
    assert len(terminal.snapshots) == 1

def test_scenario_terminal_path_can_be_reconstructed_from_tree():
    result = SimulationEngine().run(tiny_definition())
    terminal = result.scenarios[0]
    node = next(node for node in walk(result.root) if node.node_id == terminal.terminal_node_id)
    lineage = []
    by_id = {item.node_id: item for item in walk(result.root)}
    while node.parent_node_id is not None:
        lineage.append(node.node_id)
        node = by_id[node.parent_node_id]
    assert node.node_id == result.root.node_id
    assert lineage

def test_default_rule_policy_uses_arbitrary_agent_action_ids():
    definition = tiny_definition()
    result = SimulationEngine().run(definition)
    assert {action.action_id for action in result.scenarios[0].actions} == {"increment", "approve"}

def test_same_strategy_is_not_reapplied_at_later_trigger():
    definition = SimulationDefinition.model_validate({
        "metadata":{"id":"persistent","name":"Persistent"},
        "initial_world_state":{"variables":{"count":0}},
        "agents":[{"id":"a","name":"A","objective":"increment","available_actions":["once"],"decision_policy":{"default_actions":["once"]}}],
        "action_definitions":[{"id":"once","name":"Once","agent_id":"a","effects":[{"variable":"count","operation":"add","value":1}]}],
        "trigger_definitions":[{"id":"start","event_types":["simulation_start","review"],"affected_agents":["a"]}],
        "settings":{"time_horizon":2,"initial_events":[{"id":"start","time":0,"event_type":"simulation_start"}],"scheduled_events":[{"id":"review","time":2,"event_type":"review"}]}})
    terminal = SimulationEngine().run(definition).scenarios[0]
    assert terminal.final_state.get("count") == 1
    assert len([trace for trace in terminal.decision_trace if trace.event_type == "decision" and trace.agent_id == "a"]) == 2

def test_payer_review_policy_prevents_unjustified_downgrade():
    _, result = run("examples/us_drug_launch.json")
    for scenario in result.scenarios:
        initial_payer = next(t.action.action_id for t in scenario.decision_trace
            if t.event_type == "decision" and t.agent_id == "payer" and t.time == 0)
        later_payer = [t.action.action_id for t in scenario.decision_trace
            if t.event_type == "decision" and t.agent_id == "payer" and t.time > 0]
        if initial_payer in {"standard_access", "favorable_access"}:
            assert "restricted_access" not in later_payer

def test_decision_validator_rejects_invalid_action_before_mutation():
    agent = AgentDefinition(id="a", name="A", objective="keep price in range", available_actions=["cut"])
    action = ActionDefinition(id="cut", name="Cut", agent_id="a", effects=[
        {"variable":"price","operation":"multiply","value":0.5}],
        constraints={"state":{"price":{"min":60}}})
    world = WorldState(variables={"price":100})
    from app.domain.definitions import TriggerDefinition
    from app.simulation.scheduler import TriggerMatch
    from app.domain.event import SimulationEvent
    trigger = TriggerMatch(TriggerDefinition(id="t", event_types=["start"], affected_agents=["a"]),
        SimulationEvent(event_id="e",time=0,event_type="start",description="start"))
    try:
        DecisionValidator().validate(agent, action, world, trigger, 0)
        assert False, "constraint should reject a projected price below the configured minimum"
    except DecisionValidationError as error:
        assert "price" in str(error) and "60" in str(error)
    assert world.get("price") == 100

def test_pruned_nodes_are_explicit_and_never_forecast_terminals():
    _, result = run("examples/us_drug_launch.json")
    nodes = {node.node_id: node for node in walk(result.root)}
    assert result.pruning_records
    assert len(result.pruning_records) == sum(node.status == "pruned" for node in nodes.values())
    assert all(record.policy == "diversity" and record.reason for record in result.pruning_records)
    terminal_ids = {scenario.terminal_node_id for scenario in result.scenarios}
    assert all(nodes[node_id].status == "terminal" for node_id in terminal_ids)
    assert not terminal_ids.intersection(node.node_id for node in nodes.values() if node.status == "pruned")
    assert all(node.status in {"terminal", "pruned"} for node in nodes.values() if not node.children)

def test_every_terminal_has_event_decision_transition_lineage_and_audit_context():
    _, result = run("examples/us_drug_launch.json")
    all_nodes = {node.node_id: node for node in walk(result.root)}
    for scenario in result.scenarios:
        node = all_nodes[scenario.terminal_node_id]
        lineage = []
        while node.parent_node_id is not None:
            lineage.append(node)
            node = all_nodes[node.parent_node_id]
        lineage.reverse()
        kinds = [node.node_type for node in lineage]
        assert kinds[0] == "event"
        assert "decision" in kinds and "transition" in kinds
        assert all(node.status != "pruned" for node in lineage)
        decisions = [trace for trace in scenario.decision_trace if trace.event_type == "decision"]
        assert decisions and all(trace.observations and trace.plausible_actions and
            trace.alternative_reason and trace.validity_reason for trace in decisions)

def test_pruning_reduces_paths_only_after_distinct_valid_actions_were_applied():
    definition = tiny_definition()
    worker = definition.agents[0]
    worker.available_actions.append("increment_again")
    worker.decision_policy["default_actions"].append("increment_again")
    definition.action_definitions.append(ActionDefinition(id="increment_again",name="Increment again",agent_id="worker",
        effects=[{"variable":"count","operation":"add","value":2}],
        generated_events=[{"event_type":"changed"}]))
    definition.scenario_generation.policy = "limited"
    definition.scenario_generation.max_scenarios = 1
    limited = SimulationEngine().run(definition)
    assert len(limited.scenarios) == 1
    assert limited.pruning_records
    assert all(record.reason and record.policy == "limited" for record in limited.pruning_records)
    assert limited.scenarios[0].actions[0].action_id in {"increment", "increment_again"}
    definition.scenario_generation.policy = "exhaustive"
    definition.scenario_generation.safety_limit = 100
    exhaustive = SimulationEngine().run(definition)
    assert limited.scenarios[0].actions[0].action_id == exhaustive.scenarios[0].actions[0].action_id
    assert limited.scenarios[0].final_state.get("count") == exhaustive.scenarios[0].final_state.get("count")

def test_exhaustive_policy_honors_safety_limit_and_diversity_is_deterministic():
    definition = tiny_definition()
    definition.agents[0].available_actions.append("increment_again")
    definition.agents[0].decision_policy["default_actions"].append("increment_again")
    definition.action_definitions.append(ActionDefinition(id="increment_again",name="Increment again",agent_id="worker",
        effects=[{"variable":"count","operation":"add","value":2}]))
    definition.scenario_generation.policy = "exhaustive"
    definition.scenario_generation.safety_limit = 1
    capped = SimulationEngine().run(definition)
    assert len(capped.scenarios) == 1 and capped.pruning_records
    _, first = run("examples/us_drug_launch.json")
    _, second = run("examples/us_drug_launch.json")
    assert first.model_dump() == second.model_dump()
    signatures = set()
    for scenario in first.scenarios:
        signature = tuple(next(trace.action.action_id for trace in scenario.decision_trace
            if trace.event_type == "decision" and trace.agent_id == actor and trace.time == 0)
            for actor in ("competitor", "payer"))
        signatures.add(signature)
    assert len(signatures) == len(first.scenarios)

def test_old_new_forecast_regression_has_causal_state_delta():
    # Previously validated reference result retained from the pre-generic demo.
    old = {
        "restricted_slow": {"peak_sales":335835000,"cumulative_sales":1526430000,
            "market_share":0.015790995,"patients_treated":3951},
        "standard_strong": {"peak_sales":2662965000,"cumulative_sales":13942040000,
            "market_share":0.1252,"patients_treated":31329},
        "favorable_strong": {"peak_sales":3121455000,"cumulative_sales":17515015000,
            "market_share":0.1467,"patients_treated":36723}}
    _, result = run("examples/us_drug_launch.json")
    representative = []
    for initial_access, initial_action in ((0.55,"restricted_access"),(.75,"standard_access"),(.9,"favorable_access")):
        scenario = next(s for s in result.scenarios if any(t.event_type == "decision" and
            t.agent_id == "payer" and t.time == 0 and t.action.action_id == initial_action
            for t in s.decision_trace))
        representative.append((scenario, initial_access))
    for scenario, expected_access in representative:
        assert scenario.final_state.get("payer_access") == expected_access
        key = "restricted_slow" if expected_access == .55 else "standard_strong" if expected_access == .75 else "favorable_strong"
        prior = old[key]
        assert scenario.forecast.metrics["market_share"] != prior["market_share"]
        assert scenario.forecast.metrics["cumulative_sales"] != prior["cumulative_sales"]
        payer_decisions = [trace for trace in scenario.decision_trace if trace.event_type == "decision" and trace.agent_id == "payer"]
        assert [trace.time for trace in payer_decisions] == [0, 4, 8]
        assert [trace.observations["payer_access"] for trace in payer_decisions] == [0.75, expected_access, expected_access]
        assert any(trace.event_type == "transition" and "market_share" in trace.state_changes
                   for trace in scenario.decision_trace)
