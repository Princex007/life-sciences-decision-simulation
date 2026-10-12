"""Patient agent factory."""
from app.domain.agent import Agent
def create_patient() -> Agent:
    """Create a patient adoption participant."""
    return Agent(id="patient", name="Patient", type="patient", objective="access suitable treatment", available_actions=[])
