"""Forecasting interface."""
from typing import Protocol
from app.domain.world import WorldState
from app.domain.outcome import Outcome

class ForecastModel(Protocol):
    """Maps a market state path to quantitative outcomes.

    ``context`` carries the run inputs that are not world state: the definition (so a
    driver model can read its configured trajectories) and the stored product history.
    Models that need neither ignore it.
    """
    def forecast(self, final_state: WorldState, snapshots: list[WorldState], scenario,
                 context=None) -> Outcome: ...
