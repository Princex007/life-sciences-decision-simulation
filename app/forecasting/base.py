"""Forecasting interface."""
from typing import Protocol
from app.domain.world import WorldState
from app.domain.outcome import Outcome

class ForecastModel(Protocol):
    """Maps a market state path to quantitative outcomes."""
    def forecast(self, final_state: WorldState, snapshots: list[WorldState], scenario) -> Outcome: ...
