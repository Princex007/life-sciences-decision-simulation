"""Run-level inputs a forecast model can need beyond the world state itself."""
from dataclasses import dataclass

from app.domain.definitions import SimulationDefinition
from app.domain.history import ProductHistory


@dataclass(frozen=True)
class ForecastContext:
    """Everything a forecast plugin may read that is not world state.

    A driver projection needs the configured trajectories, a historical forecast needs the
    stored series the definition points at, and a reference analogue needs another product's
    stored series. All are run inputs, so they are passed in rather than reached for
    through a global.
    """
    definition: SimulationDefinition | None = None
    history: ProductHistory | None = None
    reference_history: ProductHistory | None = None
    projection_periods: int = 4
