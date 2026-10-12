"""Generic action definitions and selected action records."""
from typing import Any
from pydantic import BaseModel, Field

class ActionEffect(BaseModel):
    """Declarative update to a named world variable."""
    variable: str
    operation: str = "set"
    value: Any
    minimum: float | None = None
    maximum: float | None = None

class ActionDefinition(BaseModel):
    """Configuration describing an agent action and its world effects."""
    id: str
    name: str
    agent_id: str
    description: str = ""
    strategy: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    parameter_schema: dict[str, dict[str, Any]] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    effects: list[ActionEffect] = Field(default_factory=list)
    generated_events: list[dict[str, Any]] = Field(default_factory=list)

class Action(BaseModel):
    """A selected instance of an ActionDefinition."""
    action_id: str
    agent_id: str
    name: str
    category: str = "strategy"
    parameters: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
