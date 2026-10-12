"""Generic agent definitions and branch-local runtime memory."""
from typing import Any, Literal
from pydantic import BaseModel, Field
from .action import Action

class AgentDefinition(BaseModel):
    """User-configured objectives, observations, actions, and policy rules."""
    id: str
    name: str
    type: str = "generic"
    objective: str
    secondary_objectives: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)
    observable_state: list[str] | str = "all"
    available_actions: list[str] = Field(default_factory=list)
    decision_policy: dict[str, Any] = Field(default_factory=lambda: {"type": "rule_based", "rules": []})
    memory_configuration: dict[str, Any] = Field(default_factory=dict)
    evidence_tags: list[str] = Field(default_factory=list)
    initial_strategy: str | None = None


class Belief(BaseModel):
    id: str
    proposition: str
    basis: str
    timestamp: int
    evidence_strength: str = "direct_observation"
    evidence_ids: list[str] = Field(default_factory=list)
    strength_label: Literal["weak", "limited", "moderate", "strong", "direct"] = "direct"
    last_updated: int | str | None = None
    related_variables: list[str] = Field(default_factory=list)
    related_events: list[str] = Field(default_factory=list)


class BeliefState(BaseModel):
    beliefs: list[Belief] = Field(default_factory=list)

    def update_observation(self, variables: dict[str, Any], timestamp: int,
                           event_ids: list[str]) -> list[Belief]:
        updated = []
        for variable, value in variables.items():
            belief_id = f"observed:{variable}"
            proposition = f"{variable} is {value!r}"
            existing = next((item for item in self.beliefs if item.id == belief_id), None)
            if existing is None or existing.proposition != proposition:
                belief = Belief(id=belief_id, proposition=proposition,
                    basis="Directly observed world state", timestamp=timestamp,
                    related_variables=[variable], related_events=list(event_ids),
                    strength_label="direct", last_updated=timestamp)
                if existing is None:
                    self.beliefs.append(belief)
                else:
                    self.beliefs[self.beliefs.index(existing)] = belief
                updated.append(belief)
            elif event_ids:
                existing.related_events = list(dict.fromkeys([*existing.related_events, *event_ids]))
                existing.timestamp = timestamp
                existing.last_updated = timestamp
        return updated

    def apply_updates(self, updates: list[Belief]) -> None:
        for belief in updates:
            existing = next((item for item in self.beliefs if item.id == belief.id), None)
            if existing is None:
                self.beliefs.append(belief.model_copy(deep=True))
            else:
                self.beliefs[self.beliefs.index(existing)] = belief.model_copy(deep=True)


class AgentMemory(BaseModel):
    previous_decisions: list[dict[str, Any]] = Field(default_factory=list)
    previous_actions: list[str] = Field(default_factory=list)
    decision_times: list[int] = Field(default_factory=list)
    rationales: list[str] = Field(default_factory=list)
    observations: list[dict[str, Any]] = Field(default_factory=list)
    important_events: list[dict[str, Any]] = Field(default_factory=list)
    strategy_changes: list[dict[str, Any]] = Field(default_factory=list)

    # Preserve the old list-style access used by existing clients and tests.
    def __getitem__(self, index):
        if isinstance(index, str):
            return getattr(self, index)
        return self.previous_decisions[index]

    def __len__(self):
        return len(self.previous_decisions)

    def __iter__(self):
        return iter(self.previous_decisions)

    def append(self, decision: dict[str, Any]) -> None:
        self.previous_decisions.append(decision)
        if "action_id" in decision:
            self.previous_actions.append(decision["action_id"])
        if "time" in decision:
            self.decision_times.append(decision["time"])
        if "rationale" in decision:
            self.rationales.append(decision["rationale"])
        if isinstance(decision.get("observations"), dict):
            self.observations.append(dict(decision["observations"]))

class AgentState(BaseModel):
    """Persistent strategy and decision memory for one scenario path."""
    agent_id: str
    current_strategy: str | None = None
    previous_actions: list[str] = Field(default_factory=list)
    last_decision_time: int | None = None
    reason_current_strategy: str = ""
    relevant_observations: dict[str, Any] = Field(default_factory=dict)
    memory: AgentMemory = Field(default_factory=AgentMemory)
    belief_state: BeliefState = Field(default_factory=BeliefState)
    last_trigger_times: dict[str, int] = Field(default_factory=dict)

    def remember(self, action: Action, time: int, trigger: str, rationale: str,
                 observations: dict[str, Any]) -> None:
        """Persist the selected strategy and its decision context."""
        previous_strategy = self.current_strategy
        self.previous_actions.append(action.action_id)
        self.last_decision_time = time
        self.reason_current_strategy = rationale
        self.relevant_observations = dict(observations)
        decision = {"time": time, "action": action.name, "action_id": action.action_id,
                    "trigger": trigger, "rationale": rationale, "observations": dict(observations)}
        self.memory.previous_decisions.append(decision)
        self.memory.previous_actions.append(action.action_id)
        self.memory.decision_times.append(time)
        self.memory.rationales.append(rationale)
        self.memory.observations.append(dict(observations))
        if previous_strategy != self.current_strategy:
            self.memory.strategy_changes.append({"time": time, "from": previous_strategy,
                                                 "to": self.current_strategy, "action_id": action.action_id})

    def remember_event(self, event: dict[str, Any]) -> None:
        self.memory.important_events.append(dict(event))

# Compatibility name for older example factories. New definitions use AgentDefinition.
class Agent(AgentDefinition):
    """Legacy combined definition/runtime object retained for sample factories."""
    current_strategy: str | None = None
    previous_actions: list[str] = Field(default_factory=list)
    last_decision_time: int | None = None
    reason_current_strategy: str = ""
    relevant_observations: dict[str, Any] = Field(default_factory=dict)
    memory: AgentMemory = Field(default_factory=AgentMemory)
    belief_state: BeliefState = Field(default_factory=BeliefState)
    decision_history: list[dict[str, Any]] = Field(default_factory=list)

    def observe(self, state) -> dict[str, Any]:
        """Return only configured observable state, or all variables."""
        values = state.as_variables()
        if self.observable_state == "all":
            return values
        return {key: values[key] for key in self.observable_state if key in values}

    def action(self, name: str, category: str, parameters: dict, description: str) -> Action:
        """Create an available action record for older example code."""
        if name not in self.available_actions:
            raise ValueError(f"{name!r} is not available to agent {self.id}")
        return Action(action_id=f"{self.id}:{name}", agent_id=self.id, name=name,
                      category=category, parameters=parameters, description=description)
