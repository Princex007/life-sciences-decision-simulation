"""Scenario paths, complete lineage trees, and decision traces."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field
from .action import Action
from .agent import AgentState
from .event import SimulationEvent
from .outcome import Outcome
from .world import WorldState
from app.agents.cognition import AgentObservation, DecisionAudit, DecisionContext, DecisionResponse

class TraceEvent(BaseModel):
    """One decision or simulation transition with before/after audit state."""
    time: int
    agent_id: str | None = None
    event_type: str
    description: str
    action: Action | None = None
    trigger: str | None = None
    previous_strategy: str | None = None
    plausible_actions: list[Action] = Field(default_factory=list)
    rationale: str = ""
    event: SimulationEvent | None = None
    state_changes: dict[str, Any] = Field(default_factory=dict)
    previous_world_state: WorldState | None = None
    resulting_world_state: WorldState | None = None
    observations: dict[str, Any] = Field(default_factory=dict)
    current_strategy: str | None = None
    strategy_change: str | None = None
    alternative_reason: str = ""
    validity_reason: str = ""
    objective: str = ""
    trigger_id: str = ""
    observation_snapshot: AgentObservation | None = None
    decision_context: DecisionContext | None = None
    decision_response: DecisionResponse | None = None
    llm_audit: DecisionAudit | None = None
    validation_status: str = ""
    decision_source: str = ""
    objective_score_margin: float | None = None
    branch_role: Literal["selected", "counterfactual"] = "selected"

class ScenarioNode(BaseModel):
    """A node in the executable causal scenario tree."""
    node_id: str
    node_type: Literal["root", "event", "decision", "transition"] = "event"
    parent_node_id: str | None = None
    time: int
    world_state: WorldState
    triggering_event: SimulationEvent | None = None
    acting_agent: str | None = None
    plausible_actions: list[Action] = Field(default_factory=list)
    selected_action: Action | None = None
    decision_rationale: str = ""
    branch_role: Literal["selected", "counterfactual"] = "selected"
    status: Literal["active", "pruned", "terminal"] = "active"
    pruning_policy: str | None = None
    pruning_reason: str | None = None
    competing_retained_node_id: str | None = None
    children: list[ScenarioNode] = Field(default_factory=list)

class PruningRecord(BaseModel):
    node_id: str
    policy: str
    reason: str
    competing_retained_node_id: str | None = None

class Scenario(BaseModel):
    """A terminal path through a scenario tree."""
    scenario_id: str
    name: str
    actions: list[Action] = Field(default_factory=list)
    final_state: WorldState
    forecast: Outcome | None = None
    key_drivers: list[str] = Field(default_factory=list)
    decision_trace: list[TraceEvent] = Field(default_factory=list)
    snapshots: list[WorldState] = Field(default_factory=list)
    agent_states: list[AgentState] = Field(default_factory=list)
    terminal_node_id: str

class SimulationResult(BaseModel):
    """Full tree plus terminal forecast paths."""
    simulation_id: str
    name: str
    root: ScenarioNode
    scenarios: list[Scenario]
    pruning_records: list[PruningRecord] = Field(default_factory=list)

    def __iter__(self):
        """Allow legacy callers to iterate the terminal scenario paths."""
        return iter(self.scenarios)

    def __len__(self):
        return len(self.scenarios)

    def __getitem__(self, index):
        return self.scenarios[index]
