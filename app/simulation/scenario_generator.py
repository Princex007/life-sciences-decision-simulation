"""Branch valid agent decisions and maintain auditable scenario lineage."""
from copy import deepcopy
from dataclasses import dataclass, field
from app.domain.action import Action, ActionDefinition
from app.domain.agent import AgentDefinition, AgentState
from app.agents.cognition import DecisionAudit, DecisionContext, DecisionResponse
from app.domain.event import SimulationEvent
from app.domain.scenario import PruningRecord, ScenarioNode, TraceEvent
from app.domain.world import WorldState
from app.simulation.scheduler import TriggerMatch
from app.simulation.state_transition import StateTransitionSystem, TransitionResult
from app.simulation.scenario_pruning import ScenarioPolicy
from app.simulation.decision_validator import DecisionValidator
from app.simulation.strategy_transition import StrategyTransitionSystem

@dataclass
class SimulationPath:
    world: WorldState
    agents: dict[str, AgentState]
    actions: list[Action]
    trace: list[TraceEvent]
    snapshots: list[WorldState]
    cursor: ScenarioNode
    decided_agents: set[str] = field(default_factory=set)

    def clone(self) -> "SimulationPath":
        child = SimulationPath(self.world.model_copy(deep=True), deepcopy(self.agents), list(self.actions),
                               list(self.trace), list(self.snapshots), self.cursor, set(self.decided_agents))
        if hasattr(self, "_previous_world"):
            child._previous_world = self._previous_world.model_copy(deep=True)
        if hasattr(self, "_pending_events"):
            child._pending_events = list(self._pending_events)
        return child

class ScenarioGenerator:
    """Fork already validated plausible actions; pruning only retains/removes paths."""
    def __init__(self, pruner: ScenarioPolicy):
        self.pruner = pruner
        self._node_sequence = 0
        self.pruning_records: list[PruningRecord] = []

    def root_path(self, world: WorldState, definitions: list[AgentDefinition]):
        root = ScenarioNode(node_id="root", node_type="root", time=world.time,
                            world_state=world.model_copy(deep=True))
        path = SimulationPath(world.model_copy(deep=True),
            {definition.id: AgentState(agent_id=definition.id,
                current_strategy=definition.initial_strategy) for definition in definitions},
            [], [], [], root)
        return path, root

    def branch(self, path: SimulationPath, agent: AgentDefinition, trigger: TriggerMatch,
               definitions: list[ActionDefinition], transition: StateTransitionSystem, time: int,
               context: DecisionContext, response: DecisionResponse,
               alternative_reason: str = "", audit: DecisionAudit | None = None
               ) -> list[tuple[SimulationPath, TransitionResult]]:
        outputs = []
        for definition in definitions:
            DecisionValidator().validate(agent, definition, path.world, trigger, time)
            branch_role = "selected" if definition.id == response.primary_action else "counterfactual"
            child = path.clone()
            memory = child.agents[agent.id]
            before = child.world.model_copy(deep=True)
            previous_strategy = memory.current_strategy
            action = Action(action_id=definition.id, agent_id=definition.agent_id, name=definition.name,
                category="decision", parameters=definition.parameters, description=definition.description)
            rationale = (f"Selected '{definition.name}' from the configured plausible set after trigger '{trigger.definition.id}'."
                         if branch_role == "selected" else
                         f"Counterfactual comparison branch: '{definition.name}' was feasible after trigger "
                         f"'{trigger.definition.id}' but was not the decision layer's selection.")
            target_strategy = definition.strategy if definition.strategy is not None else definition.id
            already_applied = (memory.current_strategy == target_strategy and memory.previous_actions
                               and memory.previous_actions[-1] == definition.id)
            if already_applied:
                result = TransitionResult(before, child.world.model_copy(deep=True), [])
            else:
                result = transition.apply_action(child.world, definition, time)
            strategy_transition = StrategyTransitionSystem().apply(
                memory, definition.strategy, definition.id, time)
            memory.belief_state.apply_updates(response.belief_updates)
            memory.remember(action, time, trigger.definition.id, rationale,
                            context.observations.visible_world_variables)
            memory.last_trigger_times[trigger.definition.id] = time
            child.actions.append(action)
            child.decided_agents.add(agent.id)
            plausible = [Action(action_id=item.id, agent_id=item.agent_id, name=item.name,
                category="decision", parameters=item.parameters, description=item.description) for item in definitions]
            decision_node = ScenarioNode(node_id=self._new_node_id(), node_type="decision",
                parent_node_id=child.cursor.node_id, time=time, world_state=before,
                triggering_event=trigger.event, acting_agent=agent.id, plausible_actions=plausible,
                selected_action=action, decision_rationale=rationale, branch_role=branch_role)
            child.cursor.children.append(decision_node)
            child.cursor = decision_node
            child.trace.append(TraceEvent(time=time, agent_id=agent.id, event_type="decision",
                description=definition.description, action=action, trigger=trigger.event.description,
                previous_strategy=previous_strategy, current_strategy=strategy_transition.current,
                plausible_actions=plausible, rationale=rationale, event=trigger.event,
                previous_world_state=before, resulting_world_state=before,
                observations=context.observations.visible_world_variables,
                alternative_reason=alternative_reason,
                validity_reason="Available to this agent; trigger is active; compatibility, parameters, and constraints passed.",
                objective=context.objective, trigger_id=trigger.definition.id,
                strategy_change=target_strategy if target_strategy != previous_strategy else None,
                observation_snapshot=context.observations, decision_context=context,
                decision_response=response,
                decision_source=context.decision_source or "existing_policy_fallback",
                objective_score_margin=context.objective_score_margin,
                branch_role=branch_role,
                validation_status=response.validation_status,
                llm_audit=audit.model_copy(update={"selected_action": definition.id}, deep=True)
                    if audit is not None else None))
            transition_event = SimulationEvent(event_id=f"transition:{time}:{definition.id}:{self._node_sequence + 1}",
                time=time, event_type="action_transition", description=f"Apply action '{definition.name}'",
                actor_id=agent.id, data={"action_id": definition.id})
            transition_node = ScenarioNode(node_id=self._new_node_id(), node_type="transition",
                parent_node_id=child.cursor.node_id, time=time, world_state=child.world.model_copy(deep=True),
                triggering_event=transition_event, acting_agent=agent.id,
                decision_rationale="Action effects applied by the configured transition system.")
            child.cursor.children.append(transition_node)
            child.cursor = transition_node
            child.trace.append(TraceEvent(time=time, agent_id=agent.id, event_type="transition",
                description=transition_event.description, event=transition_event, state_changes=result.changes,
                previous_world_state=result.previous_state, resulting_world_state=child.world.model_copy(deep=True)))
            outputs.append((child, result))
        return outputs

    def append_transition(self, path: SimulationPath, event: SimulationEvent, result: TransitionResult) -> None:
        node = ScenarioNode(node_id=self._new_node_id(), node_type="transition",
            parent_node_id=path.cursor.node_id, time=event.time,
            world_state=path.world.model_copy(deep=True), triggering_event=event,
            decision_rationale="Configured transition rule applied.")
        path.cursor.children.append(node)
        path.cursor = node
        path.trace.append(TraceEvent(time=event.time, event_type="transition", description=event.description,
            event=event, state_changes=result.changes, previous_world_state=result.previous_state,
            resulting_world_state=path.world.model_copy(deep=True)))

    def append_event(self, path: SimulationPath, event: SimulationEvent) -> None:
        node = ScenarioNode(node_id=self._new_node_id(), node_type="event",
            parent_node_id=path.cursor.node_id, time=event.time,
            world_state=path.world.model_copy(deep=True), triggering_event=event)
        path.cursor.children.append(node)
        path.cursor = node
        path.trace.append(TraceEvent(time=event.time, event_type="event", description=event.description,
            event=event, previous_world_state=path.world.model_copy(deep=True),
            resulting_world_state=path.world.model_copy(deep=True)))

    def record_invalid_decision(self, path: SimulationPath, agent: AgentDefinition,
                                trigger: TriggerMatch, context: DecisionContext,
                                response: DecisionResponse, audit: DecisionAudit | None = None) -> None:
        candidates = [Action(action_id=item.id, agent_id=item.agent_id, name=item.name,
            category="decision", parameters=item.parameters, description=item.description)
            for item in context.available_actions]
        path.cursor.children.append(ScenarioNode(node_id=self._new_node_id(), node_type="decision",
            parent_node_id=path.cursor.node_id, time=context.time,
            world_state=path.world.model_copy(deep=True), triggering_event=trigger.event,
            acting_agent=agent.id, plausible_actions=candidates,
            decision_rationale="Decision rejected by validation; no world transition was applied."))
        path.trace.append(TraceEvent(time=context.time, agent_id=agent.id, event_type="decision",
            description="Decision rejected by validation", trigger=trigger.event.description,
            trigger_id=trigger.definition.id, previous_strategy=path.agents[agent.id].current_strategy,
            current_strategy=path.agents[agent.id].current_strategy, plausible_actions=candidates,
            rationale=response.rationale, event=trigger.event,
            previous_world_state=path.world.model_copy(deep=True),
            resulting_world_state=path.world.model_copy(deep=True),
            observations=context.observations.visible_world_variables, objective=context.objective,
            observation_snapshot=context.observations, decision_context=context,
            decision_response=response, validation_status=response.validation_status,
            decision_source=context.decision_source or "existing_policy_fallback",
            objective_score_margin=context.objective_score_margin,
            validity_reason="; ".join(response.validation_errors),
            llm_audit=audit.model_copy(deep=True) if audit is not None else None))

    def prune(self, paths: list[SimulationPath], time: int) -> list[SimulationPath]:
        result = self.pruner.prune(paths, time)
        for rejected in result.pruned:
            node = rejected.path.cursor
            node.status = "pruned"
            node.pruning_policy = result.policy
            node.pruning_reason = rejected.reason
            node.competing_retained_node_id = rejected.competing_retained_node_id
            self.pruning_records.append(PruningRecord(node_id=node.node_id, policy=result.policy,
                reason=rejected.reason, competing_retained_node_id=rejected.competing_retained_node_id))
        return result.retained

    def _new_node_id(self):
        self._node_sequence += 1
        return f"node-{self._node_sequence:06d}"
