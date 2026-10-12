"""Serializable, data-driven simulation definitions."""
from typing import Any, Literal
from pydantic import BaseModel, Field
from .agent import AgentDefinition
from .action import ActionDefinition, ActionEffect
from .driver import ExternalDriver
from .world import WorldState
from .evidence import Evidence

class TriggerDefinition(BaseModel):
    """Event or state-change trigger subscribed by configured agents."""
    id: str
    event_types: list[str] = Field(default_factory=list)
    affected_agents: list[str] = Field(default_factory=list)
    state_condition: dict[str, Any] | None = None
    priority: int = 0
    cooldown: int = 0
    expires_after: int | None = None

class TransitionRule(BaseModel):
    """Effects applied when an event of the configured type is processed."""
    id: str
    event_type: str
    effects: list[ActionEffect] = Field(default_factory=list)

class ScheduledEventDefinition(BaseModel):
    """A deterministic event scheduled at a simulation time."""
    id: str
    time: int
    event_type: str
    description: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0

class SimulationSettings(BaseModel):
    """Clock, scheduled events, and kernel-independent execution settings."""
    time_horizon: int = 8
    step_duration: float = 1.0
    step_unit: str = "step"
    initial_events: list[ScheduledEventDefinition] = Field(default_factory=lambda: [
        ScheduledEventDefinition(id="simulation-start", time=0, event_type="simulation_start",
                                 description="Simulation begins", priority=100)])
    scheduled_events: list[ScheduledEventDefinition] = Field(default_factory=list)
    transient_variables: list[str] = Field(default_factory=list)
    decision_policy: Literal["rule_based", "llm"] = "rule_based"

class ScenarioGenerationSettings(BaseModel):
    """Configurable scenario pruning strategy."""
    policy: str = "diversity"
    max_scenarios: int | None = 9
    diversity_by_agents: list[str] = Field(default_factory=list)
    safety_limit: int = 1000

class SimulationMetadata(BaseModel):
    """Human-readable simulation identity and domain metadata."""
    id: str
    name: str
    description: str = ""
    domain: str = "general"

class SimulationDefinition(BaseModel):
    """Complete definition consumed by the generic simulation engine."""
    metadata: SimulationMetadata
    initial_world_state: WorldState
    world_variable_metadata: dict[str, dict[str, Any]] = Field(default_factory=dict)
    evaluation_objectives: dict[str, dict[str, Any]] = Field(default_factory=dict)
    clinical_outcome_assumptions: dict[str, Any] = Field(default_factory=dict)
    patient_affordability_assumptions: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    agents: list[AgentDefinition]
    action_definitions: list[ActionDefinition] = Field(default_factory=list)
    trigger_definitions: list[TriggerDefinition] = Field(default_factory=list)
    transition_rules: list[TransitionRule] = Field(default_factory=list)
    settings: SimulationSettings = Field(default_factory=SimulationSettings)
    forecast_model_id: str | None = None
    scenario_generation: ScenarioGenerationSettings = Field(default_factory=ScenarioGenerationSettings)
    external_drivers: list[ExternalDriver] = Field(default_factory=list)

    @classmethod
    def from_json(cls, path: str) -> "SimulationDefinition":
        """Load and validate a complete simulation definition from JSON."""
        from pathlib import Path
        import json
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
