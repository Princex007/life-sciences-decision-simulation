"""Competitor agent factory."""
from app.domain.agent import Agent
def create_competitor() -> Agent:
    """Create a share-protecting competitor."""
    return Agent(id="competitor", name="Competitor", type="competitor", objective="protect_market_share", constraints={"min_price": 50_000}, available_actions=["aggressive_price_cut", "increase_promotion", "maintain_strategy", "delay_response"])
