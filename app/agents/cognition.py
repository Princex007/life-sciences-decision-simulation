"""Filtered observations and stable, serializable agent decision contracts."""
from copy import deepcopy
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from app.domain.agent import AgentDefinition, AgentState, Belief
from app.domain.action import ActionDefinition
from app.domain.event import SimulationEvent
from app.domain.world import WorldState
from app.domain.evidence import Evidence


class ObservedEvent(BaseModel):
    event_id: str
    time: int
    event_type: str
    description: str
    actor_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class AgentObservation(BaseModel):
    timestamp: int
    visible_world_variables: dict[str, Any] = Field(default_factory=dict)
    relevant_events: list[ObservedEvent] = Field(default_factory=list)
    relevant_state_changes: dict[str, Any] = Field(default_factory=dict)
    relevant_evidence: list[Evidence] = Field(default_factory=list)


class ObservationModel:
    """Project a world state into only the variables and event facts an agent may see."""
    SAFE_EVENT_METADATA = {"trigger_id"}

    def observe(self, agent: AgentDefinition, world_state: WorldState,
                events: list[SimulationEvent] | None = None,
                state_changes: dict[str, Any] | None = None,
                evidence: list[Evidence] | None = None) -> AgentObservation:
        world_variables = deepcopy(world_state.as_variables())
        permitted = set(world_variables) if agent.observable_state == "all" else set(agent.observable_state)
        visible = {key: value for key, value in world_variables.items() if key in permitted}
        observed_events = []
        for event in events or []:
            safe_data = deepcopy({key: value for key, value in event.data.items()
                         if key in permitted or key in self.SAFE_EVENT_METADATA}
            )
            observed_events.append(ObservedEvent(event_id=event.event_id, time=event.time,
                event_type=event.event_type, description=event.description,
                actor_id=event.actor_id, data=safe_data))
        changes = deepcopy({key: value for key, value in (state_changes or {}).items() if key in permitted})
        visible_evidence = [item.model_copy(deep=True) for item in (evidence or [])
                            if "*" in item.visible_to_agents or "all" in item.visible_to_agents
                            or agent.id in item.visible_to_agents]
        return AgentObservation(timestamp=world_state.time, visible_world_variables=visible,
            relevant_events=observed_events, relevant_state_changes=changes,
            relevant_evidence=visible_evidence)


class DecisionContext(BaseModel):
    agent_id: str
    agent_name: str
    agent_type: str
    time: int
    trigger: ObservedEvent
    objective: str
    secondary_objectives: list[str] = Field(default_factory=list)
    current_strategy: str | None = None
    observations: AgentObservation
    relevant_beliefs: list[Belief] = Field(default_factory=list)
    relevant_memory: dict[str, Any] = Field(default_factory=dict)
    available_actions: list[ActionDefinition] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)
    policy_configuration: dict[str, Any] = Field(default_factory=dict)
    relevant_evidence: list[Evidence] = Field(default_factory=list)
    action_previews: dict[str, dict[str, Any]] = Field(default_factory=dict)
    objective_scores: dict[str, dict[str, Any]] = Field(default_factory=dict)
    objective_score_margin: float | None = None
    decision_source: str | None = None
    decision_reason: str | None = None


class DecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    primary_action: str
    alternative_actions: list[str] = Field(default_factory=list)
    rationale: str = ""
    key_drivers: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    facts_used: list[str] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)
    belief_updates: list[Belief] = Field(default_factory=list)
    strategy_change: str | None = None
    validation_status: str = "pending"
    validation_errors: list[str] = Field(default_factory=list)


class DecisionAudit(BaseModel):
    provider: str
    model: str
    model_version: str | None = None
    prompt_context_version: str
    timestamp: str
    agent_id: str
    trigger: ObservedEvent
    input_context: DecisionContext
    raw_provider_response: str = ""
    parsed_response: DecisionResponse
    validation_result: str = "pending"
    validation_errors: list[str] = Field(default_factory=list)
    selected_action: str | None = None


def build_decision_context(agent: AgentDefinition, state: AgentState,
                           observation: AgentObservation, trigger: ObservedEvent,
                           actions: list[ActionDefinition]) -> DecisionContext:
    visible_keys = set(observation.visible_world_variables)
    related = [belief for belief in state.belief_state.beliefs
               if set(belief.related_variables).issubset(visible_keys)]
    def filtered_observation(values):
        return {key: value for key, value in values.items() if key in visible_keys}
    decisions = []
    for item in state.memory.previous_decisions[-10:]:
        copy = dict(item)
        if isinstance(copy.get("observations"), dict):
            copy["observations"] = filtered_observation(copy["observations"])
        decisions.append(copy)
    memory = {
        "previous_decisions": decisions,
        "previous_actions": state.memory.previous_actions[-10:],
        "decision_times": state.memory.decision_times[-10:],
        "rationales": state.memory.rationales[-10:],
        "observations": [filtered_observation(values) for values in state.memory.observations[-10:]],
        "important_events": state.memory.important_events[-10:],
        "strategy_changes": state.memory.strategy_changes[-10:],
    }
    return DecisionContext(agent_id=agent.id, agent_name=agent.name, agent_type=agent.type,
        time=observation.timestamp, trigger=trigger, objective=agent.objective,
        secondary_objectives=deepcopy(agent.secondary_objectives), current_strategy=state.current_strategy,
        observations=deepcopy(observation), relevant_beliefs=deepcopy(related), relevant_memory=deepcopy(memory),
        available_actions=deepcopy(actions), constraints=deepcopy(agent.constraints), resources=deepcopy(agent.resources),
        policy_configuration=deepcopy(agent.decision_policy),
        relevant_evidence=deepcopy(observation.relevant_evidence))
