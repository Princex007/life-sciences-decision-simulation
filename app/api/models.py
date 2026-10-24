"""API request/response models reuse validated domain definitions."""
from typing import Literal

from pydantic import BaseModel, Field
from app.domain.driver import DriverPathway
from app.simulation.context import SimulationDefinition

class CreateSimulationRequest(SimulationDefinition):
    """A complete deterministic simulation definition."""

class SimulationCreated(BaseModel):
    simulation_id: str
    name: str
    status: str

class TimeSeriesForecastRequest(BaseModel):
    """An observed period series to project forward without running a simulation."""
    values: list[float] = Field(min_length=2, max_length=500)
    periods_ahead: int = Field(default=4, ge=1, le=60)
    label: str = Field(default="", max_length=80)


class ReferenceAnalogueRequest(BaseModel):
    """A stored product's recorded shape, stretched to a peak, projected without a simulation."""
    history_id: str = Field(min_length=1, max_length=80)
    peak: float = Field(gt=0)
    periods_ahead: int = Field(default=4, ge=1, le=60)


class DriverIndexTrajectory(BaseModel):
    """One exogenous driver: how its index level is carried into the horizon, and its pathway.

    ``basis`` picks between the two ways a driver can be continued past the last known period.
    ``observed`` fits a least-squares straight line through the recorded index readings and
    continues that line; ``compound`` grows an index anchored at t0 geometrically at
    ``growth_rate`` per period. The pathway is the domain model's own ``DriverPathway``, so
    operation, magnitude, bounds, evidence grade and the hypothesis-only flag mean here exactly
    what they mean inside a run.
    """
    name: str = Field(min_length=1, max_length=60)
    basis: Literal["observed", "compound"] = "observed"
    levels: list[float] = Field(default_factory=list, max_length=500)
    initial_level: float | None = None
    growth_rate: float | None = None
    pathway: DriverPathway


class AffectedVariable(BaseModel):
    """One variable a pathway acts on: its value at t0 and its own growth rate per period.

    ``growth_rate`` is the variable's organic drift — the path it would follow with no driver at
    all. Driver pathways are applied on top of it, so the two contributions stay separable.
    """
    name: str = Field(min_length=1, max_length=80)
    # No default: a missing baseline must be refused, not silently projected from zero.
    value: float
    # What one unit of this variable's value means, e.g. "treated patients per quarter". Stored so
    # the result can name the metric beside every number; a factor never converts between units.
    unit: str = Field(default="", max_length=80)
    growth_rate: float | None = None


class DriverScenarioRequest(BaseModel):
    """Several drivers, each with its own index and pathway, projected without a simulation.

    Drivers fire in listed order in every projected period, the same order
    ``DriverProjectionForecast`` uses past a run's horizon, so two pathways on one variable stack
    deterministically here and there.
    """
    drivers: list[DriverIndexTrajectory] = Field(min_length=1, max_length=20)
    variables: list[AffectedVariable] = Field(min_length=1, max_length=20)
    periods_ahead: int = Field(default=4, ge=1, le=60)

class TableImportRequest(BaseModel):
    """One uploaded CSV or Excel file, sent as base64 so no multipart dependency is needed."""
    file_name: str = Field(min_length=1, max_length=200)
    data: str = Field(min_length=1)
    sheet: str = Field(default="", max_length=100)

class ReferenceSuggestionRequest(BaseModel):
    """The new product in the user's own words, matched against stored product histories."""
    profile: str = Field(min_length=20, max_length=4000)
