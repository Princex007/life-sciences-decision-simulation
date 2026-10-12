"""Physician agent factory."""
from app.domain.agent import Agent
def create_physician() -> Agent:
    """Create an efficacy and access sensitive prescriber."""
    return Agent(id="physician", name="Physician", type="physician", objective="select effective accessible therapy", available_actions=["slow_adoption", "adopt", "maintain_adoption"])
