"""API request/response models reuse validated domain definitions."""
from pydantic import BaseModel
from app.simulation.context import SimulationDefinition

class CreateSimulationRequest(SimulationDefinition):
    """A complete deterministic simulation definition."""

class SimulationCreated(BaseModel):
    simulation_id: str
    name: str
    status: str
