"""Explicit events that can trigger agent reconsideration."""
from typing import Any
from pydantic import BaseModel, Field

class SimulationEvent(BaseModel):
    """A state-relevant occurrence emitted by an action or market update."""
    event_id: str
    time: int
    event_type: str
    description: str
    actor_id: str | None = None
    priority: int = 0
    data: dict[str, Any] = Field(default_factory=dict)
