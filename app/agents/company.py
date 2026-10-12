"""Company launch agent factory."""
from app.domain.agent import Agent
def create_company() -> Agent:
    """Create the launching company participant."""
    return Agent(id="company", name="Company", type="company", objective="maximize sustainable adoption", available_actions=["launch", "maintain_promotion"])
