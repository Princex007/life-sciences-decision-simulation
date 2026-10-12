"""Payer agent factory."""
from app.domain.agent import Agent
def create_payer() -> Agent:
    """Create a cost and access balancing payer."""
    return Agent(id="payer", name="Payer", type="payer", objective="balance access and affordability", available_actions=["restricted_access", "standard_access", "favorable_access"])
